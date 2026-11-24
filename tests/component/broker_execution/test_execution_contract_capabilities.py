"""Persisted capability declarations gate new leases and submitting ACKs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.broker_execution.application.agent_auth import build_agent_signature
from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError
from apps.broker_execution.domain.execution_contract_capabilities import (
    EXECUTION_CONSTRAINT_SCHEMA_V2,
)
from apps.broker_execution.infrastructure import broker_repository_agent_runtime as runtime
from apps.broker_execution.infrastructure.models import (
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    LiveOrderModel,
    OrderLeaseModel,
    TradingControlModel,
)
from apps.broker_execution.infrastructure.repositories import DjangoBrokerExecutionRepository

pytestmark = pytest.mark.django_db


def _bound_agent() -> BrokerAgentModel:
    user = get_user_model().objects.create_user(username="execution-contract-owner")
    agent = BrokerAgentModel.objects.create(
        user=user, agent_id="contract-agent", display_name="Fixture"
    )
    BrokerAccountBindingModel.objects.create(
        user=user, agent=agent, account_id=7, broker_account_ref="fixture-account"
    )
    return agent


def test_heartbeat_persists_v2_declaration_and_legacy_update_clears_it() -> None:
    agent = _bound_agent()
    repository = DjangoBrokerExecutionRepository()
    payload: dict[str, object] = {
        "account_ids": [7],
        "observed_at": timezone.now().isoformat(),
        "qmt_connected": True,
        "agent_version": "0.2.0",
        "dry_run": True,
        "execution_constraint_schemas": [EXECUTION_CONSTRAINT_SCHEMA_V2],
    }
    repository.heartbeat_agent(agent_pk=agent.pk, allowed_account_ids=[7], payload=payload)
    agent.refresh_from_db()
    assert agent.health_snapshot["execution_constraint_schemas"] == [EXECUTION_CONSTRAINT_SCHEMA_V2]
    payload.pop("execution_constraint_schemas")
    repository.heartbeat_agent(agent_pk=agent.pk, allowed_account_ids=[7], payload=payload)
    agent.refresh_from_db()
    assert agent.health_snapshot["execution_constraint_schemas"] == []


def test_missing_capability_cannot_create_a_lease_even_with_evidence_gate_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _bound_agent()
    monkeypatch.setattr(runtime, "broker_order_evidence_integrated", lambda: True)
    with pytest.raises(BrokerExecutionConflictError, match="AGENT_EXECUTION_CONTRACT_UNSUPPORTED"):
        DjangoBrokerExecutionRepository().lease_agent_orders(
            agent_pk=agent.pk, allowed_account_ids=[7], limit=1, lease_seconds=30
        )
    assert OrderLeaseModel.objects.count() == 0


def test_missing_capability_cannot_advance_a_leased_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _bound_agent()
    order = LiveOrderModel.objects.create(
        user=agent.user,
        account_id=7,
        agent=agent,
        asset_code="600000.SH",
        side="BUY",
        quantity=Decimal("100"),
        limit_price=Decimal("10"),
        status="LEASED",
        expires_at=timezone.now() + timedelta(minutes=1),
    )
    monkeypatch.setattr(runtime, "broker_order_evidence_integrated", lambda: True)
    with pytest.raises(BrokerExecutionConflictError, match="AGENT_EXECUTION_CONTRACT_UNSUPPORTED"):
        DjangoBrokerExecutionRepository().acknowledge_submitting(
            agent_pk=agent.pk,
            allowed_account_ids=[7],
            client_order_id=str(order.client_order_id),
            lease_token="fixture-token",
        )
    order.refresh_from_db()
    assert order.status == "LEASED"
    assert order.version == 1


@pytest.mark.parametrize(
    ("schemas", "expected_status"),
    [
        ([EXECUTION_CONSTRAINT_SCHEMA_V2], 200),
        ([EXECUTION_CONSTRAINT_SCHEMA_V2, EXECUTION_CONSTRAINT_SCHEMA_V2], 400),
        ([True], 400),
        ([f" {EXECUTION_CONSTRAINT_SCHEMA_V2}"], 400),
        ([f"{EXECUTION_CONSTRAINT_SCHEMA_V2}\n"], 400),
        (None, 400),
        (EXECUTION_CONSTRAINT_SCHEMA_V2, 400),
    ],
)
def test_signed_heartbeat_api_validates_schema_declaration(
    schemas: object,
    expected_status: int,
) -> None:
    agent = _bound_agent()
    secret = "fixture-only-capability-secret"
    credential = BrokerAgentCredentialModel.objects.create(
        agent=agent,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        scopes=["agent.heartbeat.write"],
        allowed_account_ids=[7],
        expires_at=timezone.now() + timedelta(hours=1),
    )
    sent_at = timezone.now().isoformat()
    payload = {
        "contract_version": "1.0",
        "observed_at": sent_at,
        "qmt_connected": True,
        "account_ids": [7],
        "agent_version": "0.2.0",
        "execution_constraint_schemas": schemas,
    }
    body = json.dumps(payload).encode()
    nonce = "capability-fixture-nonce"
    request_id = "capability-fixture-request"
    response = Client().post(
        "/api/broker-execution/agent/v1/heartbeat/",
        data=body,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Agent {credential.credential_id}.{secret}",
        HTTP_X_AGENT_ID=agent.agent_id,
        HTTP_X_SENT_AT=sent_at,
        HTTP_X_NONCE=nonce,
        HTTP_X_REQUEST_ID=request_id,
        HTTP_X_SIGNATURE=build_agent_signature(
            secret=secret,
            sent_at=sent_at,
            nonce=nonce,
            request_id=request_id,
            body=body,
        ),
    )
    assert response.status_code == expected_status
    assert response["Content-Type"].startswith("application/json")
    agent.refresh_from_db()
    if expected_status == 200:
        assert agent.health_snapshot["execution_constraint_schemas"] == [
            EXECUTION_CONSTRAINT_SCHEMA_V2
        ]
    else:
        assert agent.health_snapshot == {}


def _mark_agent_online_for_submission(
    agent: BrokerAgentModel, *, now: datetime, observed_at: datetime
) -> None:
    """Create only the source health projection required to reach lease guards."""

    agent.status = BrokerAgentModel.STATUS_ONLINE
    agent.qmt_connected = True
    agent.last_heartbeat_at = now
    agent.health_snapshot = {
        "source_observed_at": observed_at.isoformat(),
        "execution_constraint_schemas": [EXECUTION_CONSTRAINT_SCHEMA_V2],
    }
    agent.save(
        update_fields=[
            "status",
            "qmt_connected",
            "last_heartbeat_at",
            "health_snapshot",
            "updated_at",
        ]
    )


def _ready_order_for_agent(agent: BrokerAgentModel, *, now: datetime) -> LiveOrderModel:
    """Persist a READY fixture without turning it into approval authority."""

    return LiveOrderModel.objects.create(
        user=agent.user,
        account_id=7,
        agent=agent,
        asset_code="600000.SH",
        side="BUY",
        quantity=Decimal("100"),
        limit_price=Decimal("10.00"),
        estimated_amount=Decimal("1000.00"),
        risk_policy_version="risk-v1",
        risk_snapshot={"passed": True},
        status="READY",
        expires_at=now + timedelta(hours=1),
    )


@pytest.mark.parametrize("change", ["disable", "stop", "future_snapshot", "disconnect"])
def test_lease_rechecks_account_state_at_the_write_boundary(
    change: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _bound_agent()
    binding = BrokerAccountBindingModel.objects.get(agent=agent, account_id=7)
    binding.auto_execution_enabled = True
    binding.enforce_trading_session = False
    binding.save()
    now = timezone.now()
    _mark_agent_online_for_submission(agent, now=now, observed_at=now)
    order = _ready_order_for_agent(agent, now=now)
    captured_at = now + timedelta(seconds=30) if change == "future_snapshot" else now
    BrokerAccountSnapshotModel.objects.create(
        user=agent.user, agent=agent, account_id=7, captured_at=captured_at
    )
    # Reach only the subordinate operational guard. This fixture supplies no Evidence grant.
    monkeypatch.setattr(runtime, "broker_order_evidence_integrated", lambda: True)
    original = runtime.transaction.atomic

    def begin():
        monkeypatch.setattr(runtime.transaction, "atomic", original)
        if change == "disable":
            BrokerAccountBindingModel.objects.filter(pk=binding.pk).update(
                auto_execution_enabled=False
            )
        elif change == "stop":
            TradingControlModel.objects.create(
                user=agent.user, account_id=7, kill_switch_active=True
            )
        elif change == "disconnect":
            BrokerAgentModel.objects.filter(pk=agent.pk).update(qmt_connected=False)
        return original()

    monkeypatch.setattr(runtime.transaction, "atomic", begin)
    repository = DjangoBrokerExecutionRepository()
    if change == "disconnect":
        with pytest.raises(BrokerExecutionConflictError, match="not online"):
            repository.lease_agent_orders(
                agent_pk=agent.pk, allowed_account_ids=[7], limit=1, lease_seconds=30
            )
    else:
        result = repository.lease_agent_orders(
            agent_pk=agent.pk, allowed_account_ids=[7], limit=1, lease_seconds=30
        )
        assert result["orders"] == []
    assert not OrderLeaseModel.objects.filter(order=order).exists()
    order.refresh_from_db()
    assert order.status == "READY"


def test_lease_and_submit_recheck_the_execution_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.broker_execution.application import execution_price_guard
    from tests.component.data_center.test_execution_quote_repository import _seed_quote

    agent = _bound_agent()
    binding = BrokerAccountBindingModel.objects.get(agent=agent, account_id=7)
    binding.auto_execution_enabled = True
    binding.enforce_trading_session = False
    binding.save()
    now = timezone.now()
    _mark_agent_online_for_submission(agent, now=now, observed_at=now)
    order = _ready_order_for_agent(agent, now=now)
    BrokerAccountSnapshotModel.objects.create(
        user=agent.user, agent=agent, account_id=7, captured_at=now
    )
    _seed_quote(
        asset_code=order.asset_code,
        snapshot_at=now - timedelta(seconds=10),
        fetched_at=now - timedelta(seconds=9),
        published_at=now - timedelta(seconds=1),
        execution_freshness_seconds=60,
    )
    # Isolate the market guard from the still-closed authorization gate.
    monkeypatch.setattr(runtime, "broker_order_evidence_integrated", lambda: True)
    repository = DjangoBrokerExecutionRepository()
    binding.price_deviation_limit_pct = Decimal("0.001")
    binding.save()
    poll = repository.lease_agent_orders(
        agent_pk=agent.pk, allowed_account_ids=[7], limit=1, lease_seconds=30
    )
    assert poll["orders"] == [] and not OrderLeaseModel.objects.filter(order=order).exists()
    binding.price_deviation_limit_pct = Decimal("0.03")
    binding.save()
    poll = repository.lease_agent_orders(
        agent_pk=agent.pk, allowed_account_ids=[7], limit=1, lease_seconds=30
    )
    assert len(poll["orders"]) == 1
    token = poll["orders"][0]["lease_token"]
    clock = Mock(wraps=timezone)
    clock.now.return_value = now + timedelta(seconds=51)
    monkeypatch.setattr(execution_price_guard, "timezone", clock)
    with pytest.raises(BrokerExecutionConflictError, match="execution_quote_stale"):
        repository.acknowledge_submitting(
            agent_pk=agent.pk,
            allowed_account_ids=[7],
            client_order_id=str(order.client_order_id),
            lease_token=token,
        )
    order.refresh_from_db()
    assert order.status == "LEASED" and order.submitted_at is None


def test_creation_and_approval_use_the_current_execution_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.broker_execution.infrastructure import broker_repository_order_control, repositories
    from tests.component.data_center.test_execution_quote_repository import _seed_quote

    agent = _bound_agent()
    binding = BrokerAccountBindingModel.objects.get(agent=agent, account_id=7)
    binding.auto_execution_enabled = True
    binding.allowed_symbols = ["600000.SH"]
    binding.max_single_order_amount = Decimal("2000")
    binding.daily_order_amount_limit = Decimal("10000")
    binding.save()
    now = timezone.now()
    payload = {
        "account_id": 7,
        "asset_code": "600000.SH",
        "side": "BUY",
        "quantity": "100",
        "limit_price": "10",
        "source_recommendation_ids": ["scenario"],
        "expires_at": now + timedelta(minutes=1),
        "initial_status": "WAITING_APPROVAL",
        "risk_policy_version": "test-policy",
        "risk_snapshot": {"passed": True, "market_snapshot": {"current_price": "10"}},
    }
    # Exercise only the market prerequisite under the real database writer.
    monkeypatch.setattr(repositories, "broker_order_evidence_integrated", lambda: True)
    monkeypatch.setattr(
        broker_repository_order_control, "broker_order_evidence_integrated", lambda: True
    )
    repository = DjangoBrokerExecutionRepository()
    with pytest.raises(BrokerExecutionConflictError, match="execution_quote_"):
        repository.create_live_order(
            user_id=agent.user_id,
            is_admin=False,
            payload=payload,
            idempotency_key="price-check",
            request_digest="create",
        )
    assert not LiveOrderModel.objects.filter(account_id=7).exists()
    _seed_quote(
        asset_code="600000.SH",
        snapshot_at=now - timedelta(seconds=10),
        fetched_at=now - timedelta(seconds=9),
        published_at=now - timedelta(seconds=1),
        execution_freshness_seconds=60,
    )
    repository.create_live_order(
        user_id=agent.user_id,
        is_admin=False,
        payload=payload,
        idempotency_key="price-check",
        request_digest="create",
    )
    order = LiveOrderModel.objects.get(account_id=7)
    binding.price_deviation_limit_pct = Decimal("0.001")
    binding.save()
    with pytest.raises(BrokerExecutionConflictError, match="market-price deviation"):
        repository.mutate_order(
            user_id=agent.user_id,
            is_admin=False,
            client_order_id=str(order.client_order_id),
            action="approve",
            expected_version=order.version,
            reason="test",
            idempotency_key="price-approve",
            request_digest="approve",
        )
    order.refresh_from_db()
    assert order.status == "WAITING_APPROVAL" and order.approved_at is None


@pytest.mark.parametrize("binding_state", ["missing", "inactive", "disabled"])
def test_lease_requires_an_active_auto_enabled_binding_after_test_only_gate_bypass(
    binding_state: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _bound_agent()
    binding = BrokerAccountBindingModel.objects.get(agent=agent, account_id=7)
    binding.auto_execution_enabled = True
    binding.enforce_trading_session = False
    if binding_state == "missing":
        binding.delete()
    elif binding_state == "inactive":
        binding.is_active = False
        binding.save(
            update_fields=[
                "is_active",
                "auto_execution_enabled",
                "enforce_trading_session",
                "updated_at",
            ]
        )
    elif binding_state == "disabled":
        binding.auto_execution_enabled = False
        binding.save(
            update_fields=["auto_execution_enabled", "enforce_trading_session", "updated_at"]
        )
    else:
        raise AssertionError(f"Unexpected binding state: {binding_state}")

    now = timezone.now()
    _mark_agent_online_for_submission(agent, now=now, observed_at=now)
    order = _ready_order_for_agent(agent, now=now)
    BrokerAccountSnapshotModel.objects.create(
        user=agent.user,
        agent=agent,
        account_id=7,
        captured_at=now,
    )
    assert BrokerAccountSnapshotModel.objects.filter(
        agent=agent, account_id=7, captured_at=now
    ).exists()
    assert TradingControlModel.objects.filter(user=agent.user, account_id=7).exists() is False
    snapshot_manager = BrokerAccountSnapshotModel._default_manager
    snapshot_filter = Mock(wraps=snapshot_manager.filter)
    monkeypatch.setattr(snapshot_manager, "filter", snapshot_filter)
    monkeypatch.setattr(runtime, "broker_order_evidence_integrated", lambda: True)

    result = DjangoBrokerExecutionRepository().lease_agent_orders(
        agent_pk=agent.pk,
        allowed_account_ids=[7],
        limit=1,
        lease_seconds=30,
    )

    assert result == {"orders": [], "total_count": 0, "stopped": False}
    snapshot_filter.assert_not_called()
    assert OrderLeaseModel.objects.filter(order=order).exists() is False
    order.refresh_from_db()
    assert order.status == "READY"


def test_lease_rejects_stale_agent_source_before_mutating_ready_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _bound_agent()
    binding = BrokerAccountBindingModel.objects.get(agent=agent, account_id=7)
    binding.auto_execution_enabled = True
    binding.enforce_trading_session = False
    binding.save(update_fields=["auto_execution_enabled", "enforce_trading_session", "updated_at"])
    now = timezone.now()
    _mark_agent_online_for_submission(
        agent,
        now=now,
        observed_at=now - timedelta(seconds=91),
    )
    BrokerAccountSnapshotModel.objects.create(
        user=agent.user,
        agent=agent,
        account_id=7,
        captured_at=now,
    )
    order = _ready_order_for_agent(agent, now=now)
    monkeypatch.setattr(runtime, "broker_order_evidence_integrated", lambda: True)

    with pytest.raises(BrokerExecutionConflictError, match="heartbeat source or receipt is stale"):
        DjangoBrokerExecutionRepository().lease_agent_orders(
            agent_pk=agent.pk,
            allowed_account_ids=[7],
            limit=1,
            lease_seconds=30,
        )

    assert OrderLeaseModel.objects.filter(order=order).exists() is False
    order.refresh_from_db()
    assert order.status == "READY"


def test_lease_does_not_use_a_stale_broker_snapshot_after_test_only_gate_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _bound_agent()
    binding = BrokerAccountBindingModel.objects.get(agent=agent, account_id=7)
    binding.auto_execution_enabled = True
    binding.enforce_trading_session = False
    binding.save(update_fields=["auto_execution_enabled", "enforce_trading_session", "updated_at"])
    now = timezone.now()
    _mark_agent_online_for_submission(agent, now=now, observed_at=now)
    BrokerAccountSnapshotModel.objects.create(
        user=agent.user,
        agent=agent,
        account_id=7,
        captured_at=now - timedelta(seconds=121),
    )
    order = _ready_order_for_agent(agent, now=now)
    monkeypatch.setattr(runtime, "broker_order_evidence_integrated", lambda: True)

    snapshot_manager = BrokerAccountSnapshotModel._default_manager
    snapshot_filter = Mock(wraps=snapshot_manager.filter)
    monkeypatch.setattr(snapshot_manager, "filter", snapshot_filter)
    transaction_atomic = Mock(wraps=runtime.transaction.atomic)
    monkeypatch.setattr(runtime.transaction, "atomic", transaction_atomic)

    result = DjangoBrokerExecutionRepository().lease_agent_orders(
        agent_pk=agent.pk,
        allowed_account_ids=[7],
        limit=1,
        lease_seconds=30,
    )

    assert result == {"orders": [], "total_count": 0, "stopped": False}
    snapshot_filter.assert_called_once()
    assert "captured_at__gte" in snapshot_filter.call_args.kwargs
    transaction_atomic.assert_not_called()
    assert OrderLeaseModel.objects.filter(order=order).exists() is False
    order.refresh_from_db()
    assert order.status == "READY"
