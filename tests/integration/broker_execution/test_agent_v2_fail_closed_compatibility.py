"""Signed in-process API compatibility for the fail-closed Agent polling loop."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from apps.broker_execution.application.evidence_gate import BROKER_ORDER_EVIDENCE_BLOCK_MESSAGE
from apps.broker_execution.domain.entities import LiveOrderStatus
from apps.broker_execution.infrastructure.models import (
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    LiveOrderModel,
    OrderLeaseModel,
)
from qmt_agent import __version__
from qmt_agent.api_client import AgentApiClient, AgentApiError
from qmt_agent.config import AgentConfig
from qmt_agent.executor import QmtAgentExecutor
from qmt_agent.fake_adapter import FakeQmtAdapter
from qmt_agent.qmt_adapter import BrokerSubmitResult
from qmt_agent.state_store import AgentStateStore


class _DjangoTransportResponse:
    """Minimal context-managed response shape consumed by AgentApiClient."""

    def __init__(self, content: bytes) -> None:
        self.content = content

    def __enter__(self) -> _DjangoTransportResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self.content


class _CountingFakeQmtAdapter(FakeQmtAdapter):
    """Track submission calls without changing the production fake's facts."""

    def __init__(self) -> None:
        super().__init__("success")
        self.submit_calls = 0

    def submit_order(self, order: dict[str, Any]) -> BrokerSubmitResult:
        self.submit_calls += 1
        return super().submit_order(order)


