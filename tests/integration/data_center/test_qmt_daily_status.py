"""Signed daily-status retention without price fabrication or execution authority."""

import copy
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.data_center.infrastructure.models import PriceBarModel, QuoteSnapshotModel
from apps.data_center.infrastructure.qmt_bridge_models import (
    QmtBridgeBatchModel,
    QmtBridgeBindingModel,
)
from apps.data_center.qmt_bridge_composition import read_qmt_daily_status
from tests.integration.data_center import test_qmt_bridge as bridge_contract
from tests.integration.data_center.test_qmt_bridge import approve, payload, signed

setup_bridge = bridge_contract.setup_bridge
isolated_bridge_cache = bridge_contract.isolated_bridge_cache
pytestmark = pytest.mark.django_db


def daily_payload(flag=1):
    day = timezone.localdate() - timedelta(days=2)
    return {
        "batch_id": str(uuid.uuid4()),
        "kind": "daily_status",
        "schema_version": "qmt-native-daily-status.v1",
        "collected_at": (timezone.now() - timedelta(seconds=1)).isoformat(),
        "request_start": day.isoformat(),
        "request_end": day.isoformat(),
        "samples": [{"asset_code": "510300.SH", "bar_date": day.isoformat(), "suspend_flag": flag}],
    }


def test_daily_status_plan_advertises_supported_independent_kind(setup_bridge):
    client, _, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    response = signed(client, pair, "plan", {})
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.data["data"]["kinds"] == ["quote", "bar", "daily_status"]
    assert response.data["data"]["trading_enabled"] is False


@pytest.mark.parametrize("kind", ["quote", "daily_status"])
def test_authenticated_upload_rechecks_owner_before_writing(setup_bridge, monkeypatch, kind):
    from apps.data_center.application.qmt_bridge import QmtBridgeService

    client, owner, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    original = QmtBridgeService.execute

    def deactivate_before_ingest(service, binding_id, batch):
        owner.is_active = False
        owner.save(update_fields=["is_active"])
        return original(service, binding_id, batch)

    monkeypatch.setattr(QmtBridgeService, "execute", deactivate_before_ingest)
    batch = daily_payload() if kind == "daily_status" else payload()
    denied = signed(client, pair, "batches", batch)
    assert denied.status_code == 403
    assert denied["Content-Type"].startswith("application/json")
    assert not QmtBridgeBatchModel.objects.exists()
    assert not QuoteSnapshotModel.objects.exists()


def test_daily_status_signed_upload_retains_status_only_and_exact_retry(setup_bridge):
    client, _, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    batch = daily_payload()
    first = signed(client, pair, "batches", batch)
    assert first.status_code == 200, first.data
    assert first["Content-Type"].startswith("application/json")
    assert first.data["data"]["stored"] == 1
    saved = QmtBridgeBatchModel.objects.get()
    original = (saved.digest, saved.payload, saved.created_at)
    assert saved.payload["samples"] == batch["samples"]
    assert "observed_at" not in saved.payload["samples"][0]
    assert not PriceBarModel.objects.exists()
    assert not QuoteSnapshotModel.objects.exists()
    assert signed(client, pair, "batches", batch).data == first.data
    saved.refresh_from_db()
    assert (saved.digest, saved.payload, saved.created_at) == original
    conflict = copy.deepcopy(batch)
    conflict["samples"][0]["suspend_flag"] = 0
    denied = signed(client, pair, "batches", conflict)
    assert denied.status_code == 409
    assert denied["Content-Type"].startswith("application/json")
    assert QmtBridgeBatchModel.objects.count() == 1


@pytest.mark.parametrize("flag", [True, False, 2, -2, 1.5, "1", "normal"])
def test_daily_status_http_rejects_noncanonical_flags(setup_bridge, flag):
    client, _, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    denied = signed(client, pair, "batches", daily_payload(flag))
    assert denied.status_code == 400
    assert denied["Content-Type"].startswith("application/json")
    assert not QmtBridgeBatchModel.objects.exists()


@pytest.mark.parametrize("change", ["missing", "unknown_clock", "duplicate", "outside_range"])
def test_daily_status_http_rejects_missing_mixed_or_ambiguous_samples(setup_bridge, change):
    client, _, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    batch = daily_payload()
    if change == "missing":
        del batch["samples"][0]["suspend_flag"]
    elif change == "unknown_clock":
        batch["samples"][0]["source_observed_at"] = batch["collected_at"]
    elif change == "duplicate":
        batch["samples"].append(dict(batch["samples"][0]))
    else:
        batch["request_start"] = (timezone.localdate() - timedelta(days=1)).isoformat()
        batch["request_end"] = batch["request_start"]
    denied = signed(client, pair, "batches", batch)
    assert denied.status_code == 400
    assert denied["Content-Type"].startswith("application/json")
    assert not QmtBridgeBatchModel.objects.exists()


