"""Immutable instrument-reference snapshot and mapping domain contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceMappingContent,
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotError,
    make_instrument_reference_mapping_record,
    make_instrument_reference_snapshot_record,
    mapping_content_from_payload,
    snapshot_content_from_payload,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceCandidate,
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceOccurrence,
    InstrumentReferenceProviderContract,
    InstrumentReferenceRecord,
)

_RUN_ID = UUID("73f28f02-5b9a-4f2c-a6f8-aac2c4465ad1")
_BASE_TIME = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)


def _crosswalk() -> InstrumentReferenceExchangeSuffixCrosswalk:
    return InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture.stock-basic-suffix",
        crosswalk_version="fixture-v1",
        exchange_suffix_pairs=(("SSE", "SH"), ("SZSE", "SZ")),
    )


def _mapping() -> InstrumentReferenceMappingContent:
    return InstrumentReferenceMappingContent(
        mapping_id="fixture.instrument-reference-map",
        mapping_version="fixture-v1",
        source_crosswalk=_crosswalk(),
        exchange_rule_market_pairs=(("SSE", "FIXTURE_SSE"), ("SZSE", "FIXTURE_SZSE")),
        exchange_source_market_board_pairs=(
            ("SSE", "fixture-main", "FIXTURE_MAIN"),
            ("SSE", "fixture-other", "FIXTURE_OTHER"),
            ("SZSE", "fixture-growth", "FIXTURE_GROWTH"),
        ),
    )


def _candidate(
    *,
    round_number: int,
    run_id: UUID = _RUN_ID,
    source_market: str | None = "fixture-main",
    include_currency_field: bool = False,
    source_currency: str | None = None,
) -> InstrumentReferenceCandidate:
    fields = (
        "ts_code",
        "name",
        "exchange",
        "market",
        "list_status",
        "list_date",
        "delist_date",
    )
    if include_currency_field:
        fields += ("curr_type",)
    contract = InstrumentReferenceProviderContract(
        contract_id="fixture.stock-basic",
        contract_version="fixture-v1",
        provider_name="tushare",
        dataset_key="fixture.stock-basic",
        api_name="stock_basic",
        fields=fields,
        exchange_scope=("SSE",),
        list_status_scope=("L", "D"),
    )
    crosswalk = _crosswalk()
    listed_occurrence = InstrumentReferenceOccurrence(
        occurrence_id=UUID(int=round_number * 10 + 1),
        exchange="SSE",
        list_status="L",
        raw_audit_reference=RawAuditReference(
            raw_audit_id=str(round_number * 10 + 1),
            version="1",
            content_hash=f"{round_number:064x}",
            run_id=str(run_id),
            ingested_run_id="02ae71d1-76ef-4fb3-b21f-68a7476d9585",
        ),
        raw_payload_id=str(UUID(int=round_number * 10 + 1)),
        raw_payload_hash=f"sha256:{(round_number * 10 + 1):064x}",
        response_body_sha256=f"{(round_number * 10 + 1):064x}",
        response_completed_at=_BASE_TIME + timedelta(seconds=round_number * 2),
        row_count=1,
    )
    delisted_occurrence = InstrumentReferenceOccurrence(
        occurrence_id=UUID(int=round_number * 10 + 2),
        exchange="SSE",
        list_status="D",
        raw_audit_reference=RawAuditReference(
            raw_audit_id=str(round_number * 10 + 2),
            version="1",
            content_hash=f"{(round_number + 100):064x}",
            run_id=str(run_id),
            ingested_run_id="02ae71d1-76ef-4fb3-b21f-68a7476d9585",
        ),
        raw_payload_id=str(UUID(int=round_number * 10 + 2)),
        raw_payload_hash=f"sha256:{(round_number * 10 + 2):064x}",
        response_body_sha256=f"{(round_number * 10 + 2):064x}",
        response_completed_at=_BASE_TIME + timedelta(seconds=round_number * 2 + 1),
        row_count=0,
    )
    record = InstrumentReferenceRecord(
        ts_code="600000.SH",
        name="Fixture Bank",
        source_exchange="SSE",
        source_market=source_market,
        source_list_status="L",
        list_date_raw="20200102",
        list_date=date(2020, 1, 2),
        delist_date_raw="",
        delist_date=None,
        exchange_suffix="SH",
        occurrence_id=listed_occurrence.occurrence_id,
        raw_audit_reference=listed_occurrence.raw_audit_reference,
        raw_payload_id=listed_occurrence.raw_payload_id,
        raw_payload_hash=listed_occurrence.raw_payload_hash,
        source_currency=source_currency,
    )
    return InstrumentReferenceCandidate(
        provider_contract=contract,
        crosswalk=crosswalk,
        occurrences=(listed_occurrence, delisted_occurrence),
        records=(record,),
    )


def _persistable_content(
    *,
    source_market: str | None = "fixture-main",
    include_currency_field: bool = False,
    source_currency: str | None = None,
) -> tuple[
    InstrumentReferenceMappingContent,
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotContent,
]:
    mapping_content = _mapping()
    mapping_record = make_instrument_reference_mapping_record(
        mapping_content,
        mapping_record_id=UUID("3ac6010a-a132-4d80-a626-cc07fc3715c4"),
        recorded_at=_BASE_TIME + timedelta(seconds=1),
    )
    content = InstrumentReferenceSnapshotContent(
        run_id=_RUN_ID,
        mapping_record=mapping_record,
        fetch_rounds=(
            InstrumentReferenceFetchRound(
                fetch_round_id=UUID("a0eb3395-8818-4c0a-9f47-4ee7f833c452"),
                candidate=_candidate(
                    round_number=1,
                    source_market=source_market,
                    include_currency_field=include_currency_field,
                    source_currency=source_currency,
                ),
            ),
            InstrumentReferenceFetchRound(
                fetch_round_id=UUID("15908d64-355e-4bf6-80e1-317bb911c69f"),
                candidate=_candidate(
                    round_number=2,
                    source_market=source_market,
                    include_currency_field=include_currency_field,
                    source_currency=source_currency,
                ),
            ),
        ),
    )
    return mapping_content, mapping_record, content


def _first_record_payload(payload: dict[str, object]) -> dict[str, object]:
    """Narrow the first record in a public snapshot payload for assertions."""

    rounds = payload["fetch_rounds"]
    assert isinstance(rounds, list) and rounds
    fetch_round = rounds[0]
    assert isinstance(fetch_round, dict)
    candidate = fetch_round["candidate"]
    assert isinstance(candidate, dict)
    records = candidate["records"]
    assert isinstance(records, list) and records
    record = records[0]
    assert isinstance(record, dict)
    return record


def test_mapping_content_binds_source_crosswalk_without_conflating_hashes() -> None:
    mapping = _mapping()

    assert mapping.source_crosswalk_id == "fixture.stock-basic-suffix"
    assert mapping.source_crosswalk_version == "fixture-v1"
    assert mapping.source_crosswalk_hash == _crosswalk().content_hash
    assert mapping.source_crosswalk_hash != mapping.content_hash
    assert mapping.rule_market_for("SSE") == "FIXTURE_SSE"
    assert mapping.board_for("SSE", "fixture-main") == "FIXTURE_MAIN"
    assert mapping.board_for("SSE", None) is None
    assert mapping.board_for("SZSE", "fixture-main") is None


def test_snapshot_preserves_empty_scope_and_same_run_fetch_rounds() -> None:
    _mapping_content, mapping_record, content = _persistable_content()

    assert content.run_id == _RUN_ID
    assert len(content.fetch_rounds) == 2
    assert content.occurrence_count == 4
    assert content.record_count == 2
    assert content.empty_occurrence_count == 2
    assert content.fetch_rounds[0].fetch_round_id != content.fetch_rounds[1].fetch_round_id
    assert content.fetch_rounds[0].candidate.occurrences[0].raw_audit_reference.raw_audit_id != (
        content.fetch_rounds[1].candidate.occurrences[0].raw_audit_reference.raw_audit_id
    )
    assert mapping_record.recorded_at <= content.last_response_completed_at
    assert content.source_observed_at is None
    assert content.source_available_at is None
    assert content.must_not_use_for_decision is True
    assert content.must_not_execute is True
    assert content.content_hash == (
        "sha256:2eb729da4a0a9b9487355d1c3894ee21bfab0f6b528fa68d8f31b085c2d1f39b"
    )
    payload_bytes = json.dumps(
        content.to_payload(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    assert hashlib.sha256(payload_bytes).hexdigest() == content.content_hash.removeprefix("sha256:")
    rebuilt = snapshot_content_from_payload(content.to_payload(), mapping_record=mapping_record)
    assert rebuilt == content
    assert rebuilt.content_hash == content.content_hash


@pytest.mark.parametrize("source_currency", [None, "", "usd"])
def test_currency_requested_snapshot_preserves_null_empty_and_raw_text(
    source_currency: str | None,
) -> None:
    _mapping_content, mapping_record, content = _persistable_content(
        include_currency_field=True,
        source_currency=source_currency,
    )
    payload = content.to_payload()
    rounds = payload["fetch_rounds"]
    assert isinstance(rounds, list)
    for fetch_round in rounds:
        assert isinstance(fetch_round, dict)
        candidate = fetch_round["candidate"]
        assert isinstance(candidate, dict)
        contract = candidate["provider_contract"]
        assert isinstance(contract, dict)
        assert contract["fields"] == [
            "ts_code",
            "name",
            "exchange",
            "market",
            "list_status",
            "list_date",
            "delist_date",
            "curr_type",
        ]
        records = candidate["records"]
        assert isinstance(records, list)
        record = records[0]
        assert isinstance(record, dict)
        assert record["source_currency"] == source_currency

    rebuilt = snapshot_content_from_payload(payload, mapping_record=mapping_record)
    classification = rebuilt.classify_security("600000.SH")

    assert rebuilt == content
    assert classification is not None
    assert classification.source_currency == source_currency


def test_currency_value_is_bound_by_snapshot_content_hash() -> None:
    _mapping_content, _mapping_record, cny = _persistable_content(
        include_currency_field=True,
        source_currency="CNY",
    )
    _mapping_content, _mapping_record, usd = _persistable_content(
        include_currency_field=True,
        source_currency="USD",
    )

    assert cny.content_hash != usd.content_hash


def test_currency_payload_requires_exact_contract_dependent_record_fields() -> None:
    _mapping_content, mapping_record, legacy_content = _persistable_content()
    legacy_payload = legacy_content.to_payload()
    legacy_record = _first_record_payload(legacy_payload)
    legacy_record["source_currency"] = "CNY"
    with pytest.raises(InstrumentReferenceSnapshotError):
        snapshot_content_from_payload(legacy_payload, mapping_record=mapping_record)

    _mapping_content, currency_mapping_record, currency_content = _persistable_content(
        include_currency_field=True,
        source_currency=None,
    )
    currency_payload = currency_content.to_payload()
    currency_record = _first_record_payload(currency_payload)
    del currency_record["source_currency"]
    with pytest.raises(InstrumentReferenceSnapshotError):
        snapshot_content_from_payload(currency_payload, mapping_record=currency_mapping_record)

    currency_payload = currency_content.to_payload()
    currency_record = _first_record_payload(currency_payload)
    currency_record["source_currency"] = 42
    with pytest.raises(InstrumentReferenceSnapshotError):
        snapshot_content_from_payload(currency_payload, mapping_record=currency_mapping_record)


@pytest.mark.parametrize(
    "currencies",
    [("CNY", "USD"), ("USD", "CNY"), (None, "CNY"), ("CNY", None)],
)
@pytest.mark.parametrize("reverse_rounds", [False, True])
def test_currency_difference_between_fetch_rounds_blocks_classification_without_selecting_one(
    currencies: tuple[str | None, str | None],
    reverse_rounds: bool,
) -> None:
    _mapping_content, mapping_record, content = _persistable_content(
        include_currency_field=True,
        source_currency="CNY",
    )
    rounds = tuple(
        replace(
            fetch_round,
            candidate=replace(
                fetch_round.candidate,
                records=(
                    replace(
                        fetch_round.candidate.records[0],
                        source_currency=currencies[index],
                    ),
                ),
            ),
        )
        for index, fetch_round in enumerate(content.fetch_rounds)
    )
    if reverse_rounds:
        rounds = tuple(reversed(rounds))
    conflicting_content = replace(
        content,
        fetch_rounds=rounds,
    )

    classification = conflicting_content.classify_security("600000.SH")

    assert classification is not None
    assert classification.blocked_reason == "INSTRUMENT_REFERENCE_CLASSIFICATION_AMBIGUOUS"
    assert classification.source_currency is None
    assert classification.board is None


def test_snapshot_seal_binds_database_identity_and_first_knowledge_time() -> None:
    _mapping_content, mapping_record, content = _persistable_content()
    snapshot_id = UUID("4d590a6c-2d4a-41ad-b046-abec4cf21d2a")
    recorded_at = _BASE_TIME + timedelta(seconds=20)
    snapshot = make_instrument_reference_snapshot_record(
        content,
        snapshot_id=snapshot_id,
        recorded_at=recorded_at,
    )

    assert snapshot.content_hash == content.content_hash
    assert snapshot.record_digest.startswith("sha256:")
    assert snapshot.recorded_at == recorded_at
    assert snapshot.mapping_record.record_digest == mapping_record.record_digest
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(snapshot, recorded_at=recorded_at - timedelta(seconds=1))
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(snapshot, snapshot_id=uuid4())
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(snapshot, snapshot_id="not-a-uuid")
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(snapshot, content_hash="sha256:" + "0" * 64)


def test_mapping_timestamp_tampering_invalidates_its_record_seal() -> None:
    mapping_content = _mapping()
    record = make_instrument_reference_mapping_record(
        mapping_content,
        mapping_record_id=UUID("3ac6010a-a132-4d80-a626-cc07fc3715c4"),
        recorded_at=_BASE_TIME + timedelta(seconds=10),
    )

    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(record, recorded_at=record.recorded_at - timedelta(seconds=1))


def test_unmapped_market_is_preserved_but_not_board_classified() -> None:
    _mapping_content, mapping_record, content = _persistable_content(source_market="unknown-market")

    classification = content.classify(content.fetch_rounds[0].candidate.records[0])
    assert classification.source_market == "unknown-market"
    assert classification.rule_market == "FIXTURE_SSE"
    assert classification.board is None
    assert classification.blocked_reason == "INSTRUMENT_REFERENCE_BOARD_MAPPING_UNKNOWN"
    assert content.board_classification_complete is False
    assert mapping_record.content.source_crosswalk_hash == _crosswalk().content_hash


def test_source_candidate_suffix_crosswalk_must_match_exact_mapping_identity() -> None:
    _mapping_content, mapping_record, content = _persistable_content()
    altered = replace(
        mapping_record.content,
        source_crosswalk=InstrumentReferenceExchangeSuffixCrosswalk(
            crosswalk_id="different-crosswalk",
            crosswalk_version="fixture-v1",
            exchange_suffix_pairs=(("SSE", "SH"), ("SZSE", "SZ")),
        ),
    )
    altered_record = make_instrument_reference_mapping_record(
        altered,
        mapping_record_id=mapping_record.mapping_record_id,
        recorded_at=mapping_record.recorded_at,
    )
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(content, mapping_record=altered_record)


def test_snapshot_content_rejects_a_caller_backdated_mapping_receipt() -> None:
    mapping_content, _mapping_record, _content = _persistable_content()
    later_mapping = make_instrument_reference_mapping_record(
        mapping_content,
        mapping_record_id=UUID("3ac6010a-a132-4d80-a626-cc07fc3715c4"),
        recorded_at=_BASE_TIME + timedelta(seconds=60),
    )
    content = InstrumentReferenceSnapshotContent(
        run_id=_RUN_ID,
        mapping_record=later_mapping,
        fetch_rounds=(
            InstrumentReferenceFetchRound(
                fetch_round_id=UUID("a0eb3395-8818-4c0a-9f47-4ee7f833c452"),
                candidate=_candidate(round_number=1),
            ),
        ),
    )
    with pytest.raises(InstrumentReferenceSnapshotError):
        make_instrument_reference_snapshot_record(
            content,
            snapshot_id=UUID("4d590a6c-2d4a-41ad-b046-abec4cf21d2a"),
            recorded_at=_BASE_TIME + timedelta(seconds=20),
        )


def test_mapping_rejects_mutable_or_ambiguous_tuple_backing() -> None:
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceMappingContent(
            mapping_id="fixture.map",
            mapping_version="fixture-v1",
            source_crosswalk=_crosswalk(),
            exchange_rule_market_pairs=[("SSE", "FIXTURE_SSE")],  # type: ignore[arg-type]
            exchange_source_market_board_pairs=(("SSE", "fixture-main", "FIXTURE_MAIN"),),
        )


def test_mapping_rejects_bad_identity_rows_and_noncanonical_shapes() -> None:
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceMappingContent(
            mapping_id="fixture.map",
            mapping_version="fixture-v1",
            source_crosswalk=object(),  # type: ignore[arg-type]
            exchange_rule_market_pairs=(("SSE", "FIXTURE_SSE"),),
            exchange_source_market_board_pairs=(("SSE", "fixture-main", "FIXTURE_MAIN"),),
        )
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceMappingContent(
            mapping_id="fixture.map",
            mapping_version="fixture-v1",
            source_crosswalk=_crosswalk(),
            exchange_rule_market_pairs=(),
            exchange_source_market_board_pairs=(("SSE", "fixture-main", "FIXTURE_MAIN"),),
        )
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceMappingContent(
            mapping_id="fixture.map",
            mapping_version="fixture-v1",
            source_crosswalk=_crosswalk(),
            exchange_rule_market_pairs=(("SSE", "FIXTURE_SSE"),),
            exchange_source_market_board_pairs=(
                ("SSE", "fixture-main", "FIXTURE_MAIN"),
                ("SSE", "fixture-main", "FIXTURE_OTHER"),
            ),
        )
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceMappingContent(
            mapping_id="fixture.map",
            mapping_version="fixture-v1",
            source_crosswalk=_crosswalk(),
            exchange_rule_market_pairs=(("OTHER", "FIXTURE_OTHER"),),
            exchange_source_market_board_pairs=(("SSE", "fixture-main", "FIXTURE_MAIN"),),
        )
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceMappingContent(
            mapping_id="fixture.map",
            mapping_version="fixture-v1",
            source_crosswalk=_crosswalk(),
            exchange_rule_market_pairs=(("SSE", "FIXTURE_SSE"),),
            exchange_source_market_board_pairs=(("OTHER", "fixture-main", "FIXTURE_MAIN"),),
        )
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceMappingContent(
            mapping_id="fixture.map",
            mapping_version="fixture-v1",
            source_crosswalk=_crosswalk(),
            exchange_rule_market_pairs=(("SSE",),),  # type: ignore[arg-type]
            exchange_source_market_board_pairs=(("SSE", "fixture-main", "FIXTURE_MAIN"),),
        )
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceMappingContent(
            mapping_id="fixture.map",
            mapping_version="fixture-v1",
            source_crosswalk=_crosswalk(),
            exchange_rule_market_pairs=(("SSE", " FIXTURE_SSE"),),
            exchange_source_market_board_pairs=(("SSE", "fixture-main", "FIXTURE_MAIN"),),
        )


def test_mapping_payload_decoder_rejects_unknown_shapes_and_hash_changes() -> None:
    _mapping_record, mapping_record, _content = _persistable_content()
    payload = mapping_record.content.to_payload()
    assert mapping_content_from_payload(payload) == mapping_record.content

    wrong_schema = dict(payload)
    wrong_schema["schema"] = "instrument-reference-mapping.v2"
    with pytest.raises(InstrumentReferenceSnapshotError):
        mapping_content_from_payload(wrong_schema)
    changed_crosswalk = json.loads(json.dumps(payload))
    changed_crosswalk["source_crosswalk"]["content_hash"] = "sha256:" + "0" * 64
    with pytest.raises(InstrumentReferenceSnapshotError):
        mapping_content_from_payload(changed_crosswalk)
    malformed_pair = json.loads(json.dumps(payload))
    malformed_pair["exchange_rule_market_pairs"] = [["SSE"]]
    with pytest.raises(InstrumentReferenceSnapshotError):
        mapping_content_from_payload(malformed_pair)
    mutable_container = dict(payload)
    mutable_container["unexpected"] = True
    with pytest.raises(InstrumentReferenceSnapshotError):
        mapping_content_from_payload(mutable_container)
    wrong_crosswalk_shape = json.loads(json.dumps(payload))
    wrong_crosswalk_shape["source_crosswalk"]["unexpected"] = True
    with pytest.raises(InstrumentReferenceSnapshotError):
        mapping_content_from_payload(wrong_crosswalk_shape)
    non_list_rows = json.loads(json.dumps(payload))
    non_list_rows["exchange_rule_market_pairs"] = (("SSE", "FIXTURE_SSE"),)
    with pytest.raises(InstrumentReferenceSnapshotError):
        mapping_content_from_payload(non_list_rows)
    malformed_board_row = json.loads(json.dumps(payload))
    malformed_board_row["exchange_source_market_board_pairs"][0] = ["SSE", "fixture-main"]
    with pytest.raises(InstrumentReferenceSnapshotError):
        mapping_content_from_payload(malformed_board_row)


def test_mapping_record_checks_digest_time_and_identity_types() -> None:
    content = _mapping()
    record = make_instrument_reference_mapping_record(
        content,
        mapping_record_id=UUID("3ac6010a-a132-4d80-a626-cc07fc3715c4"),
        recorded_at=_BASE_TIME + timedelta(seconds=10),
    )
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(record, content_hash="sha256:" + "0" * 64)
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(record, record_digest="not-a-digest")
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(record, record_digest="sha256:" + "0" * 64)
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(record, recorded_at=_BASE_TIME.replace(tzinfo=None))
    with pytest.raises(InstrumentReferenceSnapshotError):
        make_instrument_reference_mapping_record(
            content,
            mapping_record_id=record.mapping_record_id,
            recorded_at=datetime(2026, 10, 16, 20, tzinfo=timezone(timedelta(hours=8))),
        )
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(record, mapping_record_id="not-a-uuid")
    assert record.source_crosswalk_hash == content.source_crosswalk_hash
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceMappingContent(
            mapping_id="invalid space",
            mapping_version="fixture-v1",
            source_crosswalk=_crosswalk(),
            exchange_rule_market_pairs=(("SSE", "FIXTURE_SSE"),),
            exchange_source_market_board_pairs=(("SSE", "fixture-main", "FIXTURE_MAIN"),),
        )


def test_snapshot_round_and_content_constructor_reject_invalid_and_duplicate_identity() -> None:
    _mapping_content, mapping_record, content = _persistable_content()
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceFetchRound(fetch_round_id="bad", candidate=content.fetch_rounds[0].candidate)  # type: ignore[arg-type]
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceSnapshotContent(
            run_id=_RUN_ID,
            mapping_record=mapping_record,
            fetch_rounds=[],  # type: ignore[arg-type]
        )
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceSnapshotContent(
            run_id=_RUN_ID,
            mapping_record=mapping_record,
            fetch_rounds=(content.fetch_rounds[0], content.fetch_rounds[0]),
        )
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceSnapshotContent(
            run_id="not-a-uuid",  # type: ignore[arg-type]
            mapping_record=mapping_record,
            fetch_rounds=(content.fetch_rounds[0],),
        )
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceSnapshotContent(
            run_id=_RUN_ID,
            mapping_record=mapping_record,
            fetch_rounds=(object(),),  # type: ignore[arg-type]
        )
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceSnapshotContent(
            run_id=_RUN_ID,
            mapping_record=object(),  # type: ignore[arg-type]
            fetch_rounds=(content.fetch_rounds[0],),
        )
    assert content.classify_security("missing.SH") is None
    with pytest.raises(InstrumentReferenceSnapshotError):
        content.classify_security(None)  # type: ignore[arg-type]
    with pytest.raises(InstrumentReferenceSnapshotError):
        content.classify(object())  # type: ignore[arg-type]


def test_snapshot_content_rejects_duplicate_occurrences_audits_and_contracts() -> None:
    _mapping_content, mapping_record, content = _persistable_content()
    first, second = content.fetch_rounds
    candidate_a = first.candidate
    candidate_b = second.candidate
    duplicate_occurrence_candidate = replace(
        candidate_b,
        occurrences=(candidate_a.occurrences[0], candidate_b.occurrences[1]),
        records=(
            replace(
                candidate_b.records[0],
                occurrence_id=candidate_a.occurrences[0].occurrence_id,
                raw_audit_reference=candidate_a.occurrences[0].raw_audit_reference,
                raw_payload_id=candidate_a.occurrences[0].raw_payload_id,
                raw_payload_hash=candidate_a.occurrences[0].raw_payload_hash,
            ),
        ),
    )
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(
            content, fetch_rounds=(first, replace(second, candidate=duplicate_occurrence_candidate))
        )

    duplicate_audit_occurrence = replace(
        candidate_b.occurrences[0],
        raw_audit_reference=candidate_a.occurrences[0].raw_audit_reference,
    )
    duplicate_audit_candidate = replace(
        candidate_b,
        occurrences=(duplicate_audit_occurrence, candidate_b.occurrences[1]),
        records=(
            replace(
                candidate_b.records[0],
                raw_audit_reference=duplicate_audit_occurrence.raw_audit_reference,
            ),
        ),
    )
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(content, fetch_rounds=(first, replace(second, candidate=duplicate_audit_candidate)))

    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceSnapshotContent(
            run_id=_RUN_ID,
            mapping_record=mapping_record,
            fetch_rounds=(
                InstrumentReferenceFetchRound(
                    fetch_round_id=first.fetch_round_id,
                    candidate=_candidate(round_number=7, run_id=uuid4()),
                ),
            ),
        )

    other_contract = replace(candidate_b.provider_contract, contract_version="fixture-v2")
    mixed_contract_candidate = replace(candidate_b, provider_contract=other_contract)
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(content, fetch_rounds=(first, replace(second, candidate=mixed_contract_candidate)))


def test_snapshot_content_rejects_different_crosswalk_identity_and_code_suffix() -> None:
    _mapping_content, mapping_record, content = _persistable_content()
    first, second = content.fetch_rounds
    other_crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="different-crosswalk",
        crosswalk_version="fixture-v1",
        exchange_suffix_pairs=(("SSE", "SH"), ("SZSE", "SZ")),
    )
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(
            content,
            fetch_rounds=(
                first,
                replace(second, candidate=replace(second.candidate, crosswalk=other_crosswalk)),
            ),
        )

    conflicting = replace(
        second.candidate.records[0],
        ts_code=first.candidate.records[0].ts_code,
        source_exchange="SZSE",
        exchange_suffix="SZ",
    )
    conflicting_candidate = object.__new__(InstrumentReferenceCandidate)
    object.__setattr__(
        conflicting_candidate, "provider_contract", second.candidate.provider_contract
    )
    object.__setattr__(conflicting_candidate, "crosswalk", second.candidate.crosswalk)
    object.__setattr__(conflicting_candidate, "occurrences", second.candidate.occurrences)
    object.__setattr__(conflicting_candidate, "records", (conflicting,))
    # Exercise the snapshot's defensive check if an already-built frozen candidate is corrupted.
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(content, fetch_rounds=(first, replace(second, candidate=conflicting_candidate)))

    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(content, mapping_record=object())  # type: ignore[arg-type]
    assert mapping_record.record_digest


def test_explicit_mapping_classification_blocks_unknown_exact_code_and_market() -> None:
    _mapping_content, mapping_record, content = _persistable_content()
    assert content.board_classification_complete is True
    assert content.classify_security("600000.sh") is None
    assert _mapping().rule_market_for("UNKNOWN") is None

    no_rule_market = InstrumentReferenceMappingContent(
        mapping_id="fixture.only-sz-market",
        mapping_version="fixture-v1",
        source_crosswalk=_crosswalk(),
        exchange_rule_market_pairs=(("SZSE", "FIXTURE_SZSE"),),
        exchange_source_market_board_pairs=(("SSE", "fixture-main", "FIXTURE_MAIN"),),
    )
    alternate_record = make_instrument_reference_mapping_record(
        no_rule_market,
        mapping_record_id=UUID("696b68e3-c34c-49ad-bdb5-0e8e3de0d889"),
        recorded_at=_BASE_TIME + timedelta(seconds=1),
    )
    no_market_content = replace(content, mapping_record=alternate_record)
    assert no_market_content.classify(
        no_market_content.fetch_rounds[0].candidate.records[0]
    ).blocked_reason == ("INSTRUMENT_REFERENCE_RULE_MARKET_MAPPING_UNKNOWN")
    with pytest.raises(InstrumentReferenceSnapshotError):
        no_market_content.classify_security(123)  # type: ignore[arg-type]
    assert mapping_record.content_hash != alternate_record.content_hash
    assert content.blocked_reason == "INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY"


def test_snapshot_payload_decoder_rejects_malformed_hashes_dates_times_and_numbers() -> None:
    _mapping_content, mapping_record, content = _persistable_content()

    def rejected(mutator: object) -> None:
        payload = json.loads(json.dumps(content.to_payload()))
        assert callable(mutator)
        mutator(payload)
        with pytest.raises(InstrumentReferenceSnapshotError):
            snapshot_content_from_payload(payload, mapping_record=mapping_record)

    rejected(lambda payload: payload.update(schema="wrong"))
    rejected(lambda payload: payload["mapping"].update(content_hash="wrong"))
    rejected(lambda payload: payload.update(fetch_rounds=None))
    rejected(lambda payload: payload.update(run_id="not-a-uuid"))
    rejected(lambda payload: payload["fetch_rounds"][0]["candidate"].update(records=None))
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["provider_contract"].update(
            content_hash="sha256:" + "0" * 64
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["crosswalk"].update(
            content_hash="sha256:" + "0" * 64
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["records"][0].update(
            source_market=42
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["records"][0].update(
            list_date="2020-1-2"
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["records"][0].update(list_date=42)
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["records"][0].update(
            list_date="20200102"
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["records"][0].update(
            list_date_raw=42
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["records"][0].update(
            occurrence_id="ABC"
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["occurrences"][0].update(
            occurrence_id=123
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["occurrences"][0].update(
            occurrence_id=str(_RUN_ID).upper()
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["occurrences"][0].update(
            row_count=True
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["occurrences"][0].update(
            response_completed_at="not-a-time"
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["occurrences"][0].update(
            response_completed_at="invalidZ"
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["occurrences"][0].update(
            response_completed_at="2026-10-16T04:00:00+00:00"
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["occurrences"][0].update(
            response_completed_at="2026-10-16T04:00:03.000000Z"
        )
    )
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["records"][0].update(
            raw_audit_reference={"raw_audit_id": "missing"}
        )
    )
    unknown_date_payload = json.loads(json.dumps(content.to_payload()))
    unknown_date_payload["fetch_rounds"][0]["candidate"]["records"][0].update(
        list_date_raw=None, list_date=None
    )
    unknown_date_content = snapshot_content_from_payload(
        unknown_date_payload, mapping_record=mapping_record
    )
    assert unknown_date_content.fetch_rounds[0].candidate.records[0].list_date_raw is None
    assert unknown_date_content.fetch_rounds[0].candidate.records[0].list_date is None
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["occurrences"][0][
            "raw_audit_reference"
        ].update(raw_audit_id=42)
    )
    rejected(lambda payload: payload["fetch_rounds"][0]["candidate"]["records"][0].update(name=42))
    rejected(
        lambda payload: payload["fetch_rounds"][0]["candidate"]["provider_contract"].update(
            fields=["ts_code", 42]
        )
    )


def test_snapshot_record_rejects_capture_and_mapping_time_backdating() -> None:
    mapping_content, _mapping_record, content = _persistable_content()
    snapshot_id = UUID("4d590a6c-2d4a-41ad-b046-abec4cf21d2a")
    with pytest.raises(InstrumentReferenceSnapshotError):
        make_instrument_reference_snapshot_record(
            content,
            snapshot_id=snapshot_id,
            recorded_at=content.last_response_completed_at - timedelta(seconds=1),
        )
    valid_record = make_instrument_reference_snapshot_record(
        content,
        snapshot_id=snapshot_id,
        recorded_at=content.last_response_completed_at + timedelta(seconds=10),
    )
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(
            valid_record,
            recorded_at=content.last_response_completed_at - timedelta(seconds=1),
        )

    delayed_mapping = make_instrument_reference_mapping_record(
        mapping_content,
        mapping_record_id=UUID("696b68e3-c34c-49ad-bdb5-0e8e3de0d889"),
        recorded_at=content.last_response_completed_at + timedelta(seconds=5),
    )
    delayed_content = replace(content, mapping_record=delayed_mapping)
    with pytest.raises(InstrumentReferenceSnapshotError):
        make_instrument_reference_snapshot_record(
            delayed_content,
            snapshot_id=snapshot_id,
            recorded_at=delayed_content.last_response_completed_at + timedelta(seconds=1),
        )
    delayed_snapshot = make_instrument_reference_snapshot_record(
        delayed_content,
        snapshot_id=snapshot_id,
        recorded_at=delayed_mapping.recorded_at + timedelta(seconds=1),
    )
    with pytest.raises(InstrumentReferenceSnapshotError):
        replace(
            delayed_snapshot,
            recorded_at=delayed_content.last_response_completed_at + timedelta(seconds=1),
        )
    with pytest.raises(InstrumentReferenceSnapshotError):
        InstrumentReferenceMappingContent(
            mapping_id="fixture.map",
            mapping_version="fixture-v1",
            source_crosswalk=_crosswalk(),
            exchange_rule_market_pairs=(("SSE", "M1"), ("SSE", "M2")),
            exchange_source_market_board_pairs=(("SSE", "fixture-main", "FIXTURE_MAIN"),),
        )


def test_persisted_payload_rejects_extra_fields_and_dropped_empty_occurrence() -> None:
    _mapping_content, mapping_record, content = _persistable_content()
    extra_field = content.to_payload()
    extra_field["unreviewed"] = True
    with pytest.raises(InstrumentReferenceSnapshotError):
        snapshot_content_from_payload(extra_field, mapping_record=mapping_record)
    missing_empty_scope = content.to_payload()
    rounds = missing_empty_scope["fetch_rounds"]
    assert isinstance(rounds, list)
    first_candidate = rounds[0]["candidate"]
    assert isinstance(first_candidate, dict)
    occurrences = first_candidate["occurrences"]
    assert isinstance(occurrences, list)
    occurrences.pop()
    with pytest.raises(InstrumentReferenceSnapshotError):
        snapshot_content_from_payload(missing_empty_scope, mapping_record=mapping_record)


def test_same_security_with_changed_market_keeps_shared_currency_but_classification_blocks() -> (
    None
):
    mapping_content, mapping_record, _content = _persistable_content(
        include_currency_field=True,
        source_currency="CNY",
    )
    content = InstrumentReferenceSnapshotContent(
        run_id=_RUN_ID,
        mapping_record=mapping_record,
        fetch_rounds=(
            InstrumentReferenceFetchRound(
                fetch_round_id=UUID("a0eb3395-8818-4c0a-9f47-4ee7f833c452"),
                candidate=_candidate(
                    round_number=1,
                    source_market="fixture-main",
                    include_currency_field=True,
                    source_currency="CNY",
                ),
            ),
            InstrumentReferenceFetchRound(
                fetch_round_id=UUID("15908d64-355e-4bf6-80e1-317bb911c69f"),
                candidate=_candidate(
                    round_number=2,
                    source_market="fixture-other",
                    include_currency_field=True,
                    source_currency="CNY",
                ),
            ),
        ),
    )

    classification = content.classify_security("600000.SH")

    assert classification is not None
    assert classification.blocked_reason == "INSTRUMENT_REFERENCE_CLASSIFICATION_AMBIGUOUS"
    assert classification.source_currency == "CNY"
    assert classification.board is None
    assert content.board_classification_complete is False
    assert mapping_content.board_for("SSE", "fixture-other") == "FIXTURE_OTHER"


def test_unknown_dates_remain_null_and_outside_records_cannot_be_classified() -> None:
    _mapping_content, _mapping_record, content = _persistable_content()
    first_round = content.fetch_rounds[0]
    original = first_round.candidate.records[0]
    unknown_date_record = replace(original, list_date_raw="", list_date=None)
    changed_candidate = replace(first_round.candidate, records=(unknown_date_record,))
    changed_round = replace(first_round, candidate=changed_candidate)
    changed_content = replace(
        content,
        fetch_rounds=(changed_round, content.fetch_rounds[1]),
    )
    classified = changed_content.classify(unknown_date_record)
    assert classified.list_date is None
    with pytest.raises(InstrumentReferenceSnapshotError):
        content.classify(replace(original, name="not-an-exact-member"))


def test_several_thousand_records_roundtrip_as_one_complete_snapshot_payload() -> None:
    mapping_content = _mapping()
    mapping_record = make_instrument_reference_mapping_record(
        mapping_content,
        mapping_record_id=UUID("3ac6010a-a132-4d80-a626-cc07fc3715c4"),
        recorded_at=_BASE_TIME + timedelta(seconds=1),
    )
    candidate = _candidate(round_number=13)
    occurrences = list(candidate.occurrences)
    occurrences[0] = replace(occurrences[0], row_count=3000)
    base_record = candidate.records[0]
    records = tuple(
        replace(base_record, ts_code=f"{index:06d}.SH", name=f"Fixture {index}")
        for index in range(3000)
    )
    large_candidate = replace(candidate, occurrences=tuple(occurrences), records=records)
    content = InstrumentReferenceSnapshotContent(
        run_id=_RUN_ID,
        mapping_record=mapping_record,
        fetch_rounds=(
            InstrumentReferenceFetchRound(
                fetch_round_id=UUID("a0eb3395-8818-4c0a-9f47-4ee7f833c452"),
                candidate=large_candidate,
            ),
        ),
    )
    payload_bytes = len(json.dumps(content.to_payload(), ensure_ascii=True).encode("ascii"))
    rebuilt = snapshot_content_from_payload(content.to_payload(), mapping_record=mapping_record)

    assert content.record_count == 3000
    assert payload_bytes > 3000
    assert rebuilt == content
    assert rebuilt.classify_security("002999.SH") is not None
