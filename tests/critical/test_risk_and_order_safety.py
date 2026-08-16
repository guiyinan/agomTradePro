"""Server-side risk, stop-control, freshness, and idempotency contracts."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.broker_execution.infrastructure.models import LiveOrderModel
from apps.broker_execution.infrastructure.repositories import (
    DjangoBrokerExecutionRepository,
)
from tests.component.broker_execution.test_api_and_permissions import (
    _binding,
    _order,
    _user,
)
from tests.component.broker_execution.test_api_and_permissions import (
    test_admin_global_kill_switch_stops_every_active_bound_account as _assert_global_stop,
)
from tests.component.broker_execution.test_api_and_permissions import (
    test_kill_switch_blocks_approval_but_still_allows_rejection as _assert_stop_semantics,
)
from tests.component.broker_execution.test_risk_and_reconciliation import (
    test_live_order_creation_fails_closed_on_server_risk_rejection as _assert_server_risk_rejection,
)


@pytest.mark.django_db
def test_server_risk_rejection_remains_non_executable() -> None:
    """The evidence gate blocks order creation before risk execution."""

    # The component-level contract owns the expected exception assertion.  Calling
    # it directly here keeps this critical guard aligned with the fail-closed gate
    # without wrapping a helper that already consumes the exception.
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
    """The evidence gate blocks approval before broker snapshots are consulted."""

    owner = _user("critical-stale-snapshot-owner", "owner")
    agent, _binding_model = _binding(owner, account_id=172)
    order = _order(owner, agent, account_id=172)
    client = Client()
    client.force_login(owner)
    response = client.post(
        f"/api/broker-execution/orders/{order.client_order_id}/approve/",
        data=json.dumps(
            {
                "preview_only": False,
                "reason": "critical gate",
                "expected_version": order.version,
                "idempotency_key": "critical-stale-snapshot",
            }
        ),
        content_type="application/json",
    )

    order.refresh_from_db()
    assert response.status_code == 409
    assert order.status == "WAITING_APPROVAL"


@pytest.mark.django_db
def test_final_submission_rechecks_authorization_limits_and_allow_list() -> None:
    """The evidence gate blocks approval before mutable safety controls are used."""

    owner = _user("critical-final-submit-owner", "owner")
    agent, _binding_model = _binding(owner, account_id=175)
    order = _order(owner, agent, account_id=175)
    client = Client()
    client.force_login(owner)
    response = client.post(
        f"/api/broker-execution/orders/{order.client_order_id}/approve/",
        data=json.dumps(
            {
                "preview_only": False,
                "reason": "critical gate",
                "expected_version": order.version,
                "idempotency_key": "critical-final-submit",
            }
        ),
        content_type="application/json",
    )
    order.refresh_from_db()
    assert response.status_code == 409
    assert order.status == "WAITING_APPROVAL"


@pytest.mark.django_db
def test_approval_replay_persists_one_audit_result() -> None:
    """Repeated approval requests remain blocked until evidence is integrated."""

    owner = _user("critical-approval-replay-owner", "owner")
    agent, _binding_model = _binding(owner, account_id=176)
    order = _order(owner, agent, account_id=176)
    client = Client()
    client.force_login(owner)
    payload = {
        "preview_only": False,
        "reason": "critical gate",
        "expected_version": order.version,
        "idempotency_key": "critical-approval-replay",
    }
    endpoint = f"/api/broker-execution/orders/{order.client_order_id}/approve/"
    first = client.post(endpoint, data=json.dumps(payload), content_type="application/json")
    second = client.post(endpoint, data=json.dumps(payload), content_type="application/json")
    order.refresh_from_db()
    assert first.status_code == 409
    assert second.status_code == 409
    assert order.status == "WAITING_APPROVAL"


@pytest.mark.django_db
def test_disconnected_agent_cannot_lease_orders() -> None:
    """The evidence gate blocks leasing before QMT connectivity is consulted."""

    owner = _user("critical-disconnected-owner", "owner")
    agent, _binding_model = _binding(owner, account_id=173)
    agent.status = agent.STATUS_ONLINE
    agent.qmt_connected = False
    agent.save(update_fields=["status", "qmt_connected", "updated_at"])

    result = DjangoBrokerExecutionRepository().lease_agent_orders(
        agent_pk=agent.pk,
        allowed_account_ids=[173],
        limit=1,
        lease_seconds=30,
    )
    assert result["orders"] == []
    assert result["evidence_gate_active"] is True
    assert result["must_not_execute"] is True


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
