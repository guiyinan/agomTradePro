"""Causal account sampling over a real HMAC heartbeat and snapshot HTTP transport."""

import hashlib
import json
import secrets
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from apps.broker_execution.benchmark_day_source_composition import read_benchmark_broker_balances
from apps.broker_execution.infrastructure.models import (
    BrokerAccountSnapshotModel,
    BrokerAgentCredentialModel,
)
from apps.broker_execution.infrastructure.order_risk_reservations import read_order_reservations
from apps.broker_execution.snapshot_challenge import confirmed_sampling_lower_bound
from qmt_agent.executor import QmtAgentExecutor
from tests.component.broker_execution.test_api_and_permissions import _signed_headers
from tests.component.broker_execution.test_signed_order_reservations import _order, _setup


@pytest.mark.django_db
def test_only_server_challenge_can_release_fill_even_with_ahead_agent_clock(tmp_path):
    owner, agent, binding = _setup()
    secret = secrets.token_urlsafe(32)
    credential = BrokerAgentCredentialModel.objects.create(
        agent=agent,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        scopes=["agent.heartbeat.write", "agent.snapshots.write"],
        allowed_account_ids=[27],
        expires_at=timezone.now() + timedelta(hours=1),
    )
    config = SimpleNamespace(system_account_id=27, dry_run=True, kill_switch_file=tmp_path / "STOP")

    class Transport:
        def post(self, route, payload):
            body = json.dumps(payload).encode()
            response = Client().post(
                "/api/broker-execution/agent/v1/" + route,
                body,
                content_type="application/json",
                **_signed_headers(
                    f"{credential.credential_id}.{secret}", agent.agent_id, body, uuid4().hex
                ),
            )
            assert response.status_code == 200, response.content[:300]
            return response.json()["data"]

    broker = Mock()
    broker.health.return_value = {"qmt_connected": True}
    broker.account_snapshot.side_effect = lambda: {
        "cash_available": "100",
        "total_asset": "100",
        "positions": [],
        "payload": {
            "valuation_close": {
                "source": "xtquant.stock",
                "broker_account_ref": binding.broker_account_ref,
                "currency": "CNY",
                "assets_complete": True,
                "positions_complete": True,
                "cash_frozen": "0",
                "position_market_value": "0",
                "sampling_started_at": (timezone.now() + timedelta(hours=1)).isoformat(),
            }
        },
    }
    executor = QmtAgentExecutor(config=config, api=Transport(), broker=broker, state=Mock())
    first = executor.heartbeat()["snapshot_challenge"]
    client_id = uuid4()
    done = _order(owner, agent, status="FILLED", filled_quantity=6)

    def balances():
        executor.sync_snapshot()
        snap = BrokerAccountSnapshotModel.objects.latest("pk")
        return read_benchmark_broker_balances(
            snapshot_id=snap.pk, owner_user_id=owner.pk, account_id=27, using="default"
        )

    def held(bound):
        return read_order_reservations(
            user_id=owner.pk,
            account_id=27,
            client_order_id=client_id,
            asset_code="X",
            sampling_challenge_at=bound,
            using="default",
        ).buy_amount

    report = balances()
    assert report.sampling_challenge_at < done.updated_at < report.captured_at
    assert held(report.sampling_challenge_at) == 60
    # A fresh timestamp or a second capture on the old heartbeat cannot release anything.
    assert balances().sampling_challenge_at is None
    second = executor.heartbeat()["snapshot_challenge"]
    newest = balances()
    assert (
        second != first
        and newest.sampling_challenge_at > done.updated_at
        and held(newest.sampling_challenge_at) == 0
    )
    values = {
        "agent_pk": agent.pk,
        "account_id": 27,
        "credential_id": credential.credential_id,
        "received_at": newest.received_at,
    }
    for changed in (
        {"credential_id": uuid4()},
        {"account_id": 28},
        {"agent_pk": agent.pk + 1},
        {"received_at": newest.received_at + timedelta(minutes=2)},
    ):
        assert confirmed_sampling_lower_bound(token=second, **(values | changed)) is None
    assert confirmed_sampling_lower_bound(token=second + "x", **values) is None
