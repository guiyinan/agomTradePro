"""Persisted capability declarations gate new leases and submitting ACKs."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal

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
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    LiveOrderModel,
    OrderLeaseModel,
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
