"""Owner/server pairing and durable market ingestion contract regression."""

import hashlib
import hmac
import json
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.data_center.infrastructure.models import AssetMasterModel, ProviderConfigModel, QuoteSnapshotModel
from apps.data_center.infrastructure.qmt_bridge_models import QmtBridgeBindingModel
from apps.data_center.infrastructure.qmt_bridge_provider import QmtBridgeProvider

BASE = "/api/data-center/qmt-bridge/"
pytestmark = pytest.mark.django_db


@pytest.fixture
def setup_bridge():
    owner = get_user_model().objects.create_user(username="bridge-owner", password="test-password")
    admin = get_user_model().objects.create_user(username="bridge-admin", is_staff=True)
    AssetMasterModel.objects.create(code="510300.SH", name="ETF", asset_type="etf", exchange="SSE")
    provider = ProviderConfigModel.objects.create(name="bridge-test", source_type="qmt", is_active=True)
    client = APIClient()
    client.force_authenticate(owner)
    response = client.post(BASE+"bindings/", {"agent_id": "local-qmt", "assets": ["510300.SH"]}, format="json")
    assert response.status_code == 200, response.data
    binding = response.data["data"]
    client.force_authenticate(None)
    response = client.post(BASE+"pair/", {"pairing_code": binding["pairing_code"], "agent_id": "local-qmt"}, format="json")
    assert response.status_code == 200, response.data
    pair = response.data["data"]
    return client, owner, admin, provider, binding, pair


