"""API contracts for explicit instrument-reference mapping and capture operations."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from apps.data_center.application.instrument_reference_capture import (
    CaptureExecutionStatus,
    CaptureInvocationMode,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceMappingContent,
    InstrumentReferenceMappingRecord,
    make_instrument_reference_mapping_record,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceExchangeSuffixCrosswalk,
)
from apps.data_center.interface.tui_serializers import InstrumentReferenceCaptureTuiSerializer
from core.exceptions import DuplicateResourceError

_MAPPING_URL = "/api/data-center/tui/instrument-reference/mappings/"
_CAPTURE_URL = "/api/data-center/tui/instrument-reference/captures/"


def _mapping_payload() -> dict[str, object]:
    """Return explicit synthetic mapping material for an API contract only."""

    return {
        "mapping_id": "fixture.instrument-reference",
        "mapping_version": "fixture-v1",
        "source_crosswalk_id": "fixture.exchange-suffix",
        "source_crosswalk_version": "fixture-v1",
        "exchange_suffix_pairs": [["SSE", "SH"], ["SZSE", "SZ"]],
        "exchange_rule_market_pairs": [["SSE", "SSE"], ["SZSE", "SZSE"]],
        "exchange_source_market_board_pairs": [
            ["SSE", "fixture-market", "fixture-board"],
            ["SZSE", "fixture-market", "fixture-board"],
        ],
    }


def _mapping_record(content: InstrumentReferenceMappingContent) -> InstrumentReferenceMappingRecord:
    """Create a sealed in-memory receipt for mocked API composition calls."""

    return make_instrument_reference_mapping_record(
        content,
        mapping_record_id=uuid4(),
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _mapping_content(payload: dict[str, object]) -> InstrumentReferenceMappingContent:
    """Construct the same domain value from validated operator JSON."""

    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id=str(payload["source_crosswalk_id"]),
        crosswalk_version=str(payload["source_crosswalk_version"]),
        exchange_suffix_pairs=tuple(
            (str(pair[0]), str(pair[1])) for pair in payload["exchange_suffix_pairs"]
        ),
    )
    return InstrumentReferenceMappingContent(
        mapping_id=str(payload["mapping_id"]),
        mapping_version=str(payload["mapping_version"]),
        source_crosswalk=crosswalk,
        exchange_rule_market_pairs=tuple(
            (str(pair[0]), str(pair[1])) for pair in payload["exchange_rule_market_pairs"]
        ),
        exchange_source_market_board_pairs=tuple(
            (str(row[0]), str(row[1]), str(row[2]))
            for row in payload["exchange_source_market_board_pairs"]
        ),
    )


def test_capture_serializer_defaults_currency_off_and_accepts_only_json_booleans() -> None:
    base: dict[str, object] = {
        "capture_id": str(uuid4()),
        "provider_configuration_id": 17,
        "mapping_record_id": str(uuid4()),
        "exchange_scope": ["SSE"],
        "list_status_scope": ["L", "D"],
        "mode": "normal",
    }

    omitted = InstrumentReferenceCaptureTuiSerializer(data=base)
    assert omitted.is_valid()
    assert omitted.validated_data["include_currency"] is False
    for value in (False, True):
        explicit = InstrumentReferenceCaptureTuiSerializer(data={**base, "include_currency": value})
        assert explicit.is_valid()
        assert explicit.validated_data["include_currency"] is value
    for value in ("true", 1, 0, None, [], {}):
        invalid = InstrumentReferenceCaptureTuiSerializer(data={**base, "include_currency": value})
        assert not invalid.is_valid()


@pytest.mark.django_db
def test_mapping_register_is_admin_only_idempotent_and_conflict_visible(
    client,
    django_user_model,
    monkeypatch,
) -> None:
    """Save exact operator mapping bytes, replay the receipt, and reject version mutation."""

    ordinary_user = django_user_model.objects.create_user(
        username="instrument_reference_operator_user",
        password="password",
    )
    admin_user = django_user_model.objects.create_user(
        username="instrument_reference_operator_admin",
        password="password",
        is_staff=True,
    )
    payload = _mapping_payload()
    content = _mapping_content(payload)
    record = _mapping_record(content)
    receipts: dict[tuple[str, str], InstrumentReferenceMappingRecord] = {}
    observed: list[InstrumentReferenceMappingContent] = []

    def save_mapping(candidate: InstrumentReferenceMappingContent):
        observed.append(candidate)
        key = (candidate.mapping_id, candidate.mapping_version)
        existing = receipts.get(key)
        if existing is not None:
            if existing.content != candidate:
                raise DuplicateResourceError(
                    "Mapping version is immutable.",
                    code="INSTRUMENT_REFERENCE_MAPPING_VERSION_IMMUTABLE",
                )
            return existing
        receipts[key] = record
        return record

    def read_mapping(*, mapping_record_id: UUID):
        if mapping_record_id == record.mapping_record_id:
            return record
        return None

    monkeypatch.setattr(
        "apps.data_center.interface.tui_views.save_instrument_reference_mapping",
        save_mapping,
    )
    monkeypatch.setattr(
        "apps.data_center.interface.tui_views.read_instrument_reference_mapping",
        read_mapping,
    )

    client.force_login(ordinary_user)
    denied = client.post(_MAPPING_URL, payload, content_type="application/json")
    assert denied.status_code == 403
    assert denied["Content-Type"] == "application/json"

    client.force_login(admin_user)

    collection_get = client.get(_MAPPING_URL)
    collection_head = client.head(_MAPPING_URL)
    collection_options = client.options(_MAPPING_URL)
    detail_url = f"{_MAPPING_URL}{record.mapping_record_id}/"
    detail_post = client.post(
        detail_url,
        payload,
        content_type="application/json",
    )
    detail_head = client.head(detail_url)
    detail_options = client.options(detail_url)

    expected_collection_methods = {"POST", "OPTIONS"}
    expected_detail_methods = {"GET", "HEAD", "OPTIONS"}
    method_responses = (
        (collection_get, expected_collection_methods),
        (collection_head, expected_collection_methods),
        (collection_options, expected_collection_methods),
        (detail_post, expected_detail_methods),
        (detail_head, expected_detail_methods),
        (detail_options, expected_detail_methods),
    )
    for response, expected_methods in method_responses:
        actual_methods = {method.strip() for method in response["Allow"].split(",")}
        assert actual_methods == expected_methods

    for unsupported_response in (collection_get, collection_head, detail_post):
        assert unsupported_response.status_code == 405
        assert unsupported_response["Content-Type"] == "application/json"
    for json_response in (collection_get, detail_post):
        assert isinstance(json_response.json(), dict)
    assert collection_options.status_code == 200
    assert detail_head.status_code == 200
    assert detail_head["Content-Type"] == "application/json"
    assert detail_options.status_code == 200
    assert detail_options["Content-Type"] == "application/json"
    assert observed == []

    unknown = {**payload, "approval_status": "approved"}
    rejected = client.post(_MAPPING_URL, unknown, content_type="application/json")
    assert rejected.status_code == 400
    ambiguous = {
        **payload,
        "exchange_suffix_pairs": [["SSE", "SH"], ["SSE", "SZ"]],
    }
    invalid = client.post(_MAPPING_URL, ambiguous, content_type="application/json")
    assert invalid.status_code == 400
    assert observed == []

    first = client.post(_MAPPING_URL, payload, content_type="application/json")
    replay = client.post(_MAPPING_URL, payload, content_type="application/json")
    assert first.status_code == replay.status_code == 200
    assert first["Content-Type"] == "application/json"
    assert first.json()["mapping"] == replay.json()["mapping"]
    assert first.json()["mapping"]["content"] == content.to_payload()
    assert first.json()["mapping"]["owner_or_provider_approval_asserted"] is False
    assert observed == [content, content]

    exact = client.get(f"{_MAPPING_URL}{record.mapping_record_id}/")
    missing = client.get(f"{_MAPPING_URL}{uuid4()}/")
    assert exact.status_code == 200
    assert exact.json()["mapping"]["mapping_record_id"] == str(record.mapping_record_id)
    assert missing.status_code == 404

    changed = {**payload, "exchange_suffix_pairs": [["SSE", "SHX"], ["SZSE", "SZ"]]}
    conflict = client.post(_MAPPING_URL, changed, content_type="application/json")
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "INSTRUMENT_REFERENCE_MAPPING_VERSION_IMMUTABLE"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("capture_status", "expected_http", "expected_outcome", "expected_message"),
    [
        (
            CaptureExecutionStatus.COMPLETED,
            200,
            "success",
            "来源快照采集已完成",
        ),
        (
            CaptureExecutionStatus.IN_PROGRESS,
            202,
            "noop",
            "处理中",
        ),
        (
            CaptureExecutionStatus.RESUME_REQUIRED,
            202,
            "blocked",
            "需要明确恢复",
        ),
        (
            CaptureExecutionStatus.BLOCKED,
            409,
            "blocked",
            "已阻断",
        ),
    ],
)
@pytest.mark.parametrize("include_currency", [None, False, True])
def test_capture_request_preserves_exact_inputs_and_normalizes_actual_status(
    client,
    django_user_model,
    monkeypatch,
    capture_status: CaptureExecutionStatus,
    expected_http: int,
    expected_outcome: str,
    expected_message: str,
    include_currency: bool | None,
) -> None:
    """Forward exact inputs and normalize capture progress without inventing completion."""

    ordinary_user = django_user_model.objects.create_user(
        username="instrument_reference_capture_user",
        password="password",
    )
    admin_user = django_user_model.objects.create_user(
        username="instrument_reference_capture_admin",
        password="password",
        is_staff=True,
    )
    capture_id = uuid4()
    mapping_record_id = uuid4()
    observed: dict[str, object] = {}
    capture_mapping_record = _mapping_record(_mapping_content(_mapping_payload()))
    captured_fields = (
        "ts_code",
        "name",
        "exchange",
        "market",
        "list_status",
        "list_date",
        "delist_date",
    )
    if include_currency is True:
        captured_fields += ("curr_type",)
    capture_provider_contract = SimpleNamespace(
        contract_id="fixture-stock-basic",
        contract_version="v2" if include_currency is True else "v1",
        provider_name="tushare",
        dataset_key="instrument_reference",
        api_name="stock_basic",
        fields=captured_fields,
        exchange_scope=("SSE",),
        list_status_scope=("L",),
        content_hash="f" * 64,
    )
    capture_crosswalk = SimpleNamespace(
        crosswalk_id="fixture-crosswalk",
        crosswalk_version="v1",
        exchange_suffix_pairs=(("SSE", "SH"),),
        content_hash="e" * 64,
    )
    capture_snapshot = SimpleNamespace(
        snapshot_id=uuid4(),
        mapping_record=capture_mapping_record,
        content_hash="c" * 64,
        record_digest="sha256:" + "d" * 64,
        recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
        content=SimpleNamespace(
            run_id=uuid4(),
            fetch_rounds=(
                SimpleNamespace(
                    candidate=SimpleNamespace(
                        provider_contract=capture_provider_contract,
                        crosswalk=capture_crosswalk,
                    )
                ),
            ),
            record_count=0,
            occurrence_count=1,
            empty_occurrence_count=1,
            last_response_completed_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_observed_at=None,
            source_available_at=None,
            must_not_use_for_decision=True,
            must_not_execute=True,
            blocked_reason="INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY",
        ),
    )

    def capture(**values: object) -> SimpleNamespace:
        observed.update(values)
        return SimpleNamespace(
            status=capture_status,
            request_sha256="a" * 64,
            reason_code=None,
            snapshot=(
                capture_snapshot if capture_status is CaptureExecutionStatus.COMPLETED else None
            ),
        )

    monkeypatch.setattr(
        "apps.data_center.interface.tui_views.capture_instrument_reference_snapshot",
        capture,
    )
    client.force_login(ordinary_user)
    denied = client.post(
        _CAPTURE_URL,
        {"capture_id": str(capture_id)},
        content_type="application/json",
    )
    assert denied.status_code == 403
    assert denied["Content-Type"] == "application/json"

    client.force_login(admin_user)
    base_payload: dict[str, object] = {
        "capture_id": str(capture_id),
        "provider_configuration_id": 17,
        "mapping_record_id": str(mapping_record_id),
        "exchange_scope": ["SSE"],
        "list_status_scope": ["L", "D"],
        "mode": "normal",
    }
    invalid = client.post(
        _CAPTURE_URL,
        {**base_payload, "include_currency": "true"},
        content_type="application/json",
    )
    assert invalid.status_code == 400
    assert invalid["Content-Type"] == "application/json"
    assert observed == {}

    payload = dict(base_payload)
    if include_currency is not None:
        payload["include_currency"] = include_currency
    response = client.post(_CAPTURE_URL, payload, content_type="application/json")

    assert response.status_code == expected_http
    assert response["Content-Type"] == "application/json"
    assert response.json()["outcome"] == expected_outcome
    assert expected_message in response.json()["message"]
    assert response.json()["status"] == capture_status.value
    assert response.json()["success"] is (capture_status is CaptureExecutionStatus.COMPLETED)
    assert (response.json()["snapshot"] is not None) is (
        capture_status is CaptureExecutionStatus.COMPLETED
    )
    assert response.json()["decision_ready"] is False
    assert response.json()["provider_configuration_id"] == 17
    assert response.json()["mapping_record_id"] == str(mapping_record_id)
    assert response.json()["exchange_scope"] == ["SSE"]
    assert response.json()["list_status_scope"] == ["L", "D"]
    expected_currency = include_currency is True
    assert response.json()["include_currency"] is expected_currency
    if response.json()["snapshot"] is not None:
        provider_contract = response.json()["snapshot"]["provider_contract"]
        assert provider_contract["contract_version"] == ("v2" if expected_currency else "v1")
        assert ("curr_type" in provider_contract["fields"]) is expected_currency
    assert observed == {
        "capture_id": capture_id,
        "provider_configuration_id": 17,
        "mapping_record_id": mapping_record_id,
        "exchange_scope": ("SSE",),
        "list_status_scope": ("L", "D"),
        "actor_provenance": f"tui-admin:{admin_user.pk}",
        "mode": CaptureInvocationMode.NORMAL,
        "include_currency": expected_currency,
    }


@pytest.mark.django_db
def test_exact_snapshot_read_returns_source_rows_and_unknown_upstream_times(
    client,
    django_user_model,
    monkeypatch,
) -> None:
    """Page source rows and exact occurrences independently without inventing source time."""

    ordinary_user = django_user_model.objects.create_user(
        username="instrument_reference_snapshot_user",
        password="password",
    )
    admin_user = django_user_model.objects.create_user(
        username="instrument_reference_snapshot_admin",
        password="password",
        is_staff=True,
    )
    mapping_record = _mapping_record(_mapping_content(_mapping_payload()))
    snapshot_id = uuid4()
    run_id = uuid4()
    raw_audit_hashes = ("a" * 64, "b" * 64, "c" * 64)
    raw_audit_ids = ("fixture-audit-1", "fixture-audit-2", "fixture-audit-3")

    def raw_audit(index: int) -> SimpleNamespace:
        return SimpleNamespace(
            raw_audit_id=raw_audit_ids[index],
            version="1",
            content_hash=raw_audit_hashes[index],
            run_id=str(run_id),
            ingested_run_id=f"fixture-ingest-{index + 1}",
        )

    provider_contract = SimpleNamespace(
        contract_id="fixture-stock-basic",
        contract_version="v2",
        provider_name="tushare",
        dataset_key="instrument_reference",
        api_name="stock_basic",
        fields=(
            "ts_code",
            "name",
            "exchange",
            "market",
            "list_status",
            "list_date",
            "delist_date",
            "curr_type",
        ),
        exchange_scope=("SSE", "SZSE"),
        list_status_scope=("L", "D"),
        content_hash="f" * 64,
    )
    crosswalk = SimpleNamespace(
        crosswalk_id="fixture-crosswalk",
        crosswalk_version="v1",
        exchange_suffix_pairs=(("SSE", "SH"), ("SZSE", "SZ")),
        content_hash="e" * 64,
    )
    completed_at = (
        datetime(2026, 1, 2, 3, 0, tzinfo=UTC),
        datetime(2026, 1, 2, 4, 0, tzinfo=UTC),
        datetime(2026, 1, 2, 5, 0, tzinfo=UTC),
    )
    occurrences = tuple(
        SimpleNamespace(
            occurrence_id=uuid4(),
            exchange=exchange,
            list_status=list_status,
            raw_audit_reference=raw_audit(index),
            raw_payload_id=f"fixture-payload-{index + 1}",
            raw_payload_hash="sha256:" + chr(ord("d") + index) * 64,
            response_body_sha256=chr(ord("1") + index) * 64,
            response_completed_at=completed_at[index],
            row_count=row_count,
        )
        for index, (exchange, list_status, row_count) in enumerate(
            (("SSE", "L", 1), ("SSE", "D", 0), ("SZSE", "L", 1))
        )
    )
    row = SimpleNamespace(
        ts_code="FIXTURE.SH",
        name="Fixture source row",
        source_exchange="SSE",
        source_market="fixture-market",
        source_list_status="L",
        list_date_raw="20260101",
        list_date=date(2026, 1, 1),
        delist_date_raw=None,
        delist_date=None,
        exchange_suffix="SH",
        occurrence_id=occurrences[0].occurrence_id,
        raw_audit_reference=occurrences[0].raw_audit_reference,
        raw_payload_id=occurrences[0].raw_payload_id,
        raw_payload_hash=occurrences[0].raw_payload_hash,
        source_currency="CNY",
        source_observed_at=None,
        source_available_at=None,
    )
    second_row = SimpleNamespace(
        ts_code="FIXTURE.SZ",
        name="Second source row",
        source_exchange="SZSE",
        source_market="fixture-market",
        source_list_status="L",
        list_date_raw=None,
        list_date=None,
        delist_date_raw="20261231",
        delist_date=date(2026, 12, 31),
        exchange_suffix="SZ",
        occurrence_id=occurrences[2].occurrence_id,
        raw_audit_reference=occurrences[2].raw_audit_reference,
        raw_payload_id=occurrences[2].raw_payload_id,
        raw_payload_hash=occurrences[2].raw_payload_hash,
        source_currency=None,
        source_observed_at=None,
        source_available_at=None,
    )
    first_round = SimpleNamespace(
        fetch_round_id=uuid4(),
        candidate=SimpleNamespace(
            provider_contract=provider_contract,
            crosswalk=crosswalk,
            occurrences=occurrences[:2],
            records=(row,),
        ),
    )
    second_round = SimpleNamespace(
        fetch_round_id=uuid4(),
        candidate=SimpleNamespace(
            provider_contract=provider_contract,
            crosswalk=crosswalk,
            occurrences=occurrences[2:],
            records=(second_row,),
        ),
    )
    record = SimpleNamespace(
        snapshot_id=snapshot_id,
        mapping_record=mapping_record,
        recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
        content_hash="c" * 64,
        record_digest="sha256:" + "d" * 64,
        content=SimpleNamespace(
            run_id=run_id,
            last_response_completed_at=completed_at[-1],
            record_count=2,
            occurrence_count=3,
            empty_occurrence_count=1,
            source_observed_at=None,
            source_available_at=None,
            must_not_use_for_decision=True,
            must_not_execute=True,
            blocked_reason="INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY",
            fetch_rounds=(first_round, second_round),
        ),
    )
    monkeypatch.setattr(
        "apps.data_center.interface.tui_views.read_instrument_reference_snapshot",
        lambda *, snapshot_id: record if snapshot_id == record.snapshot_id else None,
    )

    client.force_login(ordinary_user)
    denied = client.get(f"/api/data-center/tui/instrument-reference/snapshots/{snapshot_id}/")
    assert denied.status_code == 403

    client.force_login(admin_user)
    response = client.get(
        f"/api/data-center/tui/instrument-reference/snapshots/{snapshot_id}/?limit=1&offset=0"
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    body = response.json()
    assert body["snapshot"]["snapshot_id"] == str(snapshot_id)
    assert body["snapshot"]["run_id"] == str(run_id)
    assert body["snapshot"]["fetch_round_count"] == 2
    assert body["snapshot"]["last_response_completed_at"] == completed_at[-1].isoformat()
    assert body["snapshot"]["provider_contract"] == {
        "contract_id": "fixture-stock-basic",
        "contract_version": "v2",
        "provider_name": "tushare",
        "dataset_key": "instrument_reference",
        "api_name": "stock_basic",
        "fields": [
            "ts_code",
            "name",
            "exchange",
            "market",
            "list_status",
            "list_date",
            "delist_date",
            "curr_type",
        ],
        "exchange_scope_count": 2,
        "list_status_scope_count": 2,
        "content_hash": "f" * 64,
    }
    assert body["snapshot"]["crosswalk"] == {
        "crosswalk_id": "fixture-crosswalk",
        "crosswalk_version": "v1",
        "content_hash": "e" * 64,
    }
    assert body["snapshot"]["source_observed_at"] is None
    assert body["snapshot"]["source_available_at"] is None
    assert body["snapshot"]["must_not_use_for_decision"] is True
    assert body["total"] == 2
    assert body["next_offset"] == 1
    assert body["rows"] == [
        {
            "ts_code": "FIXTURE.SH",
            "name": "Fixture source row",
            "source_exchange": "SSE",
            "source_market": "fixture-market",
            "source_list_status": "L",
            "list_date_raw": "20260101",
            "list_date": "2026-01-01",
            "delist_date_raw": None,
            "delist_date": None,
            "exchange_suffix": "SH",
            "occurrence_id": str(row.occurrence_id),
            "raw_audit_id": "fixture-audit-1",
            "raw_audit_reference": {
                "raw_audit_id": "fixture-audit-1",
                "version": "1",
                "content_hash": "a" * 64,
                "run_id": str(run_id),
                "ingested_run_id": "fixture-ingest-1",
            },
            "raw_audit_version": "1",
            "raw_audit_content_hash": "a" * 64,
            "raw_audit_run_id": str(run_id),
            "raw_audit_ingested_run_id": "fixture-ingest-1",
            "raw_payload_id": "fixture-payload-1",
            "raw_payload_hash": "sha256:" + "d" * 64,
            "source_currency": "CNY",
            "source_observed_at": None,
            "source_available_at": None,
            "upstream_time_unknown": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }
    ]
    assert body["occurrence_offset"] == 0
    assert body["occurrence_limit"] == 1
    assert body["occurrence_total"] == 3
    assert body["occurrence_next_offset"] == 1
    first_occurrence = body["occurrences"][0]
    assert first_occurrence == {
        "fetch_round_id": str(first_round.fetch_round_id),
        "provider_contract_id": "fixture-stock-basic",
        "provider_contract_version": "v2",
        "provider_contract_content_hash": "f" * 64,
        "crosswalk_id": "fixture-crosswalk",
        "crosswalk_version": "v1",
        "crosswalk_content_hash": "e" * 64,
        "occurrence_id": str(occurrences[0].occurrence_id),
        "exchange": "SSE",
        "list_status": "L",
        "raw_audit_id": "fixture-audit-1",
        "raw_audit_reference": {
            "raw_audit_id": "fixture-audit-1",
            "version": "1",
            "content_hash": "a" * 64,
            "run_id": str(run_id),
            "ingested_run_id": "fixture-ingest-1",
        },
        "raw_audit_version": "1",
        "raw_audit_content_hash": "a" * 64,
        "raw_audit_run_id": str(run_id),
        "raw_audit_ingested_run_id": "fixture-ingest-1",
        "raw_payload_id": "fixture-payload-1",
        "raw_payload_hash": "sha256:" + "d" * 64,
        "response_body_sha256": "1" * 64,
        "response_completed_at": completed_at[0].isoformat(),
        "row_count": 1,
        "source_observed_at": None,
        "source_available_at": None,
        "upstream_time_unknown": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "blocked_reason": "INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY",
    }

    second_page = client.get(
        f"/api/data-center/tui/instrument-reference/snapshots/{snapshot_id}/?limit=1&offset=1"
    )
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert second_body["total"] == 2
    assert second_body["next_offset"] is None
    assert second_body["rows"][0]["ts_code"] == "FIXTURE.SZ"
    assert second_body["rows"][0]["delist_date"] == "2026-12-31"
    assert second_body["rows"][0]["source_currency"] is None
    assert second_body["rows"][0]["raw_audit_id"] == "fixture-audit-3"
    assert second_body["rows"][0]["raw_payload_id"] == "fixture-payload-3"
    assert second_body["rows"][0]["raw_payload_hash"] == "sha256:" + "f" * 64
    assert second_body["occurrence_total"] == 3
    assert second_body["occurrence_next_offset"] == 2
    empty_occurrence = second_body["occurrences"][0]
    assert empty_occurrence["fetch_round_id"] == str(first_round.fetch_round_id)
    assert empty_occurrence["occurrence_id"] == str(occurrences[1].occurrence_id)
    assert empty_occurrence["exchange"] == "SSE"
    assert empty_occurrence["list_status"] == "D"
    assert empty_occurrence["response_completed_at"] == completed_at[1].isoformat()
    assert empty_occurrence["response_body_sha256"] == "2" * 64
    assert empty_occurrence["raw_audit_reference"] == {
        "raw_audit_id": "fixture-audit-2",
        "version": "1",
        "content_hash": "b" * 64,
        "run_id": str(run_id),
        "ingested_run_id": "fixture-ingest-2",
    }
    assert empty_occurrence["row_count"] == 0

    end_page = client.get(
        f"/api/data-center/tui/instrument-reference/snapshots/{snapshot_id}/?limit=1&offset=2"
    )
    assert end_page.status_code == 200
    end_body = end_page.json()
    assert end_body["rows"] == []
    assert end_body["total"] == 2
    assert end_body["next_offset"] is None
    assert end_body["occurrences"][0]["occurrence_id"] == str(occurrences[2].occurrence_id)
    assert end_body["occurrences"][0]["fetch_round_id"] == str(second_round.fetch_round_id)
    assert end_body["occurrence_next_offset"] is None
    beyond_end = client.get(
        f"/api/data-center/tui/instrument-reference/snapshots/{snapshot_id}/?limit=1&offset=3"
    )
    assert beyond_end.status_code == 200
    beyond_end_body = beyond_end.json()
    assert beyond_end_body["rows"] == []
    assert beyond_end_body["total"] == 2
    assert beyond_end_body["next_offset"] is None
    assert beyond_end_body["occurrences"] == []
    assert beyond_end_body["occurrence_total"] == 3
    assert beyond_end_body["occurrence_next_offset"] is None
    assert "security_id" not in body["rows"][0]
    assert "asset_type" not in body["rows"][0]