@pytest.mark.django_db(transaction=True)
def test_current_agent_runtime_persists_v2_heartbeat_and_fails_closed_on_orders(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    owner = User.objects.create_user(username="agent-v2-owner", password="test123")
    owner.account_profile.rbac_role = "owner"
    owner.account_profile.save(update_fields=["rbac_role", "updated_at"])
    agent = BrokerAgentModel.objects.create(
        user=owner,
        agent_id="agent-v2-compat",
        display_name="Fake QMT v2 contract",
    )
    binding = BrokerAccountBindingModel.objects.create(
        user=owner,
        account_id=11,
        agent=agent,
        broker_account_ref="fake-v2-account-11",
        broker_account_mask="****0011",
        auto_execution_enabled=True,
        max_single_order_amount="100000",
        daily_order_amount_limit="500000",
        allowed_symbols=["510300.SH"],
        enforce_trading_session=False,
    )
    # A READY row only exercises the server's closed lease boundary. This direct
    # fixture is not an approval, risk receipt, V2 envelope, or submission grant.
    candidate = LiveOrderModel.objects.create(
        user=owner,
        account_id=binding.account_id,
        agent=agent,
        asset_code="510300.SH",
        side="BUY",
        quantity="100",
        limit_price="3.90",
        estimated_amount="390.00",
        risk_policy_version="TEST_FIXTURE_ONLY",
        risk_snapshot={"fixture_only": True},
        status=LiveOrderStatus.READY.value,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    secret = "synthetic-agent-v2-secret"
    credential = BrokerAgentCredentialModel.objects.create(
        agent=agent,
        secret_hash=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
        scopes=[
            "agent.heartbeat.write",
            "agent.orders.lease",
            "agent.orders.submitting_ack",
            "agent.events.write",
            "agent.snapshots.write",
            "agent.commands.lease",
        ],
        allowed_account_ids=[binding.account_id],
        expires_at=timezone.now() + timedelta(days=1),
    )
    token = f"{credential.credential_id}.{secret}"
    django_client = Client()
    transport_records: list[dict[str, object]] = []

    def django_urlopen(
        request: Request, timeout: float, context: object
    ) -> _DjangoTransportResponse:
        del timeout, context
        request_headers = {name.lower(): value for name, value in request.header_items()}
        body = request.data or b""
        path = urlsplit(request.full_url).path
        response = django_client.post(
            path,
            data=body,
            content_type=request_headers["content-type"],
            HTTP_AUTHORIZATION=request_headers["authorization"],
            HTTP_X_AGENT_ID=request_headers["x-agent-id"],
            HTTP_X_REQUEST_ID=request_headers["x-request-id"],
            HTTP_X_SENT_AT=request_headers["x-sent-at"],
            HTTP_X_NONCE=request_headers["x-nonce"],
            HTTP_X_SIGNATURE=request_headers["x-signature"],
        )
        response_body = json.loads(response.content.decode("utf-8"))
        transport_records.append(
            {
                "path": path,
                "status": response.status_code,
                "request_content_type": request_headers["content-type"],
                "response_content_type": response.headers.get("Content-Type", ""),
                "body": response_body,
            }
        )
        if response.status_code >= 400:
            raise HTTPError(
                request.full_url,
                response.status_code,
                response.reason_phrase,
                response.headers,
                io.BytesIO(response.content),
            )
        return _DjangoTransportResponse(response.content)

    monkeypatch.setattr("urllib.request.urlopen", django_urlopen)
    config = AgentConfig(
        agent_id=agent.agent_id,
        server_url="http://127.0.0.1",
        qmt_userdata_path=tmp_path / "qmt-userdata",
        broker_account_id=binding.broker_account_ref,
        broker_account_type="STOCK",
        system_account_id=binding.account_id,
        lease_seconds=30,
        dry_run=False,
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
        kill_switch_file=tmp_path / "STOP",
        verify_tls=False,
        enforce_trading_session=False,
    )
    config.validate()
    api = AgentApiClient(config, token)
    broker = _CountingFakeQmtAdapter()
    state = AgentStateStore(config.state_dir / "agent-state.sqlite3")
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)
    try:
        executor.initialize()
        executor.run_once()

        agent.refresh_from_db()
        assert agent.agent_version == __version__
        assert agent.status == BrokerAgentModel.STATUS_ONLINE
        assert agent.qmt_connected is True
        assert agent.last_heartbeat_at is not None
        assert agent.health_snapshot["execution_constraint_schemas"] == [
            "a-share-execution-constraints.v2"
        ]
        observed_at = agent.health_snapshot["source_observed_at"]
        assert isinstance(observed_at, str)
        assert datetime.fromisoformat(observed_at).tzinfo is not None

        assert (
            BrokerAccountSnapshotModel.objects.filter(
                agent=agent,
                account_id=binding.account_id,
            ).count()
            >= 1
        )
        lease_record = next(
            item for item in transport_records if item["path"].endswith("/orders/lease/")
        )
        assert lease_record["status"] == 200
        assert lease_record["request_content_type"] == "application/json"
        assert str(lease_record["response_content_type"]).startswith("application/json")
        lease_data = lease_record["body"]["data"]
        assert lease_data["orders"] == []
        assert lease_data["evidence_gate_active"] is True
        assert lease_data["must_not_execute"] is True
        second_lease = api.post(
            "orders/lease/",
            {"contract_version": "1.0", "limit": 10, "lease_seconds": config.lease_seconds},
        )
        assert second_lease["orders"] == []
        assert second_lease["evidence_gate_active"] is True
        assert candidate.status == LiveOrderStatus.READY.value
        assert not OrderLeaseModel.objects.filter(order=candidate).exists()

        for attempt in range(2):
            with pytest.raises(AgentApiError, match="409") as rejected:
                api.post(
                    "orders/submitting/",
                    {
                        "contract_version": "1.0",
                        "client_order_id": str(candidate.client_order_id),
                        "lease_token": "synthetic-token-never-issued-by-blocked-lease",
                    },
                )
            assert BROKER_ORDER_EVIDENCE_BLOCK_MESSAGE in str(rejected.value)
            ack_record = [
                item for item in transport_records if item["path"].endswith("/orders/submitting/")
            ][attempt]
            assert ack_record["status"] == 409
            assert ack_record["request_content_type"] == "application/json"
            assert str(ack_record["response_content_type"]).startswith("application/json")
            assert BROKER_ORDER_EVIDENCE_BLOCK_MESSAGE in ack_record["body"]["error"]

        called_paths = [str(item["path"]) for item in transport_records]
        assert called_paths.count("/api/broker-execution/agent/v1/heartbeat/") == 1
        assert called_paths.count("/api/broker-execution/agent/v1/orders/lease/") == 2
        assert called_paths.count("/api/broker-execution/agent/v1/snapshots/") >= 2
        assert called_paths.count("/api/broker-execution/agent/v1/commands/lease/") == 1
        assert all(item["request_content_type"] == "application/json" for item in transport_records)
        assert all(
            str(item["response_content_type"]).startswith("application/json")
            for item in transport_records
        )
        assert all(
            item["status"] == 200
            for item in transport_records
            if not str(item["path"]).endswith("/orders/submitting/")
        )
        assert [
            item["status"]
            for item in transport_records
            if str(item["path"]).endswith("/orders/submitting/")
        ] == [409, 409]
        assert broker.submit_calls == 0
        assert broker.orders == {}
        order = LiveOrderModel.objects.get(pk=candidate.pk)
        assert order.status == LiveOrderStatus.READY.value
        assert not OrderLeaseModel.objects.filter(order=order).exists()
    finally:
        state.close()
