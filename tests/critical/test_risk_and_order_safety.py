"""Server-side risk, stop-control, freshness, and idempotency contracts."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
)
from apps.broker_execution.infrastructure.models import BrokerAccountSnapshotModel, LiveOrderModel
from apps.broker_execution.infrastructure.repositories import (
    DjangoBrokerExecutionRepository,
)
from tests.unit.broker_execution.test_api_and_permissions import (
    _binding,
    _order,
    _user,
)
from tests.unit.broker_execution.test_api_and_permissions import (
    test_admin_global_kill_switch_stops_every_active_bound_account as _assert_global_stop,
)
from tests.unit.broker_execution.test_api_and_permissions import (
    test_kill_switch_blocks_approval_but_still_allows_rejection as _assert_stop_semantics,
)
from tests.unit.broker_execution.test_api_and_permissions import (
    test_owner_can_preview_commit_and_replay_approval as _assert_approval_idempotency,
)
from tests.unit.broker_execution.test_api_and_permissions import (
    test_submit_ack_rechecks_limits_and_allow_list_after_approval as _assert_final_submit_recheck,
)
from tests.unit.broker_execution.test_risk_and_reconciliation import (
    test_live_order_creation_fails_closed_on_server_risk_rejection as _assert_server_risk_rejection,
)


def _approve_order(owner, order) -> None:
    client = Client()
    client.force_login(owner)
    endpoint = f"/api/broker-execution/orders/{order.client_order_id}/approve/"
    preview = client.post(
        endpoint,
        data=json.dumps({"preview_only": True, "reason": "critical gate"}),
        content_type="application/json",
    )
    assert preview.status_code == 200
    commit = client.post(
        endpoint,
        data=json.dumps(
            {
                "preview_only": False,
                "reason": "critical gate",
                "expected_version": preview.json()["data"]["order"]["version"],
                "idempotency_key": f"critical-{order.client_order_id}",
            }
        ),
        content_type="application/json",
    )
    assert commit.status_code == 200


@pytest.mark.django_db
def test_server_risk_rejection_remains_non_executable() -> None:
    """Caller-provided risk cannot bypass an authoritative server rejection."""

    _assert_server_risk_rejection()


@pytest.mark.django_db
def test_stop_state_blocks_approval_but_allows_risk_reduction() -> None:
    """A kill switch blocks new exposure while preserving rejection operations."""

    _assert_stop_semantics()


@pytest.mark.django_db
def test_global_kill_switch_stops_all_bound_accounts() -> None:
    """The global stop cannot be bypassed by selecting another bound account."""

    _assert_global_stop()


@pytest.mark.django_db
def test_stale_broker_snapshot_prevents_order_leasing() -> None:
    """An approved order cannot reach an Agent with stale broker account facts."""

    owner = _user("critical-stale-snapshot-owner", "owner")
    agent, binding = _binding(owner, account_id=172)
    binding.enforce_trading_session = False
    binding.max_snapshot_age_seconds = 60
    binding.save(
        update_fields=[
            "enforce_trading_session",
            "max_snapshot_age_seconds",
            "updated_at",
        ]
    )
    order = _order(owner, agent, account_id=172)
    _approve_order(owner, order)
    agent.status = agent.STATUS_ONLINE
    agent.qmt_connected = True
    agent.last_heartbeat_at = timezone.now()
    agent.save(update_fields=["status", "qmt_connected", "last_heartbeat_at", "updated_at"])
    BrokerAccountSnapshotModel.objects.create(
        user=owner,
        agent=agent,
        account_id=172,
        captured_at=timezone.now() - timedelta(seconds=61),
        cash_available=Decimal("100000"),
        total_asset=Decimal("100000"),
    )

    leased = DjangoBrokerExecutionRepository().lease_agent_orders(
        agent_pk=agent.pk,
        allowed_account_ids=[172],
        limit=1,
        lease_seconds=30,
    )

    order.refresh_from_db()
    assert leased["orders"] == []
    assert order.status == "READY"


@pytest.mark.django_db
def test_final_submission_rechecks_authorization_limits_and_allow_list() -> None:
    """Approval does not freeze mutable account safety controls."""

    _assert_final_submit_recheck()


@pytest.mark.django_db
def test_approval_replay_persists_one_audit_result() -> None:
    """Repeated approval requests are idempotent at the persistence boundary."""

    _assert_approval_idempotency()


@pytest.mark.django_db
def test_disconnected_agent_cannot_lease_orders() -> None:
    """QMT disconnect stops order pickup before any broker-side submission."""

    owner = _user("critical-disconnected-owner", "owner")
    agent, _binding_model = _binding(owner, account_id=173)
    agent.status = agent.STATUS_ONLINE
    agent.qmt_connected = False
    agent.save(update_fields=["status", "qmt_connected", "updated_at"])

    with pytest.raises(BrokerExecutionConflictError, match="not online"):
        DjangoBrokerExecutionRepository().lease_agent_orders(
            agent_pk=agent.pk,
            allowed_account_ids=[173],
            limit=1,
            lease_seconds=30,
        )


@pytest.mark.django_db
def test_expired_heartbeat_marks_agent_offline_before_leasing() -> None:
    """Maintenance converts a missing heartbeat into a hard leasing stop."""

    owner = _user("critical-stale-heartbeat-owner", "owner")
    agent, _binding_model = _binding(owner, account_id=174)
    agent.status = agent.STATUS_ONLINE
    agent.qmt_connected = True
    agent.last_heartbeat_at = timezone.now() - timedelta(seconds=91)
    agent.save(update_fields=["status", "qmt_connected", "last_heartbeat_at", "updated_at"])

    result = DjangoBrokerExecutionRepository().run_maintenance()

    agent.refresh_from_db()
    assert result["stale_agents"] == 1
    assert agent.status == agent.STATUS_OFFLINE
    assert agent.qmt_connected is False
    assert LiveOrderModel.objects.filter(agent=agent, status="LEASED").exists() is False