def signed(client, pair, operation, payload, nonce=None):
    path = BASE+f"agent/v1/{operation}/"
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sent = timezone.now().isoformat()
    nonce = nonce or uuid.uuid4().hex
    canonical = f"POST\n{path}\n{pair['binding_id']}\n{sent}\n{nonce}\n{hashlib.sha256(body).hexdigest()}"
    signature = hmac.new(pair["token"].encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return client.post(path, body, content_type="application/json", HTTP_X_BRIDGE_ID=pair["binding_id"],
        HTTP_AUTHORIZATION=f"QmtBridge {pair['token']}", HTTP_X_SENT_AT=sent, HTTP_X_NONCE=nonce, HTTP_X_SIGNATURE=signature)


def approve(client, admin, provider, pair):
    client.force_authenticate(admin)
    response = client.post(BASE+f"bindings/{pair['binding_id']}/",
        {"action": "approve", "provider_id": provider.pk, "quote_multiplier": "100", "bar_multiplier": "100"}, format="json")
    assert response.status_code == 200, response.data
    client.force_authenticate(None)


def payload(age=1):
    return {"batch_id": str(uuid.uuid4()), "kind": "quote", "collected_at": timezone.now().isoformat(),
            "samples": [{"asset_code": "510300.SH", "observed_at": (timezone.now()-timedelta(seconds=age)).isoformat(),
                         "price": "3.5000", "volume": "2.00", "amount": "700.00"}]}


def test_owner_server_pairing_is_single_use_and_scoped(setup_bridge):
    client, owner, admin, provider, binding, pair = setup_bridge
    assert pair["scope"] == "market_data" and not pair["trading_enabled"]
    response = client.post(BASE+"pair/", {"pairing_code": binding["pairing_code"], "agent_id": "local-qmt"}, format="json")
    assert response.status_code == 403
    client.force_authenticate(owner)
    assert client.post(BASE+f"bindings/{pair['binding_id']}/", {"action": "approve", "provider_id": provider.pk,
        "quote_multiplier": "100", "bar_multiplier": "100"}, format="json").status_code == 403
    other = get_user_model().objects.create_user(username="other")
    client.force_authenticate(other)
    assert client.get(BASE+"bindings/").data["data"] == []
    assert client.post(BASE+f"bindings/{pair['binding_id']}/", {"action": "pause"}, format="json").status_code == 404


def test_batch_retry_preserves_observation_and_volume_contract(setup_bridge):
    client, owner, admin, provider, binding, pair = setup_bridge
    approve(client, admin, provider, pair)
    batch = payload()
    first = signed(client, pair, "batches", batch)
    assert first.status_code == 200, first.data
    assert first["Content-Type"].startswith("application/json")
    assert first.data["data"]["stored"] == 1
    assert signed(client, pair, "batches", batch).data == first.data
    assert QuoteSnapshotModel.objects.count() == 1
    quote = QuoteSnapshotModel.objects.get()
    assert quote.snapshot_at.isoformat() == batch["samples"][0]["observed_at"]
    assert quote.volume == 200
    batch["samples"][0]["price"] = "4.0000"
    assert signed(client, pair, "batches", batch).status_code == 409
    assert quote.extra["must_not_use_for_decision"] is True
    fresh = QmtBridgeProvider(pair["binding_id"], provider.pk).quotes(["510300.SH"])
    assert len(fresh) == 1 and fresh[0].snapshot_at == quote.snapshot_at
    assert fresh[0].extra["must_not_use_for_decision"] is True


def test_stale_quote_does_not_become_current_or_stop_fallback(setup_bridge):
    client, owner, admin, provider, binding, pair = setup_bridge
    approve(client, admin, provider, pair)
    assert signed(client, pair, "batches", payload(600)).status_code == 200
    assert QmtBridgeProvider(pair["binding_id"], provider.pk).quotes(["510300.SH"]) == []
    client.force_authenticate(owner)
    state = client.get(BASE+"bindings/").data["data"][0]
    assert state["freshness"] == "stale_or_missing"
    assert state["must_not_use_for_decision"] is True


def test_pause_revoke_replay_and_asset_scope_fail_closed(setup_bridge):
    client, owner, admin, provider, binding, pair = setup_bridge
    assert signed(client, pair, "batches", payload()).status_code == 403
    approve(client, admin, provider, pair)
    nonce = uuid.uuid4().hex
    assert signed(client, pair, "plan", {}, nonce).status_code == 200
    assert signed(client, pair, "plan", {}, nonce).status_code == 403
    batch = payload()
    batch["samples"][0]["asset_code"] = "600000.SH"
    assert signed(client, pair, "batches", batch).status_code == 403
    client.force_authenticate(owner)
    assert client.post(BASE+f"bindings/{pair['binding_id']}/", {"action": "revoke"}, format="json").status_code == 200
    client.force_authenticate(None)
    assert signed(client, pair, "plan", {}).status_code == 403


@pytest.mark.parametrize("bad_time", ["2039-01-01T00:00:00+00:00", "2026-09-01T00:00:00"])
def test_future_or_naive_source_time_is_rejected(setup_bridge, bad_time):
    client, owner, admin, provider, binding, pair = setup_bridge
    approve(client, admin, provider, pair)
    batch = payload()
    batch["samples"][0]["observed_at"] = bad_time
    assert signed(client, pair, "batches", batch).status_code == 400
    assert not QuoteSnapshotModel.objects.exists()


def test_daily_history_and_partial_batch_rollback(setup_bridge):
    from apps.data_center.infrastructure.models import PriceBarModel
    client, owner, admin, provider, binding, pair = setup_bridge
    approve(client, admin, provider, pair)
    day = timezone.now().date()-timedelta(days=2)
    batch = payload()
    batch["kind"] = "bar"
    batch["samples"] = [{"asset_code": "510300.SH", "bar_date": day.isoformat(),
        "observed_at": day.isoformat()+"T00:00:00+00:00", "price": "3.5", "open": "3.4",
        "low": "3.3", "high": "3.6", "volume": "2", "amount": "700"}]
    assert signed(client, pair, "batches", batch).status_code == 200
    assert PriceBarModel.objects.get().volume == 200
    assert len(QmtBridgeProvider(pair["binding_id"], provider.pk).bars("510300.SH", day, day)) == 1
    batch = payload()
    bad = dict(batch["samples"][0], asset_code="600000.SH")
    batch["samples"].append(bad)
    assert signed(client, pair, "batches", batch).status_code == 403
    assert QuoteSnapshotModel.objects.count() == 0


def test_expired_credentials_and_inactive_owner_are_rejected(setup_bridge):
    client, owner, admin, provider, binding, pair = setup_bridge
    owner.is_active = False
    owner.save()
    assert signed(client, pair, "plan", {}).status_code == 403
    owner.is_active = True
    owner.save()
    QmtBridgeBindingModel.objects.filter(pk=pair["binding_id"]).update(token_expires_at=timezone.now()-timedelta(seconds=1))
    assert signed(client, pair, "plan", {}).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_actual_http_pairing_and_worker_upload_roundtrip(live_server, tmp_path):
    from qmt_agent.bridge_client import BridgeClient
    from qmt_agent.bridge_worker import BridgeWorker

    owner = get_user_model().objects.create_user(username="http-bridge-owner", is_staff=True)
    AssetMasterModel.objects.create(code="510300.SH", name="ETF", asset_type="etf", exchange="SSE")
    provider = ProviderConfigModel.objects.create(name="http-bridge-provider", source_type="qmt", is_active=True)
    user_client = APIClient()
    user_client.force_authenticate(owner)
    response = user_client.post(BASE+"bindings/", {"agent_id": "http-agent", "assets": "510300.SH"},
                                format="json", HTTP_HOST=live_server.url.split("//", 1)[1])
    assert response.status_code == 200
    binding = response.data["data"]
    client = BridgeClient(live_server.url)
    pair = client.post("pair", {"pairing_code": binding["pairing_code"], "agent_id": "http-agent"}, pairing=True)
    machine = BridgeClient(live_server.url, pair["binding_id"], pair["token"])
    assert machine.post("plan", {})["enabled"] is False
    approve(user_client, owner, provider, pair)

    class Source:
        def quotes(self, assets):
            return payload()["samples"]

    worker = BridgeWorker(tmp_path, machine, Source())
    try:
        assert worker.run_once()["stored"] == 1
        assert QuoteSnapshotModel.objects.get().source.startswith("qmt-bridge:")
        assert worker.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    finally:
        worker.close()
