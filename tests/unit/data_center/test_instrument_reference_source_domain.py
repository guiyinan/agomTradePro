"""Pure contracts for explicitly scoped instrument-reference responses."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from typing import cast
from uuid import UUID

import pytest

from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceOccurrence,
    InstrumentReferenceProviderContract,
    InstrumentReferenceRecord,
)


def _contract(
    *,
    exchanges: tuple[str, ...] = ("SSE", "SZSE"),
    statuses: tuple[str, ...] = ("L", "D"),
) -> InstrumentReferenceProviderContract:
    return InstrumentReferenceProviderContract(
        contract_id="tushare.stock_basic.reference",
        contract_version="2026-10-16.1",
        provider_name="tushare",
        dataset_key="tushare.stock_basic.reference",
        api_name="stock_basic",
        fields=("ts_code", "name", "exchange", "market", "list_status", "list_date", "delist_date"),
        exchange_scope=exchanges,
        list_status_scope=statuses,
    )


def _crosswalk() -> InstrumentReferenceExchangeSuffixCrosswalk:
    return InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture.crosswalk",
        crosswalk_version="fixture.1",
        exchange_suffix_pairs=(("SSE", "SH"), ("SZSE", "SZ")),
    )


def _audit_ref() -> RawAuditReference:
    return RawAuditReference(
        raw_audit_id="42",
        version="1",
        content_hash="a" * 64,
        run_id="0f84554d-6341-43f9-b4dd-1eaed9d39d00",
        ingested_run_id="205ab56d-9f75-487b-996e-7e7b1c86d2e1",
    )


def _occurrence() -> InstrumentReferenceOccurrence:
    return InstrumentReferenceOccurrence(
        occurrence_id=UUID("d805500e-c59c-4b89-b07b-fb605c54ffb1"),
        exchange="SSE",
        list_status="L",
        raw_audit_reference=_audit_ref(),
        raw_payload_id="payload-1",
        raw_payload_hash="sha256:" + "b" * 64,
        response_body_sha256="c" * 64,
        response_completed_at=datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
        row_count=1,
    )


def _record() -> InstrumentReferenceRecord:
    occurrence = _occurrence()
    return InstrumentReferenceRecord(
        ts_code="600000.SH",
        name="浦发银行",
        source_exchange="SSE",
        source_market="主板",
        source_list_status="L",
        list_date_raw="19991110",
        list_date=date(1999, 11, 10),
        delist_date_raw=None,
        delist_date=None,
        exchange_suffix="SH",
        occurrence_id=occurrence.occurrence_id,
        raw_audit_reference=occurrence.raw_audit_reference,
        raw_payload_id=occurrence.raw_payload_id,
        raw_payload_hash=occurrence.raw_payload_hash,
    )


def test_explicit_contract_and_crosswalk_are_content_hashed() -> None:
    contract = _contract()
    crosswalk = _crosswalk()

    assert len(contract.content_hash) == 64
    assert contract.content_hash != _contract(statuses=("D", "L")).content_hash
    assert len(crosswalk.content_hash) == 64
    assert crosswalk.suffix_for("SSE") == "SH"
    assert crosswalk.suffix_for("UNKNOWN") is None
    assert crosswalk.matches("600000.SH", "SSE")
    assert not crosswalk.matches("600000.SZ", "SSE")
    assert not crosswalk.matches("600000.SH", "UNKNOWN")
    assert not crosswalk.matches(".SH", "SSE")
    assert not crosswalk.matches("600000.SH.extra", "SSE")
    assert not crosswalk.matches(" 600000.SH", "SSE")


@pytest.mark.parametrize(
    "values",
    [
        {"exchange_scope": ()},
        {"list_status_scope": ()},
        {"fields": ("ts_code", "ts_code")},
        {"fields": cast(tuple[str, ...], [*_contract().fields])},
        {"exchange_scope": cast(tuple[str, ...], ["SSE"])},
        {"list_status_scope": cast(tuple[str, ...], ["L"])},
        {"exchange_scope": ("SSE", "SSE")},
        {"list_status_scope": ("L", "L")},
    ],
)
def test_provider_contract_rejects_ambiguous_or_empty_scope(values: dict[str, object]) -> None:
    defaults: dict[str, object] = {
        "contract_id": "tushare.stock_basic.reference",
        "contract_version": "2026-10-16.1",
        "provider_name": "tushare",
        "dataset_key": "tushare.stock_basic.reference",
        "api_name": "stock_basic",
        "fields": (
            "ts_code",
            "name",
            "exchange",
            "market",
            "list_status",
            "list_date",
            "delist_date",
        ),
        "exchange_scope": ("SSE",),
        "list_status_scope": ("L",),
    }
    defaults.update(values)

    with pytest.raises(ValueError):
        InstrumentReferenceProviderContract(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"api_name": "daily"},
        {"fields": ("ts_code",)},
    ],
)
def test_provider_contract_rejects_unversioned_api_or_incomplete_fields(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(_contract(), **changes)


@pytest.mark.parametrize(
    "pairs",
    [(), (("SSE", "SH"), ("SSE", "SZ")), (("SSE", "SH"), ("SZSE", "SH"))],
)
def test_crosswalk_rejects_empty_or_ambiguous_mappings(
    pairs: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ValueError):
        InstrumentReferenceExchangeSuffixCrosswalk(
            crosswalk_id="fixture.crosswalk",
            crosswalk_version="fixture.1",
            exchange_suffix_pairs=pairs,
        )


@pytest.mark.parametrize(
    "pairs",
    [
        (("SSE",),),
        (("SSE", "SH.X"),),
        (cast(tuple[str, str], ["SSE", "SH"]),),
    ],
)
def test_crosswalk_rejects_malformed_mapping_rows(
    pairs: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ValueError):
        InstrumentReferenceExchangeSuffixCrosswalk(
            crosswalk_id="fixture.crosswalk",
            crosswalk_version="fixture.1",
            exchange_suffix_pairs=pairs,
        )


def test_crosswalk_rejects_mutable_outer_pair_collection() -> None:
    with pytest.raises(ValueError):
        InstrumentReferenceExchangeSuffixCrosswalk(
            crosswalk_id="fixture.crosswalk",
            crosswalk_version="fixture.1",
            exchange_suffix_pairs=cast(tuple[tuple[str, str], ...], [("SSE", "SH")]),
        )


def test_candidate_keeps_source_times_unknown_and_is_always_non_decision() -> None:
    candidate = InstrumentReferenceCandidate(
        provider_contract=_contract(exchanges=("SSE",), statuses=("L",)),
        crosswalk=_crosswalk(),
        occurrences=(_occurrence(),),
        records=(_record(),),
    )

    assert candidate.source_observed_at is None
    assert candidate.source_available_at is None
    assert candidate.must_not_use_for_decision is True
    assert candidate.must_not_execute is True
    assert candidate.blocked_reason == "INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY"
    assert candidate.contract_hash == candidate.provider_contract.content_hash
    assert candidate.crosswalk_hash == candidate.crosswalk.content_hash


@pytest.mark.parametrize(
    ("occurrences", "records"),
    [
        ([_occurrence()], (_record(),)),
        ((_occurrence(),), [_record()]),
    ],
)
def test_candidate_rejects_mutable_row_and_occurrence_collections(
    occurrences: object,
    records: object,
) -> None:
    with pytest.raises(ValueError):
        InstrumentReferenceCandidate(
            provider_contract=_contract(exchanges=("SSE",), statuses=("L",)),
            crosswalk=_crosswalk(),
            occurrences=cast(tuple[InstrumentReferenceOccurrence, ...], occurrences),
            records=cast(tuple[InstrumentReferenceRecord, ...], records),
        )


def test_candidate_rejects_omitted_or_extra_records_per_occurrence() -> None:
    occurrence = _occurrence()
    record = _record()

    for records in ((), (record, record)):
        with pytest.raises(ValueError):
            InstrumentReferenceCandidate(
                provider_contract=_contract(exchanges=("SSE",), statuses=("L",)),
                crosswalk=_crosswalk(),
                occurrences=(occurrence,),
                records=records,
            )


@pytest.mark.parametrize("duplicate", ["occurrence", "audit"])
def test_candidate_rejects_reused_occurrence_or_raw_audit_identity(duplicate: str) -> None:
    first = _occurrence()
    first = replace(first, row_count=0)
    second = replace(
        first,
        exchange="SZSE",
        occurrence_id=UUID("fa3f7e75-87b2-4e43-8744-93179fa94870"),
    )
    if duplicate == "occurrence":
        second = replace(second, occurrence_id=first.occurrence_id)
    else:
        second = replace(
            second,
            raw_audit_reference=replace(first.raw_audit_reference, raw_audit_id="42"),
        )

    with pytest.raises(ValueError):
        InstrumentReferenceCandidate(
            provider_contract=_contract(exchanges=("SSE", "SZSE"), statuses=("L",)),
            crosswalk=_crosswalk(),
            occurrences=(first, second),
            records=(),
        )


def test_record_binds_exact_code_suffix_and_raw_occurrence() -> None:
    record = _record()

    assert record.ts_code == "600000.SH"
    assert record.source_market == "主板"
    assert record.source_list_status == "L"
    assert record.list_date == date(1999, 11, 10)
    assert record.delist_date is None
    assert record.source_observed_at is None
    assert record.source_available_at is None
    assert record.raw_audit_reference.raw_audit_id == "42"


def test_record_preserves_empty_raw_market_without_deriving_a_replacement() -> None:
    record = replace(_record(), source_market="")

    assert record.source_market == ""


def test_record_rejects_date_interpretation_that_differs_from_source_text() -> None:
    with pytest.raises(ValueError):
        replace(_record(), list_date_raw="20000101")


@pytest.mark.parametrize(
    "reference",
    [
        replace(_audit_ref(), raw_audit_id="not-a-database-id"),
        replace(_audit_ref(), run_id="caller-text"),
    ],
)
def test_occurrence_rejects_nonpersisted_or_nonowner_audit_identity(
    reference: RawAuditReference,
) -> None:
    with pytest.raises(ValueError):
        replace(_occurrence(), raw_audit_reference=reference)


@pytest.mark.parametrize(
    "field_values",
    [
        {"raw_payload_hash": 7},
        {"ts_code": 7},
    ],
)
def test_record_rejects_nontext_identity_hash_without_leaking_type_error(
    field_values: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "ts_code": "600000.SH",
        "name": "浦发银行",
        "source_exchange": "SSE",
        "source_market": "主板",
        "source_list_status": "L",
        "list_date_raw": "19991110",
        "list_date": date(1999, 11, 10),
        "delist_date_raw": None,
        "delist_date": None,
        "exchange_suffix": "SH",
        "occurrence_id": _occurrence().occurrence_id,
        "raw_audit_reference": _audit_ref(),
        "raw_payload_id": "payload-1",
        "raw_payload_hash": "sha256:" + "b" * 64,
    }
    values.update(field_values)

    with pytest.raises(ValueError):
        InstrumentReferenceRecord(**values)  # type: ignore[arg-type]


def test_occurrence_rejects_nontext_hash_without_leaking_type_error() -> None:
    values: dict[str, object] = {
        "occurrence_id": _occurrence().occurrence_id,
        "exchange": "SSE",
        "list_status": "L",
        "raw_audit_reference": _audit_ref(),
        "raw_payload_id": "payload-1",
        "raw_payload_hash": 7,
        "response_body_sha256": "c" * 64,
        "response_completed_at": datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
        "row_count": 1,
    }
    with pytest.raises(ValueError):
        InstrumentReferenceOccurrence(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"occurrence_id": cast(UUID, "not-a-uuid")},
        {"raw_audit_reference": cast(RawAuditReference, object())},
        {"raw_payload_hash": "sha256:bad"},
        {"response_body_sha256": "not-a-sha256"},
        {"row_count": -1},
        {"row_count": True},
        {"response_completed_at": datetime(2026, 10, 16, 1, 0)},
        {
            "response_completed_at": datetime(
                2026, 10, 16, 1, 0, tzinfo=timezone(timedelta(hours=8))
            )
        },
    ],
)
def test_occurrence_rejects_malformed_id_hash_count_or_clock(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(_occurrence(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"name": 7},
        {"source_market": cast(str, object())},
        {"list_date": cast(date, datetime(1999, 11, 10))},
        {"list_date_raw": 19991110},
        {"delist_date": cast(date, datetime(2000, 1, 1))},
        {"delist_date_raw": "20000101"},
        {"occurrence_id": cast(UUID, "not-a-uuid")},
        {"raw_audit_reference": cast(RawAuditReference, object())},
        {"raw_payload_hash": "sha256:bad"},
    ],
)
def test_record_rejects_malformed_preserved_values_and_provenance(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(_record(), **changes)


@pytest.mark.parametrize("source_date", ["2000-01-01", "20000230"])
def test_record_rejects_invalid_source_date_text(source_date: str) -> None:
    with pytest.raises(ValueError):
        replace(_record(), list_date_raw=source_date, list_date=None)


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_contract": cast(InstrumentReferenceProviderContract, object())},
        {"crosswalk": cast(InstrumentReferenceExchangeSuffixCrosswalk, object())},
        {"occurrences": (cast(InstrumentReferenceOccurrence, object()),)},
        {"records": (cast(InstrumentReferenceRecord, object()),)},
    ],
)
def test_candidate_rejects_invalid_contract_or_nested_item_types(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "provider_contract": _contract(exchanges=("SSE",), statuses=("L",)),
        "crosswalk": _crosswalk(),
        "occurrences": (_occurrence(),),
        "records": (_record(),),
    }
    values.update(changes)
    with pytest.raises(ValueError):
        InstrumentReferenceCandidate(**values)  # type: ignore[arg-type]


def test_candidate_rejects_record_from_another_occurrence() -> None:
    record = replace(_record(), occurrence_id=UUID("fa3f7e75-87b2-4e43-8744-93179fa94870"))
    with pytest.raises(ValueError):
        InstrumentReferenceCandidate(
            provider_contract=_contract(exchanges=("SSE",), statuses=("L",)),
            crosswalk=_crosswalk(),
            occurrences=(_occurrence(),),
            records=(record,),
        )


def test_audit_identity_rejects_noncanonical_but_parseable_uuid() -> None:
    reference = replace(
        _audit_ref(),
        run_id="0F84554D-6341-43F9-B4DD-1EAED9D39D00",
    )
    with pytest.raises(ValueError):
        replace(_occurrence(), raw_audit_reference=reference)
