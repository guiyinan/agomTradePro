"""Exercise the real staff HTTP mapping-to-source-capture workflow."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.test import override_settings
from rest_framework.test import APIClient

from apps.config_center.infrastructure.models import (
    RuntimeConfigProfileModel,
    RuntimeConfigSnapshotModel,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.fact_and_operational_models import (
    InstrumentReferenceMappingModel,
    InstrumentReferenceSnapshotModel,
    RawAuditModel,
    RawPayloadModel,
    SyncBatchModel,
    SyncCheckpointModel,
    SyncRunModel,
)
from apps.data_center.infrastructure.models import AssetMasterModel
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.data_center.infrastructure.sync_item_attempt_models import SyncItemAttemptModel
from shared.config.secrets import AppSecrets, DataSourceSecrets
from shared.config.tushare import (
    TUSHARE_REQUEST_MODE_REST_PATH,
    TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.unit.data_center.test_tushare_provider_response_capture import _Response, _Session

_MAPPINGS_URL = "/api/data-center/tui/instrument-reference/mappings/"
_CAPTURES_URL = "/api/data-center/tui/instrument-reference/captures/"
_SNAPSHOTS_URL = "/api/data-center/tui/instrument-reference/snapshots/"
_PROXY_URL = "https://market.example.test/pro"
_FIELDS = (
    "ts_code",
    "name",
    "exchange",
    "market",
    "list_status",
    "list_date",
    "delist_date",
)
_PROVIDER_KEY = "fixture-only-not-a-credential"


def _stock_basic_body(list_status: str) -> bytes:
    """Return fixed source rows for one scope, without invented upstream times."""

    items: list[list[str]] = []
    if list_status == "L":
        items = [
            [
                "600000.SH",
                "Fixture bank",
                "SSE",
                "fixture-market",
                "L",
                "20200102",
                "",
            ],
            [
                "600001.SH",
                "Fixture energy",
                "SSE",
                "fixture-market",
                "L",
                "20200103",
                "",
            ],
        ]
    elif list_status != "D":
        raise AssertionError(f"unexpected fixture list_status: {list_status}")
    return json.dumps(
        {
            "code": 0,
            "msg": "fixture response",
            "data": {
                "fields": list(_FIELDS),
                "items": items,
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class _StockBasicSession(_Session):
    """Replace only the outbound provider session while retaining client logic."""

    def __init__(self) -> None:
        """Start a transport double that records method and target without networking."""

        super().__init__(_Response(_stock_basic_body("L")))
        self.requests: list[tuple[str, str, dict[str, object]]] = []
        self.responses: list[_Response] = []

    def _respond(
        self,
        method: str,
        url: str,
        kwargs: dict[str, object],
    ) -> _Response:
        """Return exact fixture bytes and retain the request for wire assertions."""

        self.calls.append(kwargs)
        assert method == "POST"
        request_body = kwargs.get("json")
        assert isinstance(request_body, dict)
        params = request_body.get("params")
        assert isinstance(params, dict)
        list_status = params.get("list_status")
        assert isinstance(list_status, str)
        self.requests.append((method, url, kwargs))
        response = _Response(_stock_basic_body(list_status))
        self.responses.append(response)
        self.response = response
        return response

    def post(self, url: str, **kwargs: object) -> _Response:
        """Capture one relay POST without opening a socket."""

        return self._respond("POST", url, kwargs)

    def get(self, url: str, **kwargs: object) -> _Response:
        """Capture an unexpected REST-path GET without opening a socket."""

        return self._respond("GET", url, kwargs)


def _mapping_payload() -> dict[str, object]:
    """Provide explicit test mapping material for one Shanghai exchange."""

    return {
        "mapping_id": "operator-capture-fixture",
        "mapping_version": "fixture-v1",
        "source_crosswalk_id": "operator-capture-fixture.suffix",
        "source_crosswalk_version": "fixture-v1",
        "exchange_suffix_pairs": [["SSE", "SH"]],
        "exchange_rule_market_pairs": [["SSE", "SSE"]],
        "exchange_source_market_board_pairs": [["SSE", "fixture-market", "fixture-board"]],
    }


def _login_staff(client: APIClient) -> AbstractBaseUser:
    """Create and session-login one database-backed staff user."""

    user_model = get_user_model()
    user = user_model.objects.create_user(
        username=f"instrument-reference-{uuid4().hex[:12]}",
        password="test-only-password",
        is_staff=True,
    )
    client.force_login(user)
    return user


def _install_transport_and_global_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> _StockBasicSession:
    """Pin a different global mode and stub only the outbound HTTP session."""

    fallback = AppSecrets(
        data_sources=DataSourceSecrets(
            tushare_token="",
            fred_api_key="",
            tushare_http_url=None,
            tushare_request_mode=TUSHARE_REQUEST_MODE_REST_PATH,
        )
    )
    monkeypatch.setattr(tushare_client, "get_secrets", lambda: fallback)
    baseline = tushare_client.resolve_tushare_runtime_settings(
        token=_PROVIDER_KEY,
        http_url=_PROXY_URL,
    )
    assert baseline.request_mode == TUSHARE_REQUEST_MODE_REST_PATH

    session = _StockBasicSession()
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    return session


def _register_mapping(client: APIClient) -> dict[str, object]:
    """Save one real mapping through the HTTP view and return its receipt."""

    response = client.post(_MAPPINGS_URL, _mapping_payload(), format="json")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    body = cast(dict[str, object], response.json())
    return cast(dict[str, object], body["mapping"])


def _assert_exact_occurrence_projection(
    occurrence: dict[str, object],
    *,
    capture_id: UUID,
    batch_id: UUID,
    provider_contract: dict[str, object],
    crosswalk: dict[str, object],
    expected_status: str,
    expected_row_count: int,
) -> None:
    """Bind one public occurrence projection to its exact persisted evidence."""

    assert occurrence["fetch_round_id"] == str(capture_id)
    assert occurrence["provider_contract_id"] == provider_contract["contract_id"]
    assert occurrence["provider_contract_version"] == provider_contract["contract_version"]
    assert occurrence["provider_contract_content_hash"] == provider_contract["content_hash"]
    assert occurrence["crosswalk_id"] == crosswalk["crosswalk_id"]
    assert occurrence["crosswalk_version"] == crosswalk["crosswalk_version"]
    assert occurrence["crosswalk_content_hash"] == crosswalk["content_hash"]
    assert occurrence["exchange"] == "SSE"
    assert occurrence["list_status"] == expected_status
    assert occurrence["row_count"] == expected_row_count
    assert occurrence["source_observed_at"] is None
    assert occurrence["source_available_at"] is None
    assert occurrence["upstream_time_unknown"] is True
    assert occurrence["must_not_use_for_decision"] is True
    assert occurrence["must_not_execute"] is True
    assert occurrence["blocked_reason"] == "INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY"

    expected_body = _stock_basic_body(expected_status)
    expected_body_sha256 = hashlib.sha256(expected_body).hexdigest()
    assert occurrence["response_body_sha256"] == expected_body_sha256
    raw_payload = RawPayloadModel._default_manager.get(pk=occurrence["raw_payload_id"])
    assert raw_payload.redacted is True
    assert raw_payload.request_params["fields"] == ",".join(_FIELDS)
    assert raw_payload.request_params["params"] == {
        "exchange": "SSE",
        "list_status": expected_status,
    }
    raw_payload_payload = cast(dict[str, object], raw_payload.payload)
    assert occurrence["raw_payload_hash"] == raw_payload.payload_hash
    assert raw_payload_payload["response_body_sha256"] == expected_body_sha256
    response_completed_at = occurrence["response_completed_at"]
    assert isinstance(response_completed_at, str)
    assert response_completed_at == raw_payload_payload["response_completed_at"]
    completed_at = datetime.fromisoformat(response_completed_at)
    assert completed_at.tzinfo is not None
    assert completed_at.utcoffset() == timedelta(0)
    assert completed_at == raw_payload.fetched_at

    audit_reference = cast(dict[str, object], occurrence["raw_audit_reference"])
    raw_audit = RawAuditModel._default_manager.get(pk=audit_reference["raw_audit_id"])
    assert audit_reference == {
        "raw_audit_id": str(raw_audit.pk),
        "version": "1",
        "content_hash": raw_audit.content_hash,
        "run_id": str(capture_id),
        "ingested_run_id": str(batch_id),
    }
    assert occurrence["raw_audit_id"] == audit_reference["raw_audit_id"]
    assert occurrence["raw_audit_version"] == audit_reference["version"]
    assert occurrence["raw_audit_content_hash"] == audit_reference["content_hash"]
    assert occurrence["raw_audit_run_id"] == audit_reference["run_id"]
    assert occurrence["raw_audit_ingested_run_id"] == audit_reference["ingested_run_id"]
    assert raw_audit.run_id == capture_id
    assert raw_audit.ingested_run_id == batch_id
    assert raw_audit.response_payload_hash == expected_body_sha256
    assert raw_audit.row_count == expected_row_count
    assert raw_audit.fetched_at == completed_at


@pytest.mark.django_db(transaction=True)
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="operator-capture-test-encryption-key")
def test_staff_session_registers_captures_and_reads_exact_source_snapshot(
    api_client: APIClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove the real mapping, selected provider, capture, and exact-read path."""

    staff_user = _login_staff(api_client)
    session = _install_transport_and_global_mode(monkeypatch)
    provider = ProviderConfigRepository().save(
        ProviderConfig(
            id=None,
            name="instrument-reference-operator-fixture",
            source_type="tushare",
            is_active=True,
            priority=1,
            api_key=_PROVIDER_KEY,
            api_secret="",
            http_url=_PROXY_URL,
            api_endpoint="",
            extra_config={"tushare_request_mode": TUSHARE_REQUEST_MODE_UNIFIED_RELAY},
            description="Test-only provider configuration.",
        )
    )
    assert type(provider.id) is int
    assert provider.extra_config["tushare_request_mode"] == TUSHARE_REQUEST_MODE_UNIFIED_RELAY

    selector_counts_before = (
        RuntimeConfigProfileModel._default_manager.count(),
        RuntimeConfigSnapshotModel._default_manager.count(),
        AssetMasterModel._default_manager.count(),
    )
    mapping_response = api_client.post(_MAPPINGS_URL, _mapping_payload(), format="json")
    assert mapping_response.status_code == 200
    assert mapping_response["Content-Type"].startswith("application/json")
    mapping_body = cast(dict[str, object], mapping_response.json())
    mapping_receipt = cast(dict[str, object], mapping_body["mapping"])
    mapping_record_id = str(mapping_receipt["mapping_record_id"])
    mapping_content = cast(dict[str, object], mapping_receipt["content"])
    assert mapping_content["mapping_id"] == "operator-capture-fixture"
    assert mapping_content["mapping_version"] == "fixture-v1"
    assert mapping_content["source_crosswalk"]["exchange_suffix_pairs"] == [["SSE", "SH"]]
    assert mapping_receipt["owner_or_provider_approval_asserted"] is False
    assert mapping_receipt["operator_supplied_only"] is True
    mapping_recorded_at = datetime.fromisoformat(str(mapping_receipt["recorded_at"]))
    assert mapping_recorded_at.tzinfo is not None
    assert mapping_recorded_at.utcoffset() == timedelta(0)

    mapping_read = api_client.get(f"{_MAPPINGS_URL}{mapping_record_id}/")
    mapping_replay = api_client.post(_MAPPINGS_URL, _mapping_payload(), format="json")
    assert mapping_read.status_code == mapping_replay.status_code == 200
    assert mapping_read.json()["mapping"] == mapping_receipt
    assert mapping_replay.json()["mapping"] == mapping_receipt

    changed_mapping = _mapping_payload()
    changed_mapping["exchange_suffix_pairs"] = [["SSE", "SHX"]]
    mapping_conflict = api_client.post(_MAPPINGS_URL, changed_mapping, format="json")
    assert mapping_conflict.status_code == 409
    assert mapping_conflict.json()["code"] == "INSTRUMENT_REFERENCE_MAPPING_VERSION_IMMUTABLE"
    assert (
        InstrumentReferenceMappingModel._default_manager.filter(
            mapping_id="operator-capture-fixture",
            mapping_version="fixture-v1",
        ).count()
        == 1
    )

    capture_id = uuid4()
    capture_request = {
        "capture_id": str(capture_id),
        "provider_configuration_id": provider.id,
        "mapping_record_id": mapping_record_id,
        "exchange_scope": ["SSE"],
        "list_status_scope": ["L", "D"],
        "mode": "normal",
    }
    counts_before_capture = (
        RawAuditModel._default_manager.count(),
        RawPayloadModel._default_manager.count(),
        InstrumentReferenceSnapshotModel._default_manager.count(),
        SyncRunModel._default_manager.count(),
        SyncBatchModel._default_manager.count(),
        SyncCheckpointModel._default_manager.count(),
    )
    captured = api_client.post(_CAPTURES_URL, capture_request, format="json")
    assert captured.status_code == 200, (
        captured.json().get("status"),
        captured.json().get("reason_code"),
    )
    assert captured["Content-Type"].startswith("application/json")
    captured_body = cast(dict[str, object], captured.json())
    assert captured_body["status"] == "completed"
    assert captured_body["success"] is True
    assert captured_body["outcome"] == "success"
    assert captured_body["decision_ready"] is False
    assert captured_body["execution_authorized"] is False
    assert captured_body["capture_id"] == str(capture_id)
    snapshot_receipt = cast(dict[str, object], captured_body["snapshot"])
    snapshot_id = str(snapshot_receipt["snapshot_id"])
    assert snapshot_receipt["mapping_record_id"] == mapping_record_id
    assert snapshot_receipt["mapping_content_hash"] == mapping_receipt["content_hash"]
    assert snapshot_receipt["mapping_record_digest"] == mapping_receipt["record_digest"]
    assert snapshot_receipt["run_id"] == str(capture_id)
    assert snapshot_receipt["fetch_round_count"] == 1
    assert snapshot_receipt["record_count"] == 2
    assert snapshot_receipt["occurrence_count"] == 2
    assert snapshot_receipt["empty_occurrence_count"] == 1
    assert snapshot_receipt["source_observed_at"] is None
    assert snapshot_receipt["source_available_at"] is None
    assert snapshot_receipt["must_not_use_for_decision"] is True
    assert snapshot_receipt["must_not_execute"] is True
    assert (
        snapshot_receipt["blocked_reason"] == "INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY"
    )

    assert [method for method, _url, _kwargs in session.requests] == ["POST", "POST"]
    assert [url for _method, url, _kwargs in session.requests] == [_PROXY_URL, _PROXY_URL]
    assert len(session.responses) == 2
    for expected_status, (_method, _url, request_kwargs), response in zip(
        ("L", "D"), session.requests, session.responses, strict=True
    ):
        request_body = request_kwargs.get("json")
        assert isinstance(request_body, dict)
        assert request_body.get("api_name") == "stock_basic"
        assert request_body.get("fields") == ",".join(_FIELDS)
        request_params = request_body.get("params")
        assert request_params == {"exchange": "SSE", "list_status": expected_status}
        expected_body = _stock_basic_body(expected_status)
        assert response.body == expected_body
    assert session.responses and all(response.closed for response in session.responses)

    request_chunks = list(
        SyncCheckpointModel._default_manager.filter(
            run_id=capture_id,
            cursor_name__startswith="ircap.v1.request.",
        )
        .order_by("cursor_name")
        .values_list("cursor_value", flat=True)
    )
    assert request_chunks
    request_descriptor_text = "".join(request_chunks)
    request_descriptor = cast(dict[str, object], json.loads(request_descriptor_text))
    assert request_descriptor["capture_id"] == str(capture_id)
    assert request_descriptor["provider_configuration_id"] == provider.id
    assert request_descriptor["provider_route_id"] == "tushare.stock_basic"
    assert request_descriptor["provider_route_revision"] == "v1"
    assert request_descriptor["source_only"] is True
    assert request_descriptor["repository_alias"] == "default"
    provider_contract = cast(dict[str, object], request_descriptor["provider_contract"])
    assert provider_contract["list_status_scope"] == ["L", "D"]
    assert request_descriptor["scopes"] == [
        {"exchange": "SSE", "list_status": "L"},
        {"exchange": "SSE", "list_status": "D"},
    ]
    assert request_descriptor["actor_provenance"] == f"tui-admin:{staff_user.pk}"
    assert request_descriptor["mapping"] == {
        "mapping_record_id": mapping_record_id,
        "mapping_content_hash": mapping_receipt["content_hash"],
        "mapping_record_digest": mapping_receipt["record_digest"],
    }
    source_crosswalk = cast(dict[str, object], mapping_content["source_crosswalk"])
    exchange_scope = cast(list[str], provider_contract["exchange_scope"])
    list_status_scope = cast(list[str], provider_contract["list_status_scope"])
    assert snapshot_receipt["provider_contract"] == {
        "contract_id": provider_contract["contract_id"],
        "contract_version": provider_contract["contract_version"],
        "provider_name": provider_contract["provider_name"],
        "dataset_key": provider_contract["dataset_key"],
        "api_name": provider_contract["api_name"],
        "fields": provider_contract["fields"],
        "exchange_scope_count": len(exchange_scope),
        "list_status_scope_count": len(list_status_scope),
        "content_hash": provider_contract["content_hash"],
    }
    assert snapshot_receipt["crosswalk"] == {
        "crosswalk_id": source_crosswalk["crosswalk_id"],
        "crosswalk_version": source_crosswalk["crosswalk_version"],
        "content_hash": source_crosswalk["content_hash"],
    }
    assert snapshot_receipt["last_response_completed_at"]
    assert _PROVIDER_KEY not in request_descriptor_text

    snapshot_read = api_client.get(f"{_SNAPSHOTS_URL}{snapshot_id}/?limit=1&offset=0")
    assert snapshot_read.status_code == 200
    assert snapshot_read["Content-Type"].startswith("application/json")
    snapshot_read_body = cast(dict[str, object], snapshot_read.json())
    assert snapshot_read_body["snapshot"] == snapshot_receipt
    rows = cast(list[dict[str, object]], snapshot_read_body["rows"])
    occurrences = cast(list[dict[str, object]], snapshot_read_body["occurrences"])
    assert snapshot_read_body["total"] == 2
    assert snapshot_read_body["offset"] == 0
    assert snapshot_read_body["limit"] == 1
    assert snapshot_read_body["next_offset"] == 1
    assert snapshot_read_body["occurrence_offset"] == 0
    assert snapshot_read_body["occurrence_limit"] == 1
    assert snapshot_read_body["occurrence_total"] == 2
    assert snapshot_read_body["occurrence_next_offset"] == 1
    assert len(rows) == 1
    assert len(occurrences) == 1
    assert occurrences[0]["raw_payload_id"]
    capture_batch = SyncBatchModel._default_manager.get(run_id=capture_id)
    _assert_exact_occurrence_projection(
        occurrences[0],
        capture_id=capture_id,
        batch_id=capture_batch.batch_id,
        provider_contract=provider_contract,
        crosswalk=source_crosswalk,
        expected_status="L",
        expected_row_count=2,
    )
    source_row = rows[0]
    assert source_row["ts_code"] == "600000.SH"
    assert source_row["name"] == "Fixture bank"
    assert source_row["source_exchange"] == "SSE"
    assert source_row["source_market"] == "fixture-market"
    assert source_row["source_list_status"] == "L"
    assert source_row["list_date_raw"] == "20200102"
    assert source_row["delist_date_raw"] == ""
    assert source_row["exchange_suffix"] == "SH"
    assert source_row["occurrence_id"] == occurrences[0]["occurrence_id"]
    assert source_row["raw_payload_id"] == occurrences[0]["raw_payload_id"]
    assert source_row["raw_audit_id"] == occurrences[0]["raw_audit_id"]

    raw_payload = RawPayloadModel._default_manager.get(pk=source_row["raw_payload_id"])
    raw_audit = RawAuditModel._default_manager.get(pk=source_row["raw_audit_id"])
    assert raw_payload.redacted is True
    assert raw_payload.request_params["params"] == {"exchange": "SSE", "list_status": "L"}
    assert raw_audit.redacted is True
    assert raw_audit.run_id == capture_id
    assert raw_audit.status == "ok"
    assert raw_audit.fetched_at == raw_payload.fetched_at
    assert raw_audit.row_count == 2
    second_page = api_client.get(f"{_SNAPSHOTS_URL}{snapshot_id}/?limit=1&offset=1")
    assert second_page.status_code == 200
    second_page_body = cast(dict[str, object], second_page.json())
    second_rows = cast(list[dict[str, object]], second_page_body["rows"])
    assert second_page_body["total"] == 2
    assert second_page_body["offset"] == 1
    assert second_page_body["next_offset"] is None
    assert second_page_body["occurrence_offset"] == 1
    assert second_page_body["occurrence_limit"] == 1
    second_occurrences = cast(list[dict[str, object]], second_page_body["occurrences"])
    assert second_page_body["occurrence_total"] == 2
    assert second_page_body["occurrence_next_offset"] is None
    assert len(second_rows) == 1
    assert len(second_occurrences) == 1
    raw_payload_ids = {
        str(occurrences[0]["raw_payload_id"]),
        str(second_occurrences[0]["raw_payload_id"]),
    }
    assert len(raw_payload_ids) == 2
    assert second_rows[0]["ts_code"] == "600001.SH"
    assert second_rows[0]["occurrence_id"] == source_row["occurrence_id"]
    assert second_rows[0]["raw_payload_id"] == source_row["raw_payload_id"]
    assert second_rows[0]["raw_audit_id"] == source_row["raw_audit_id"]
    assert second_rows[0]["raw_payload_id"] != second_occurrences[0]["raw_payload_id"]
    assert second_rows[0]["raw_audit_id"] != second_occurrences[0]["raw_audit_id"]
    _assert_exact_occurrence_projection(
        second_occurrences[0],
        capture_id=capture_id,
        batch_id=capture_batch.batch_id,
        provider_contract=provider_contract,
        crosswalk=source_crosswalk,
        expected_status="D",
        expected_row_count=0,
    )
    summary_last_response_completed_at = datetime.fromisoformat(
        str(snapshot_receipt["last_response_completed_at"])
    )
    assert summary_last_response_completed_at.tzinfo is not None
    assert summary_last_response_completed_at.utcoffset() == timedelta(0)
    occurrence_completed_at = (
        datetime.fromisoformat(str(occurrences[0]["response_completed_at"])),
        datetime.fromisoformat(str(second_occurrences[0]["response_completed_at"])),
    )
    assert summary_last_response_completed_at == max(occurrence_completed_at)
    end_page = api_client.get(f"{_SNAPSHOTS_URL}{snapshot_id}/?limit=1&offset=2")
    assert end_page.status_code == 200
    end_page_body = cast(dict[str, object], end_page.json())
    assert end_page_body["rows"] == []
    assert end_page_body["occurrences"] == []
    assert end_page_body["total"] == 2
    assert end_page_body["next_offset"] is None
    assert end_page_body["occurrence_offset"] == 2
    assert end_page_body["occurrence_limit"] == 1
    assert end_page_body["occurrence_total"] == 2
    assert end_page_body["occurrence_next_offset"] is None
    snapshot_recorded_at = datetime.fromisoformat(str(snapshot_receipt["recorded_at"]))
    assert snapshot_recorded_at.tzinfo is not None
    assert snapshot_recorded_at.utcoffset() == timedelta(0)
    assert snapshot_recorded_at >= raw_payload.fetched_at.astimezone(UTC)
    assert snapshot_recorded_at >= mapping_recorded_at

    capture_counts = (
        RawAuditModel._default_manager.count(),
        RawPayloadModel._default_manager.count(),
        InstrumentReferenceSnapshotModel._default_manager.count(),
        SyncRunModel._default_manager.count(),
        SyncBatchModel._default_manager.count(),
        SyncCheckpointModel._default_manager.count(),
    )
    assert capture_counts[0] == counts_before_capture[0] + 2
    assert capture_counts[1] == counts_before_capture[1] + 2
    assert capture_counts[2] == counts_before_capture[2] + 1
    assert capture_counts[3] == counts_before_capture[3] + 1
    assert capture_counts[4] == counts_before_capture[4] + 1
    assert capture_counts[5] > counts_before_capture[5]
    assert SyncItemAttemptModel._default_manager.filter(run_id=capture_id).count() == 0
    capture_run = SyncRunModel._default_manager.get(run_id=capture_id)
    assert capture_run.trigger == "instrument_reference_capture"
    assert capture_run.outcome == "success"
    assert capture_run.published == 0

    replay = api_client.post(_CAPTURES_URL, capture_request, format="json")
    assert replay.status_code == 200
    assert replay.json()["snapshot"] == snapshot_receipt
    assert len(session.requests) == 2
    assert RawAuditModel._default_manager.filter(run_id=capture_id).count() == 2
    assert RawPayloadModel._default_manager.filter(payload_id__in=raw_payload_ids).count() == 2
    assert RawPayloadModel._default_manager.count() == capture_counts[1]
    assert InstrumentReferenceSnapshotModel._default_manager.filter(run_id=capture_id).count() == 1
    assert (
        RuntimeConfigProfileModel._default_manager.count(),
        RuntimeConfigSnapshotModel._default_manager.count(),
        AssetMasterModel._default_manager.count(),
    ) == selector_counts_before


