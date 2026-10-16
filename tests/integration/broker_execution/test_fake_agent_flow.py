"""Approval boundary contract while live-order Evidence receipts are unavailable."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from apps.broker_execution.application.evidence_gate import BROKER_ORDER_EVIDENCE_BLOCK_MESSAGE
from apps.broker_execution.infrastructure.models import (
    BrokerAccountBindingModel,
    BrokerAgentModel,
    LiveOrderModel,
)


@pytest.mark.django_db(transaction=True)
def test_order_approval_fails_closed_until_evidence_receipts_are_integrated() -> None:
    owner = User.objects.create_user(username="fake-flow-owner", password="test123")
    owner.account_profile.rbac_role = "owner"
    owner.account_profile.save(update_fields=["rbac_role", "updated_at"])
    agent = BrokerAgentModel.objects.create(
        user=owner, agent_id="fake-flow-agent", display_name="Fake QMT"
    )
    BrokerAccountBindingModel.objects.create(
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
    assert BROKER_ORDER_EVIDENCE_BLOCK_MESSAGE in approval.json()["error"]
    order.refresh_from_db()
    assert order.status == "WAITING_APPROVAL"
