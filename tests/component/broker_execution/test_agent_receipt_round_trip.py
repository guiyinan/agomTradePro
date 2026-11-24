"""A signed fill upload survives a lost HTTP reply and a local Agent restart."""

import hashlib
import io
import json
import secrets
import urllib.request
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.utils import timezone

from apps.broker_execution.infrastructure.models import (
    BrokerAgentCredentialModel,
    BrokerAgentNonceModel,
)
from qmt_agent.api_client import AgentApiClient, AgentApiError
from qmt_agent.config import AgentConfig
from qmt_agent.executor import QmtAgentExecutor
from qmt_agent.fake_adapter import FakeQmtAdapter
from qmt_agent.state_store import AgentStateStore
from tests.component.broker_execution.test_api_and_permissions import _binding, _order


@pytest.mark.django_db(transaction=True)
def test_signed_fill_replay_after_lost_reply_updates_restarted_agent_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = get_user_model().objects.create_user(username="receipt-round-trip")
    agent, binding = _binding(owner)
    order = _order(owner, agent)
    order.status = "SUBMITTED"
    order.broker_order_id = "order-fixture"
    order.save(update_fields=["status", "broker_order_id"])
    client_id = str(order.client_order_id)
    initial_version = order.version
    token_secret = secrets.token_urlsafe(24)
    credential = BrokerAgentCredentialModel.objects.create(
        agent=agent,
        secret_hash=hashlib.sha256(token_secret.encode()).hexdigest(),
        scopes=["agent.events.write", "agent.snapshots.write"],
        allowed_account_ids=[order.account_id],
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    token = f"{credential.credential_id}.{token_secret}"
    config = AgentConfig(
        agent_id=agent.agent_id,
        server_url="https://testserver",
        qmt_userdata_path=tmp_path,
        broker_account_id=binding.broker_account_ref,
        broker_account_type="STOCK",
        system_account_id=order.account_id,
        dry_run=False,
    )
    source_at = (timezone.now() - timedelta(seconds=1)).isoformat()
    clocks = {"broker_source_at": source_at, "clock_source": "broker"}
    event = {
        "event_id": "qmt-trade:round-trip",
        "client_order_id": client_id,
        "event_type": "QMT_TRADE",
        "status": "",
        "broker_order_id": order.broker_order_id,
        "occurred_at": source_at,
        "payload": clocks,
        "fill": {
            "broker_account_ref": binding.broker_account_ref,
            "broker_trade_id": "trade-fixture",
            "quantity": "20",
            "price": "3.90",
            "occurred_at": source_at,
            "payload": clocks,
        },
    }
    client = Client()
    event_nonces = []
    event_ids = []
    counts = []
    submit = Mock(side_effect=AssertionError("A receipt replay must never submit a broker order"))

    def django_transport(request: urllib.request.Request, **_options: object) -> io.BytesIO:
        path = urlsplit(request.full_url).path
        assert path in {
            "/api/broker-execution/agent/v1/events/",
            "/api/broker-execution/agent/v1/snapshots/",
        }
        headers = {k: v for k, v in request.header_items() if k.lower() != "content-type"}
        response = client.post(
            path, data=request.data, content_type="application/json", headers=headers, secure=True
        )
        assert response.status_code == 200, response.content
        if path.endswith("/events/"):
            assert not connection.in_atomic_block
            event_nonces.append(request.get_header("X-nonce"))
            event_ids.append(json.loads(request.data)["events"][0]["event_id"])
            result = response.json()["data"]
            counts.append((result["accepted_count"], result["duplicate_count"]))
            if len(counts) == 1:
                raise TimeoutError("reply lost after server commit")
        return io.BytesIO(response.content)

    monkeypatch.setattr(urllib.request, "urlopen", django_transport)

    def executor(state: AgentStateStore) -> QmtAgentExecutor:
        # Only the broker feed and network transport are local doubles. Signing, routing,
        # nonce storage, drop/replay handling and both persistence layers run normally.
        broker = FakeQmtAdapter()
        monkeypatch.setattr(broker, "poll_events", lambda: [deepcopy(event)])
        monkeypatch.setattr(broker, "submit_order", submit)
        return QmtAgentExecutor(
            config=config, api=AgentApiClient(config, token), broker=broker, state=state
        )

    state_path = tmp_path / "agent.sqlite3"
    state = AgentStateStore(state_path)
    try:
        state.mark_submitting(client_id, {"client_order_id": client_id})
        state.mark_result(client_id, "SUBMITTED", order.broker_order_id)
        with pytest.raises(AgentApiError, match="reply lost after server commit"):
            executor(state).sync_broker_events()
        assert order.fills.count() == order.broker_events.count() == 1
        assert state.connection.execute(
            "SELECT count(*) FROM submission_confirmations"
        ).fetchone() == (0,)
    finally:
        state.close()

    restarted = AgentStateStore(state_path)
    try:
        resumed = executor(restarted)
        resumed.initialize()
        resumed.sync_broker_events()
        order.refresh_from_db()
        assert order.version == initial_version + 1
        assert order.filled_quantity == Decimal("20") and order.average_fill_price == Decimal(
            "3.90"
        )
        assert order.broker_events.get().event_id == event["event_id"]
        assert order.fills.get().broker_trade_id == "trade-fixture"
        assert event_ids == [event["event_id"], event["event_id"]]
        assert counts == [(1, 0), (0, 1)]
        assert len(set(event_nonces)) == 2
        nonce_hashes = {hashlib.sha256(nonce.encode()).hexdigest() for nonce in event_nonces}
        assert (
            BrokerAgentNonceModel.objects.filter(
                credential=credential, nonce_hash__in=nonce_hashes
            ).count()
            == 2
        )
        confirmed = restarted.connection.execute(
            "SELECT version, status, broker_order_id FROM submission_confirmations WHERE client_order_id = ?",
            (client_id,),
        ).fetchone()
        assert confirmed == (order.version, order.status, order.broker_order_id)
        submit.assert_not_called()
    finally:
        restarted.close()