@pytest.mark.django_db(transaction=True)
def test_missing_mapping_wrong_scope_and_unknown_config_fail_with_exact_http_statuses(
    api_client: APIClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject missing authority inputs before fetching and keep failures inspectable."""

    _login_staff(api_client)
    session = _install_transport_and_global_mode(monkeypatch)
    mapping_receipt = _register_mapping(api_client)
    mapping_record_id = str(mapping_receipt["mapping_record_id"])

    missing_capture_id = uuid4()
    missing_mapping = api_client.post(
        _CAPTURES_URL,
        {
            "capture_id": str(missing_capture_id),
            "provider_configuration_id": 999_001,
            "mapping_record_id": str(uuid4()),
            "exchange_scope": ["SSE"],
            "list_status_scope": ["L"],
            "mode": "normal",
        },
        format="json",
    )
    assert missing_mapping.status_code == 404
    assert missing_mapping.json()["code"] == "INSTRUMENT_REFERENCE_MAPPING_NOT_FOUND"
    assert not SyncRunModel._default_manager.filter(run_id=missing_capture_id).exists()

    wrong_scope_capture_id = uuid4()
    wrong_scope = api_client.post(
        _CAPTURES_URL,
        {
            "capture_id": str(wrong_scope_capture_id),
            "provider_configuration_id": 999_002,
            "mapping_record_id": mapping_record_id,
            "exchange_scope": ["SZSE"],
            "list_status_scope": ["L"],
            "mode": "normal",
        },
        format="json",
    )
    assert wrong_scope.status_code == 400
    assert wrong_scope.json()["code"] == "INSTRUMENT_REFERENCE_CAPTURE_MAPPING_SCOPE_MISMATCH"
    assert not SyncRunModel._default_manager.filter(run_id=wrong_scope_capture_id).exists()

    unknown_config_capture_id = uuid4()
    counts_before_unknown_config = (
        RawAuditModel._default_manager.count(),
        RawPayloadModel._default_manager.count(),
        InstrumentReferenceSnapshotModel._default_manager.count(),
    )
    unknown_config = api_client.post(
        _CAPTURES_URL,
        {
            "capture_id": str(unknown_config_capture_id),
            "provider_configuration_id": 999_003,
            "mapping_record_id": mapping_record_id,
            "exchange_scope": ["SSE"],
            "list_status_scope": ["L"],
            "mode": "normal",
        },
        format="json",
    )
    assert unknown_config.status_code == 400
    assert (
        unknown_config.json()["code"]
        == "INSTRUMENT_REFERENCE_CAPTURE_PROVIDER_CONFIGURATION_INVALID"
    )
    assert SyncRunModel._default_manager.filter(run_id=unknown_config_capture_id).exists()
    assert not session.requests
    assert (
        RawAuditModel._default_manager.count(),
        RawPayloadModel._default_manager.count(),
        InstrumentReferenceSnapshotModel._default_manager.count(),
    ) == counts_before_unknown_config