@pytest.mark.parametrize("flag", [-1, 0, 1, None])
def test_daily_status_wire_retains_each_native_state_and_unknown(setup_bridge, flag):
    client, _, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    response = signed(client, pair, "batches", daily_payload(flag))
    assert response.status_code == 200, response.data
    saved = QmtBridgeBatchModel.objects.get()
    assert saved.payload["samples"][0]["suspend_flag"] == flag
    assert "price" not in json.dumps(saved.payload)


def read_status(owner, pair, batch, *, as_of=None, asset_code="510300.SH"):
    return read_qmt_daily_status(
        owner_id=owner.pk,
        binding_id=pair["binding_id"],
        asset_code=asset_code,
        bar_date=date.fromisoformat(batch["samples"][0]["bar_date"]),
        as_of=as_of or timezone.now(),
    )


def test_daily_status_read_binds_first_server_known_time_and_exact_batch(setup_bridge):
    client, owner, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    batch = daily_payload()
    assert signed(client, pair, "batches", batch).status_code == 200
    saved = QmtBridgeBatchModel.objects.get()
    result = read_status(owner, pair, batch)
    assert result.state.value == "suspended"
    assert result.local_known_at == datetime.fromisoformat(batch["collected_at"])
    assert result.recorded_at == saved.created_at
    assert result.evidence[0].batch_id == batch["batch_id"]
    assert result.evidence[0].content_hash == saved.digest
    assert result.source_observed_at is None and result.source_available_at is None
    assert result.must_not_use_for_decision and result.must_not_execute
    assert result.freshness == "unknown" and result.reliability == "unverified"
    hidden = read_status(owner, pair, batch, as_of=saved.created_at - timedelta(microseconds=1))
    assert hidden.state.value == "unknown" and hidden.evidence == ()
    assert signed(client, pair, "batches", batch).status_code == 200
    assert read_status(owner, pair, batch).recorded_at == result.recorded_at


@pytest.mark.parametrize(
    "scope", ["owner", "asset", "paused", "revoked", "provider", "inactive_owner"]
)
def test_daily_status_read_rejects_unavailable_current_scope(setup_bridge, scope):
    from django.contrib.auth import get_user_model

    client, owner, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    batch = daily_payload()
    assert signed(client, pair, "batches", batch).status_code == 200
    asset = "510300.SH"
    if scope == "owner":
        owner = get_user_model().objects.create_user(username="other-status-owner")
    elif scope == "asset":
        asset = "600000.SH"
    elif scope == "paused":
        QmtBridgeBindingModel.objects.filter(pk=pair["binding_id"]).update(enabled=False)
    elif scope == "revoked":
        QmtBridgeBindingModel.objects.filter(pk=pair["binding_id"]).update(revoked=True)
    elif scope == "provider":
        provider.is_active = False
        provider.save(update_fields=["is_active"])
    else:
        owner.is_active = False
        owner.save(update_fields=["is_active"])
    result = read_status(owner, pair, batch, asset_code=asset)
    assert result.blocked_reason == "qmt_daily_status_scope_unavailable"
    assert result.state.value == "unknown" and result.evidence == ()


def test_daily_status_read_rechecks_scope_after_materializing_records(setup_bridge, monkeypatch):
    from apps.data_center.infrastructure import qmt_daily_status_repository as repository

    client, owner, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    batch = daily_payload()
    assert signed(client, pair, "batches", batch).status_code == 200
    original = repository._read_scope
    reads = 0

    def revoke_on_second_read(*args):
        nonlocal reads
        reads += 1
        if reads == 2:
            QmtBridgeBindingModel.objects.filter(pk=pair["binding_id"]).update(revoked=True)
        return original(*args)

    monkeypatch.setattr(repository, "_read_scope", revoke_on_second_read)
    result = read_status(owner, pair, batch)
    assert reads == 2
    assert result.blocked_reason == "qmt_daily_status_scope_changed"
    assert result.evidence == () and result.state.value == "unknown"


