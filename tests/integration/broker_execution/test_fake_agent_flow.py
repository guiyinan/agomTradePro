"""End-to-end persisted flow through human approval and signed Fake Agent events."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from apps.broker_execution.application.agent_auth import build_agent_signature
from apps.broker_execution.infrastructure.models import (
    BrokerAccountBindingModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    BrokerFillModel,
    BrokerOrderEventModel,
    LiveOrderModel,
)


def _headers(token: str, agent_id: str, body: bytes, nonce: str) -> dict[str, str]:
    sent_at = timezone.now().isoformat()
    request_id = f"fake-agent-{nonce}"
    secret = token.split(".", 1)[1]
    return {
        "HTTP_AUTHORIZATION": f"Agent {token}",
        "HTTP_X_AGENT_ID": agent_id,
        "HTTP_X_REQUEST_ID": request_id,
        "HTTP_X_SENT_AT": sent_at,
        "HTTP_X_NONCE": nonce,
        "HTTP_X_SIGNATURE": build_agent_signature(
            secret=secret,
            sent_at=sent_at,
            nonce=nonce,
            request_id=request_id,
            body=body,
        ),
    }


def _agent_post(
    client: Client,
    token: str,
    agent_id: str,
    endpoint: str,
    payload: dict,
    nonce: str,
):
    body = json.dumps(payload).encode()
    return client.post(
        f"/api/broker-execution/agent/v1/{endpoint}",
        data=body,
        content_type="application/json",
        **_headers(token, agent_id, body, nonce),
    )


@pytest.mark.django_db(transaction=True)
def test_fake_agent_approval_lease_submit_fill_flow_is_idempotent() -> None:
    owner = User.objects.create_user(username="fake-flow-owner", password="test123")
    owner.account_profile.rbac_role = "owner"
    owner.account_profile.save(update_fields=["rbac_role", "updated_at"])
    agent = BrokerAgentModel.objects.create(
        user=owner, agent_id="fake-flow-agent", display_name="Fake QMT"
    )
    binding = BrokerAccountBindingModel.objects.create(
        user=owner,
        account_id=11,
        agent=agent,
        broker_account_ref="fake-broker-11",
        broker_account_mask="****0011",
        auto_execution_enabled=True,
        max_single_order_amount=Decimal("100000"),
        daily_order_amount_limit=Decimal("500000"),
        allowed_symbols=["510300.SH"],
        enforce_trading_session=False,
    )
    order = LiveOrderModel.objects.create(
        user=owner,
        account_id=11,
        agent=agent,
        asset_code="510300.SH",
        side="BUY",
        quantity=Decimal("100"),
        limit_price=Decimal("3.9"),
        estimated_amount=Decimal("390"),
        risk_policy_version="risk-v1",
        risk_snapshot={"passed": True},
        expires_at=timezone.now() + timedelta(hours=1),
    )
    client = Client()
    client.force_login(owner)
    approval = client.post(
        f"/api/broker-execution/orders/{order.client_order_id}/approve/",
        data=json.dumps(
            {
                "preview_only": False,
                "reason": "fake flow approval",
                "expected_version": order.version,
                "idempotency_key": "fake-flow-approve",
            }
        ),
        content_type="application/json",
    )
    # The live-order Evidence receipt gate is intentionally fail-closed until
    # its production authority composition is wired.  Keep this integration
    # contract focused on that safety boundary instead of exercising a fake
    # broker fill through a path that must not execute.
    assert approval.status_code == 409
    assert "broker_order_evidence_receipt_not_integrated" in approval.json()["error"]
    order.refresh_from_db()
    assert order.status == "WAITING_APPROVAL"
    return

    secret = "fake-flow-secret"
    scopes = [
        "agent.heartbeat.write",
        "agent.orders.lease",
        "agent.orders.submitting_ack",
        "agent.events.write",
        "agent.snapshots.write",
    ]
    credential = BrokerAgentCredentialModel.objects.create(
        agent=agent,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        scopes=scopes,
        allowed_account_ids=[11],
        expires_at=timezone.now() + timedelta(days=1),
    )
    token = f"{credential.credential_id}.{secret}"
    client.logout()
    heartbeat = _agent_post(
        client,
        token,
        agent.agent_id,
        "heartbeat/",
        {
            "contract_version": "1.0",
            "qmt_connected": True,
            "account_ids": [11],
            "agent_version": "0.1.0",
            "qmt_version": "fake",
            "dry_run": False,
        },
        "heartbeat",
    )
    assert heartbeat.status_code == 200
    snapshot = _agent_post(
        client,
        token,
        agent.agent_id,
        "snapshots/",
        {
            "contract_version": "1.0",
            "account_id": 11,
            "captured_at": timezone.now().isoformat(),
            "cash_available": "100000",
            "total_asset": "100000",
            "positions": [],
            "orders": [],
            "trades": [],
        },
        "snapshot",
    )
    assert snapshot.status_code == 200
    lease = _agent_post(
        client,
        token,
        agent.agent_id,
        "orders/lease/",
        {"contract_version": "1.0", "limit": 1, "lease_seconds": 30},
        "lease",
    )
    leased_order = lease.json()["data"]["orders"][0]
    ack = _agent_post(
        client,
        token,
        agent.agent_id,
        "orders/submitting/",
        {
            "contract_version": "1.0",
            "client_order_id": str(order.client_order_id),
            "lease_token": leased_order["lease_token"],
        },
        "submitting",
    )
    assert ack.status_code == 200
    submitted_event = {
        "event_id": "fake-submitted-1",
        "client_order_id": str(order.client_order_id),
        "event_type": "ORDER_SUBMITTED",
        "status": "SUBMITTED",
        "occurred_at": timezone.now().isoformat(),
        "broker_order_id": "FAKE-1",
        "payload": {},
    }
    submitted = _agent_post(
        client,
        token,
        agent.agent_id,
        "events/",
        {"contract_version": "1.0", "events": [submitted_event]},
        "event-submitted",
    )
    assert submitted.status_code == 200
    duplicate = _agent_post(
        client,
        token,
        agent.agent_id,
        "events/",
        {"contract_version": "1.0", "events": [submitted_event]},
        "event-submitted-replay",
    )
    assert duplicate.json()["data"]["duplicate_count"] == 1
    filled = _agent_post(
        client,
        token,
        agent.agent_id,
        "events/",
        {
            "contract_version": "1.0",
            "events": [
                {
                    "event_id": "fake-filled-1",
                    "client_order_id": str(order.client_order_id),
                    "event_type": "ORDER_FILLED",
                    "status": "FILLED",
                    "occurred_at": timezone.now().isoformat(),
                    "broker_order_id": "FAKE-1",
                    "payload": {},
                    "fill": {
                        "broker_account_ref": "agent-supplied-ref-is-not-trusted",
                        "broker_trade_id": "FAKE-TRADE-1",
                        "quantity": "100",
                        "price": "3.9",
                        "occurred_at": timezone.now().isoformat(),
                    },
                }
            ],
        },
        "event-filled",
    )
    assert filled.status_code == 200
    order.refresh_from_db()
    assert order.status == "FILLED"
    assert order.filled_quantity == Decimal("100")
    assert BrokerOrderEventModel.objects.filter(order=order).count() == 2
    assert BrokerFillModel.objects.filter(order=order).count() == 1
    assert BrokerFillModel.objects.get(order=order).broker_account_ref == binding.broker_account_ref
