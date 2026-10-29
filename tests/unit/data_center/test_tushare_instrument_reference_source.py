"""Exact-body Tushare stock_basic source and RawAudit occurrence binding tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast
from uuid import UUID

import pytest

from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceProviderContract,
)
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
    parse_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure.fact_and_operational_models import RawAuditModel
from apps.data_center.infrastructure.tushare_client import TushareResponseEvidence
from apps.data_center.infrastructure.tushare_instrument_reference_source import (
    DjangoInstrumentReferenceRawAuditOccurrenceWriter,
    TushareInstrumentReferenceSource,
)
from core.exceptions import DataFetchError

_DATASET = "tushare.stock_basic.reference"
_FIELDS = (
    "ts_code",
    "name",
    "exchange",
    "market",
    "list_status",
    "list_date",
    "delist_date",
)
_FIELDS_WITH_CURRENCY = (*_FIELDS, "curr_type")
_COMPLETED_AT = datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
_RUN_ID = UUID("0f84554d-6341-43f9-b4dd-1eaed9d39d00")
_INGESTED_RUN_ID = UUID("205ab56d-9f75-487b-996e-7e7b1c86d2e1")


class InMemoryRawPayloadRepository:
    """Retain hash-addressed test responses without database or provider access."""

    def __init__(self) -> None:
        self.rows: dict[str, RawPayload] = {}

    def save(self, payload: RawPayload) -> RawPayload:
        existing = self.rows.get(payload.payload_hash)
        if existing is not None and existing != payload:
            raise ValueError("immutable payload conflict")
        self.rows[payload.payload_hash] = payload
        return payload

    def get_by_hash(self, payload_hash: str) -> RawPayload | None:
        return self.rows.get(payload_hash)


class InMemoryRawAuditRepository:
    """Emulate the actual exact-id repository boundary for source unit tests."""

    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.rows: dict[str, RawAudit] = {}
        self.next_id = 1

    def log(self, audit: RawAudit) -> RawAudit:
        raw_audit_id = str(self.next_id)
        self.next_id += 1
        persisted = replace(
            audit,
            raw_audit_id=raw_audit_id,
            content_hash=raw_audit_content_hash(audit),
        )
        self.rows[raw_audit_id] = persisted
        return persisted

    def get_by_id(self, raw_audit_id: str) -> RawAudit | None:
        return self.rows.get(raw_audit_id)

    def get_recent(
        self,
        provider_name: str | None = None,
        capability: str | None = None,
        limit: int = 100,
    ) -> list[RawAudit]:
        del provider_name, capability
        return list(self.rows.values())[:limit]


@dataclass(frozen=True)
class CapturedFrame:
    """Expose just the witnessed-response surface consumed by the source."""

    response_evidence: TushareResponseEvidence


class CapturedStockBasicClient:
    """Build immutable fake provider bodies for each explicit request scope."""

    def __init__(
        self,
        payload_repository: InMemoryRawPayloadRepository,
        *,
        rows: list[list[object]] | None = None,
        returned_fields: tuple[str, ...] = _FIELDS,
        request_params_override: dict[str, object] | None = None,
        missing_reference: bool = False,
    ) -> None:
        self.payload_repository = payload_repository
        self.rows = rows
        self.returned_fields = returned_fields
        self.request_params_override = request_params_override
        self.missing_reference = missing_reference
        self.calls: list[dict[str, object]] = []

    def stock_basic(self, *, exchange: str, list_status: str, fields: str) -> CapturedFrame:
        self.calls.append({"exchange": exchange, "list_status": list_status, "fields": fields})
        source_rows = self.rows
        if source_rows is None:
            source_rows = [
                [
                    "600000.SH" if exchange == "SSE" else "000001.SZ",
                    "Fixture",
                    exchange,
                    "主板",
                    list_status,
                    "20200102",
                    None,
                ]
            ]
        body = json.dumps(
            {
                "code": 0,
                "msg": None,
                "data": {"fields": list(self.returned_fields), "items": source_rows},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        capture = ProviderResponseCapture(
            body=body,
            payload=parse_provider_response_json(body),
            body_sha256=sha256(body).hexdigest(),
            body_size_bytes=len(body),
            response_completed_at=_COMPLETED_AT,
            status_code=200,
            content_type="application/json",
            transport=ProviderResponseTransport.DIRECT,
        )
        request_params = self.request_params_override or {
            "api_name": "stock_basic",
            "fields": fields,
            "params": {"exchange": exchange, "list_status": list_status},
        }
        reference = RetainProviderResponsePayloadUseCase(self.payload_repository).execute(
            capture,
            provider_name="tushare",
            dataset_key=_DATASET,
            api_name="stock_basic",
            request_params=request_params,
        )
        if self.missing_reference:
            evidence = TushareResponseEvidence(
                body_sha256=reference.body_sha256,
                response_completed_at=reference.response_completed_at,
            )
        else:
            evidence = TushareResponseEvidence(
                body_sha256=reference.body_sha256,
                response_completed_at=reference.response_completed_at,
                raw_payload_reference=reference,
            )
        return CapturedFrame(evidence)


def _provider_contract(
    *,
    exchanges: tuple[str, ...] = ("SSE",),
    statuses: tuple[str, ...] = ("L",),
    fields: tuple[str, ...] = _FIELDS,
) -> InstrumentReferenceProviderContract:
    return InstrumentReferenceProviderContract(
        contract_id="tushare.stock_basic.reference",
        contract_version="fixture-v1",
        provider_name="tushare",
        dataset_key=_DATASET,
        api_name="stock_basic",
        fields=fields,
        exchange_scope=exchanges,
        list_status_scope=statuses,
    )


def _crosswalk() -> InstrumentReferenceExchangeSuffixCrosswalk:
    return InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="test.only.exchange-suffix",
        crosswalk_version="fixture-v1",
        exchange_suffix_pairs=(("SSE", "SH"), ("SZSE", "SZ"), ("BSE", "BJ")),
    )


def _build_source(
    *,
    rows: list[list[object]] | None = None,
    returned_fields: tuple[str, ...] = _FIELDS,
    request_params_override: dict[str, object] | None = None,
    missing_reference: bool = False,
    contract: InstrumentReferenceProviderContract | None = None,
) -> tuple[
    TushareInstrumentReferenceSource,
    CapturedStockBasicClient,
    InMemoryRawPayloadRepository,
    InMemoryRawAuditRepository,
]:
    payload_repository = InMemoryRawPayloadRepository()
    client = CapturedStockBasicClient(
        payload_repository,
        rows=rows,
        returned_fields=returned_fields,
        request_params_override=request_params_override,
        missing_reference=missing_reference,
    )
    audit_repository = InMemoryRawAuditRepository()
    writer = DjangoInstrumentReferenceRawAuditOccurrenceWriter(audit_repository)
    source = TushareInstrumentReferenceSource(
        client,
        payload_repository,
        writer,
        provider_contract=contract or _provider_contract(),
        exchange_suffix_crosswalk=_crosswalk(),
    )
    return source, client, payload_repository, audit_repository


def test_source_requests_every_explicit_exchange_and_status_and_preserves_unknown_times() -> None:
    contract = _provider_contract(exchanges=("SSE", "SZSE"), statuses=("L", "D"))
    source, client, _payloads, audit_repository = _build_source(contract=contract)

    candidate = source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)

    assert client.calls == [
        {"exchange": exchange, "list_status": status, "fields": ",".join(_FIELDS)}
        for exchange in ("SSE", "SZSE")
        for status in ("L", "D")
    ]
    assert len(candidate.occurrences) == 4
    assert len(candidate.records) == 4
    assert len(audit_repository.rows) == 4
    assert {row.source_list_status for row in candidate.records} == {"L", "D"}
    assert all(row.source_observed_at is None for row in candidate.records)
    assert all(row.source_available_at is None for row in candidate.records)
    assert candidate.must_not_use_for_decision is True
    assert candidate.must_not_execute is True


@pytest.mark.parametrize("currency", ["CNY", "USD", "", None])
def test_source_requests_and_preserves_optional_currency_exactly(
    currency: str | None,
) -> None:
    contract = _provider_contract(fields=_FIELDS_WITH_CURRENCY)
    source, client, _payloads, _audits = _build_source(
        contract=contract,
        returned_fields=_FIELDS_WITH_CURRENCY,
        rows=[["600000.SH", "Fixture", "SSE", "主板", "L", "20200102", None, currency]],
    )

    candidate = source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)

    assert client.calls == [
        {"exchange": "SSE", "list_status": "L", "fields": ",".join(_FIELDS_WITH_CURRENCY)}
    ]
    assert len(candidate.records) == 1
    assert candidate.records[0].source_currency == currency


@pytest.mark.parametrize("currency", [0, False, [], {}])
def test_source_rejects_nonstring_optional_currency(currency: object) -> None:
    contract = _provider_contract(fields=_FIELDS_WITH_CURRENCY)
    source, _client, _payloads, _audits = _build_source(
        contract=contract,
        returned_fields=_FIELDS_WITH_CURRENCY,
        rows=[["600000.SH", "Fixture", "SSE", "主板", "L", "20200102", None, currency]],
    )

    with pytest.raises(DataFetchError) as caught:
        source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)

    assert caught.value.code == "INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID"


def test_source_rejects_missing_optional_currency_field_or_row_value() -> None:
    contract = _provider_contract(fields=_FIELDS_WITH_CURRENCY)
    source, _client, _payloads, _audits = _build_source(
        contract=contract,
        returned_fields=_FIELDS,
        rows=[["600000.SH", "Fixture", "SSE", "主板", "L", "20200102", None, "CNY"]],
    )
    with pytest.raises(DataFetchError) as caught:
        source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)
    assert caught.value.code == "INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID"

    source, _client, _payloads, _audits = _build_source(
        contract=contract,
        returned_fields=_FIELDS_WITH_CURRENCY,
        rows=[["600000.SH", "Fixture", "SSE", "主板", "L", "20200102", None]],
    )
    with pytest.raises(DataFetchError) as caught:
        source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)
    assert caught.value.code == "INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID"


def test_legacy_seven_field_contract_keeps_source_currency_unknown() -> None:
    source, _client, _payloads, _audits = _build_source()

    candidate = source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)

    assert candidate.records[0].source_currency is None


def test_identical_body_occurrences_get_distinct_raw_audit_ids_and_redacted_requests() -> None:
    source, _client, payloads, audit_repository = _build_source()

    first = source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)
    second = source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)

    first_occurrence = first.occurrences[0]
    second_occurrence = second.occurrences[0]
    assert first_occurrence.raw_payload_hash == second_occurrence.raw_payload_hash
    assert first_occurrence.raw_payload_id == second_occurrence.raw_payload_id
    assert first_occurrence.response_body_sha256 == second_occurrence.response_body_sha256
    assert first_occurrence.raw_audit_reference.raw_audit_id != (
        second_occurrence.raw_audit_reference.raw_audit_id
    )
    assert first_occurrence.occurrence_id != second_occurrence.occurrence_id
    assert len(payloads.rows) == 1
    assert len(audit_repository.rows) == 2
    allowed_statuses = {value for value, _label in RawAuditModel.STATUS_CHOICES}
    for audit in audit_repository.rows.values():
        assert audit.status == "ok"
        assert audit.status in allowed_statuses
        assert audit.request_params == {
            "api_name": "stock_basic",
            "fields": ",".join(_FIELDS),
            "params": {"exchange": "SSE", "list_status": "L"},
        }
        assert "token" not in json.dumps(audit.request_params).casefold()
        assert audit.extra["instrument_reference_occurrence"]["database_alias"] == "default"
        assert audit.extra["instrument_reference_occurrence"]["raw_payload_reference"]


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        (
            [["600000.SZ", "Fixture", "SSE", "主板", "L", "20200102", None]],
            "INSTRUMENT_REFERENCE_IDENTITY_MISMATCH",
        ),
        (
            [["600000", "Fixture", "SSE", "主板", "L", "20200102", None]],
            "INSTRUMENT_REFERENCE_IDENTITY_MISMATCH",
        ),
        (
            [["600000.SH", "Fixture", "SZSE", "主板", "L", "20200102", None]],
            "INSTRUMENT_REFERENCE_REQUEST_SCOPE_MISMATCH",
        ),
        (
            [["600000.SH", "Fixture", "SSE", "主板", "D", "20200102", None]],
            "INSTRUMENT_REFERENCE_REQUEST_SCOPE_MISMATCH",
        ),
        (
            [["600000.SH", "Fixture", "SSE", "主板", "L", 20200102, None]],
            "INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID",
        ),
    ],
)
def test_source_blocks_suffix_scope_status_and_nonstring_date_mismatches(
    rows: list[list[object]],
    code: str,
) -> None:
    source, _client, _payloads, _audits = _build_source(rows=rows)

    with pytest.raises(DataFetchError) as caught:
        source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)

    assert caught.value.code == code


def test_source_blocks_unknown_status_instead_of_using_a_domain_default() -> None:
    source, _client, _payloads, _audits = _build_source(
        contract=_provider_contract(statuses=("L", "D")),
        rows=[["600000.SH", "Fixture", "SSE", "主板", "UN", "20200102", None]],
    )

    with pytest.raises(DataFetchError) as caught:
        source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)

    assert caught.value.code == "INSTRUMENT_REFERENCE_REQUEST_SCOPE_MISMATCH"


@pytest.mark.parametrize("returned_fields", [("ts_code",), (*_FIELDS, "board")])
def test_source_requires_exact_full_field_list(returned_fields: tuple[str, ...]) -> None:
    source, _client, _payloads, _audits = _build_source(returned_fields=returned_fields)

    with pytest.raises(DataFetchError) as caught:
        source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)

    assert caught.value.code == "INSTRUMENT_REFERENCE_RESPONSE_SCHEMA_INVALID"


def test_source_requires_exact_rawpayload_reference_and_request_scope() -> None:
    source, _client, _payloads, _audits = _build_source(missing_reference=True)

    with pytest.raises(DataFetchError) as caught:
        source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)

    assert caught.value.code == "INSTRUMENT_REFERENCE_RAW_EVIDENCE_UNAVAILABLE"

    wrong_request = {
        "api_name": "stock_basic",
        "fields": ",".join(_FIELDS),
        "params": {"exchange": "SSE", "list_status": "L", "limit": 1},
    }
    source, _client, _payloads, _audits = _build_source(
        request_params_override=wrong_request,
    )
    with pytest.raises(DataFetchError) as caught:
        source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)
    assert caught.value.code == "INSTRUMENT_REFERENCE_REQUEST_SCOPE_MISMATCH"


def test_source_requires_caller_owned_uuid_run_ids_before_provider_call() -> None:
    source, client, _payloads, _audits = _build_source()

    with pytest.raises(DataFetchError) as caught:
        source.fetch_candidate(
            run_id=cast(UUID, "caller-run"),
            ingested_run_id=_INGESTED_RUN_ID,
        )

    assert caught.value.code == "INSTRUMENT_REFERENCE_RUN_ID_INVALID"
    assert client.calls == []


def test_actual_recorder_rejects_wrong_default_alias_and_missing_exact_row() -> None:
    class WrongAliasRepository(InMemoryRawAuditRepository):
        unit_of_work_key = "django:other"

    with pytest.raises(ValueError, match="default"):
        DjangoInstrumentReferenceRawAuditOccurrenceWriter(WrongAliasRepository())

    class MissingReadbackRepository(InMemoryRawAuditRepository):
        def get_by_id(self, raw_audit_id: str) -> RawAudit | None:
            del raw_audit_id
            return None

    source, client, payloads, _audits = _build_source()
    writer = DjangoInstrumentReferenceRawAuditOccurrenceWriter(MissingReadbackRepository())
    source = TushareInstrumentReferenceSource(
        client,
        payloads,
        writer,
        provider_contract=_provider_contract(),
        exchange_suffix_crosswalk=_crosswalk(),
    )
    with pytest.raises(DataFetchError) as caught:
        source.fetch_candidate(run_id=_RUN_ID, ingested_run_id=_INGESTED_RUN_ID)
    assert caught.value.code == "INSTRUMENT_REFERENCE_RAW_AUDIT_UNAVAILABLE"