@pytest.mark.parametrize(
    "damage",
    [
        "digest",
        "non_ascii_digest",
        "flag",
        "kind",
        "schema",
        "missing",
        "receipt",
        "identity",
        "clock",
    ],
)
def test_daily_status_corrupt_retained_evidence_never_becomes_normal(setup_bridge, damage):
    client, owner, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    batch = daily_payload(0)
    assert signed(client, pair, "batches", batch).status_code == 200
    saved = QmtBridgeBatchModel.objects.get()
    if damage == "digest":
        saved.digest = "0" * 64
    elif damage == "non_ascii_digest":
        saved.digest = "坏" * 64
    elif damage == "flag":
        saved.payload["samples"][0]["suspend_flag"] = False
    elif damage == "kind":
        saved.payload["kind"] = "bar"
    elif damage == "schema":
        saved.payload["schema_version"] = "unknown"
    elif damage == "missing":
        del saved.payload["samples"][0]["suspend_flag"]
    elif damage == "receipt":
        saved.receipt["succeeded"] = True
    elif damage == "identity":
        saved.payload["batch_id"] = str(uuid.uuid4())
    else:
        saved.payload["collected_at"] = (saved.created_at + timedelta(seconds=1)).isoformat()
    if damage not in ("digest", "non_ascii_digest", "receipt"):
        saved.digest = hashlib.sha256(
            json.dumps(
                saved.payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode()
        ).hexdigest()
    saved.save(update_fields=["digest", "payload", "receipt"])
    result = read_status(owner, pair, batch)
    assert result.blocked_reason == "qmt_daily_status_invalid_retained_evidence"
    assert result.state.value == "unknown" and result.evidence == ()
    assert signed(client, pair, "batches", batch).status_code == 409


def test_daily_status_conflict_and_late_arrival_do_not_clear_restrictions(setup_bridge):
    client, owner, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    newest = daily_payload(1)
    assert signed(client, pair, "batches", newest).status_code == 200
    late = daily_payload(0)
    late["collected_at"] = (
        datetime.fromisoformat(newest["collected_at"]) - timedelta(minutes=1)
    ).isoformat()
    assert signed(client, pair, "batches", late).status_code == 200
    result = read_status(owner, pair, newest)
    assert result.blocked_reason == "qmt_daily_status_conflicting_observations"
    assert result.state.value == "unknown"
    assert [item.batch_id for item in result.evidence] == [late["batch_id"], newest["batch_id"]]


def test_daily_status_latest_unknown_does_not_reuse_older_normal(setup_bridge):
    client, owner, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    older = daily_payload(0)
    older["collected_at"] = (timezone.now() - timedelta(minutes=2)).isoformat()
    latest = daily_payload(None)
    for batch in (latest, older):
        assert signed(client, pair, "batches", batch).status_code == 200
    result = read_status(owner, pair, latest)
    assert result.blocked_reason == "qmt_daily_status_missing_suspend_flag"
    assert result.state.value == "unknown"


def test_daily_status_signing_nonce_and_asset_scope_remain_required(setup_bridge):
    client, _, admin, provider, _, pair = setup_bridge
    batch = daily_payload()
    assert signed(client, pair, "batches", batch).status_code == 403
    approve(client, admin, provider, pair)
    batch["samples"][0]["asset_code"] = "600000.SH"
    assert signed(client, pair, "batches", batch).status_code == 403
    assert not QmtBridgeBatchModel.objects.exists()
    batch["samples"][0]["asset_code"] = "510300.SH"
    bad_pair = dict(pair, token="incorrect-token")
    assert signed(client, bad_pair, "batches", batch).status_code == 403
    nonce = uuid.uuid4().hex
    assert signed(client, pair, "batches", batch, nonce).status_code == 200
    assert signed(client, pair, "batches", batch, nonce).status_code == 403
    assert QmtBridgeBatchModel.objects.count() == 1


@override_settings(TIME_ZONE="UTC")
def test_daily_status_extension_preserves_legacy_quote_payload_and_digest(setup_bridge):
    client, _, admin, provider, _, pair = setup_bridge
    approve(client, admin, provider, pair)
    legacy = {
        "batch_id": "00000000-0000-0000-0000-000000000011",
        "kind": "quote",
        "collected_at": "2020-01-03T00:00:00+00:00",
        "samples": [
            {
                "asset_code": "510300.SH",
                "observed_at": "2020-01-02T00:00:00+00:00",
                "price": "3.5000",
                "volume": "2.00",
                "amount": "700.00",
            }
        ],
    }
    first = signed(client, pair, "batches", legacy)
    assert first.status_code == 200, first.data
    stored = QmtBridgeBatchModel.objects.get()
    assert stored.digest == "51ad89d4a88eb511fbff5ab1a1f69476ec18636f5b6331a03456eb1b6f0b2ecc"
    assert stored.payload == {
        "batch_id": legacy["batch_id"],
        "kind": "quote",
        "collected_at": "2020-01-03 00:00:00+00:00",
        "samples": [
            {
                "asset_code": "510300.SH",
                "observed_at": "2020-01-02 00:00:00+00:00",
                "price": "3.5000",
                "open": None,
                "high": None,
                "low": None,
                "prev_close": None,
                "volume": "2.00",
                "amount": "700.00",
                "bar_date": None,
            }
        ],
    }
    assert signed(client, pair, "batches", legacy).data == first.data
    assert QmtBridgeBatchModel.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_actual_native_status_outbox_signed_http_and_reader_survive_lost_ack(
    live_server,
    tmp_path,
):
    from types import SimpleNamespace

    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    from apps.data_center.infrastructure.models import AssetMasterModel, ProviderConfigModel
    from qmt_agent.api_client import AgentApiError
    from qmt_agent.bridge_client import BridgeClient
    from qmt_agent.bridge_worker import BridgeWorker, XtDataSource
    from tests.integration.data_center.test_qmt_bridge import BASE

    owner = get_user_model().objects.create_user(username="http-status-owner", is_staff=True)
    AssetMasterModel.objects.create(code="510300.SH", name="ETF", asset_type="etf", exchange="SSE")
    provider = ProviderConfigModel.objects.create(
        name="http-status-source", source_type="qmt", is_active=True
    )
    user_client = APIClient()
    user_client.force_authenticate(owner)
    response = user_client.post(
        BASE + "bindings/",
        {"agent_id": "status-agent", "assets": ["510300.SH"]},
        format="json",
        HTTP_HOST=live_server.url.split("//", 1)[1],
    )
    assert response.status_code == 200, response.data
    pair = BridgeClient(live_server.url).post(
        "pair",
        {"pairing_code": response.data["data"]["pairing_code"], "agent_id": "status-agent"},
        pairing=True,
    )
    approve(user_client, owner, provider, pair)
    machine = BridgeClient(live_server.url, pair["binding_id"], pair["token"])
    day = timezone.localdate() - timedelta(days=2)
    calls = []

    def native_read(fields, assets, **kwargs):
        calls.append((fields, assets, kwargs))
        return {
            "510300.SH": SimpleNamespace(
                iterrows=lambda: iter(
                    [
                        (day.strftime("%Y%m%d"), {"suspendFlag": 1, "open": 0, "close": 0}),
                    ]
                )
            )
        }

    # Only the native SDK boundary is substituted; adapter, worker and HTTP are real.
    source = object.__new__(XtDataSource)
    source.sdk = SimpleNamespace(
        download_history_data=lambda *args, **kwargs: None, get_market_data_ex=native_read
    )
    source.subscriptions = set()

    class LoseFirstAck:
        def __init__(self):
            self.lose = True
            self.batches = []

        def post(self, operation, payload):
            result = machine.post(operation, payload)
            if operation == "batches":
                self.batches.append(copy.deepcopy(payload))
                if self.lose:
                    self.lose = False
                    raise AgentApiError("response lost after durable status commit")
            return result

    transport = LoseFirstAck()
    worker = BridgeWorker(tmp_path, transport, source)
    try:
        with pytest.raises(AgentApiError, match="response lost"):
            worker.run_once(start=day.isoformat(), end=day.isoformat())
        assert worker.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1
    finally:
        worker.close()
    saved = QmtBridgeBatchModel.objects.get(binding_id=pair["binding_id"])
    original = (saved.digest, saved.created_at)
    restarted = BridgeWorker(tmp_path, transport, source)
    try:
        assert restarted.run_once()["stored"] == 1
        assert restarted.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    finally:
        restarted.close()
    assert len(calls) == 1 and "suspendFlag" in calls[0][0]
    assert calls[0][2]["fill_data"] is False
    assert transport.batches[0] == transport.batches[1]
    saved.refresh_from_db()
    assert (saved.digest, saved.created_at) == original
    assert QmtBridgeBatchModel.objects.filter(binding_id=pair["binding_id"]).count() == 1
    result = read_status(owner, pair, transport.batches[0])
    assert result.state.value == "suspended"
    assert result.recorded_at == saved.created_at
    assert result.source_observed_at is None and result.must_not_use_for_decision
    assert result.must_not_execute and result.reliability == "unverified"
    assert not PriceBarModel.objects.exists() and not QuoteSnapshotModel.objects.exists()
