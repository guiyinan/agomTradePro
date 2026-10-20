from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest

from apps.data_center.domain.exchange_calendar import (
    exchange_calendar_request_scope_hash,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    CalendarPublicationReference,
    ExchangeCalendarDay,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    RawCalendarReference,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
    SimulatedSettlementContractError,
)
from apps.simulated_trading.domain.order_reservation_fill_release import (
    OrderFillSettlementReleaseProof,
)
from apps.simulated_trading.infrastructure import order_reservation_fill_calendar_codec
from apps.simulated_trading.infrastructure.order_reservation_fill_release_codec import (
    decode_order_fill_settlement_release_proof,
    encode_order_fill_settlement_release_proof,
)

_FILL_SESSION = date(2026, 10, 19)
_RELEASE_SESSION = date(2026, 10, 20)
_RELEASED_AT = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)


def _calendar_evidence(
    *,
    closed_dates: frozenset[date] = frozenset({date(2026, 10, 24)}),
    source_published_at: datetime | None = datetime(2026, 10, 16, 1, 30, tzinfo=UTC),
    snapshot_recorded_at: datetime = datetime(2026, 10, 16, 1, 50, tzinfo=UTC),
    published_at: datetime = datetime(2026, 10, 16, 1, 55, tzinfo=UTC),
    publication_recorded_at: datetime = datetime(2026, 10, 16, 1, 56, tzinfo=UTC),
) -> ExecutionCalendarEvidence:
    dates = tuple(date(2026, 10, 19) + timedelta(days=offset) for offset in range(6))
    previous_open = date(2026, 10, 16)
    day_rows: list[ExchangeCalendarDay] = []
    for session in dates:
        is_open = session not in closed_dates
        day_rows.append(
            ExchangeCalendarDay(
                exchange="SH",
                calendar_date=session,
                is_open=is_open,
                previous_open_date=previous_open,
            )
        )
        if is_open:
            previous_open = session
    rows = tuple(day_rows)
    response_completed_at = datetime(2026, 10, 16, 1, 40, tzinfo=UTC)
    raw_reference = RawCalendarReference(
        payload_id="0f53f9d5-7bc6-4b87-8e16-f5840aa5b301",
        payload_hash="sha256:" + "c" * 64,
        record_digest="sha256:" + "d" * 64,
        body_sha256="e" * 64,
        retained_content_sha256="e" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(
            "SH",
            dates[0],
            dates[-1],
        ),
        original_body_retained=True,
        response_completed_at=response_completed_at,
        provider_name="fixture-provider",
        dataset_key="trade_cal",
        transport="direct",
    )
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id="f418fc8b-8843-4cd8-9693-95b67834827b",
        exchange="SH",
        coverage_start=dates[0],
        coverage_end=dates[-1],
        days=rows,
        provider_name="fixture-provider",
        raw_reference=raw_reference,
        content_hash="",
        record_digest="",
        first_seen_at=response_completed_at,
        recorded_at=snapshot_recorded_at,
        source_published_at=source_published_at,
    )
    publication = CalendarPublicationReference(
        publication_id="calendar-publication-202610",
        member_id=snapshot.snapshot_id,
        publication_hash="2" * 64,
        fact_content_hash="4" * 64,
        policy_hash="3" * 64,
        published_at=published_at,
        recorded_at=publication_recorded_at,
        reference_valid_from=datetime(2026, 10, 15, 2, 0, tzinfo=UTC),
        reference_valid_until=datetime(2026, 11, 5, 2, 0, tzinfo=UTC),
        timezone_name="Asia/Shanghai",
    )
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)


def _proof(**changes: object) -> OrderFillSettlementReleaseProof:
    values: dict[str, object] = {
        "trade_id": 71,
        "reservation_id": 41,
        "account_id": 12,
        "user_id": 7,
        "receipt_hash": "a" * 64,
        "security_id": "security-600000.SH",
        "settlement_exchange": "SH",
        "fill_market_session": _FILL_SESSION,
        "settlement_lag_sessions": 1,
        "released_at": _RELEASED_AT,
        "release_session": _RELEASE_SESSION,
        "calendar_evidence": _calendar_evidence(),
    }
    values.update(changes)
    return OrderFillSettlementReleaseProof(
        trade_id=cast(int, values["trade_id"]),
        reservation_id=cast(int, values["reservation_id"]),
        account_id=cast(int, values["account_id"]),
        user_id=cast(int, values["user_id"]),
        receipt_hash=cast(str, values["receipt_hash"]),
        security_id=cast(str, values["security_id"]),
        settlement_exchange=cast(str, values["settlement_exchange"]),
        fill_market_session=cast(date, values["fill_market_session"]),
        settlement_lag_sessions=cast(int, values["settlement_lag_sessions"]),
        released_at=cast(datetime, values["released_at"]),
        release_session=cast(date, values["release_session"]),
        calendar_evidence=cast(ExecutionCalendarEvidence, values["calendar_evidence"]),
    )


def test_release_proof_validates_identity_and_complete_state() -> None:
    proof = _proof()

    proof.validate()

    assert proof.trade_id == 71
    assert proof.reservation_id == 41
    assert proof.account_id == 12
    assert proof.user_id == 7
    assert proof.receipt_hash == "a" * 64
    assert proof.security_id == "security-600000.SH"
    assert proof.settlement_exchange == "SH"
    assert proof.fill_market_session == _FILL_SESSION
    assert proof.settlement_lag_sessions == 1
    assert proof.release_session == _RELEASE_SESSION
    assert len(proof.proof_hash) == 64
    assert proof.proof_hash != replace(proof, receipt_hash="b" * 64).proof_hash


def test_release_proof_preserves_calendar_and_release_clocks() -> None:
    proof = _proof()
    payload = proof.to_payload()
    evidence = cast(dict[str, object], payload["calendar_evidence"])
    snapshot = cast(dict[str, object], evidence["snapshot"])
    raw_reference = cast(dict[str, object], snapshot["raw_reference"])
    publication = cast(dict[str, object], evidence["publication"])

    assert snapshot["source_published_at"] == "2026-10-16T01:30:00.000000Z"
    assert raw_reference["response_completed_at"] == "2026-10-16T01:40:00.000000Z"
    assert snapshot["first_seen_at"] == "2026-10-16T01:40:00.000000Z"
    assert snapshot["recorded_at"] == "2026-10-16T01:50:00.000000Z"
    assert publication["published_at"] == "2026-10-16T01:55:00.000000Z"
    assert publication["recorded_at"] == "2026-10-16T01:56:00.000000Z"
    assert payload["released_at"] == "2026-10-20T02:00:00.000000Z"


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("trade_id", 0),
        ("trade_id", True),
        ("reservation_id", False),
        ("account_id", -1),
        ("user_id", 0),
        ("receipt_hash", "A" * 64),
        ("security_id", ""),
        ("settlement_exchange", "SH SZ"),
        ("security_id", "s" * 193),
        ("settlement_lag_sessions", True),
        ("settlement_lag_sessions", -1),
        ("fill_market_session", datetime(2026, 10, 19, tzinfo=UTC)),
        ("release_session", datetime(2026, 10, 20, tzinfo=UTC)),
        ("released_at", datetime(2026, 10, 20, 2, 0)),
    ),
)
def test_release_proof_rejects_invalid_identity_types_hash_and_clocks(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(SimulatedSettlementContractError):
        replace(_proof(), **{field_name: value})


def test_release_proof_rejects_calendar_clocks_not_known_by_release() -> None:
    future_evidence = (
        _calendar_evidence(source_published_at=_RELEASED_AT + timedelta(seconds=1)),
        _calendar_evidence(snapshot_recorded_at=_RELEASED_AT + timedelta(seconds=1)),
        _calendar_evidence(
            published_at=_RELEASED_AT + timedelta(seconds=1),
            publication_recorded_at=_RELEASED_AT + timedelta(seconds=2),
        ),
        _calendar_evidence(
            publication_recorded_at=_RELEASED_AT + timedelta(seconds=1),
        ),
    )

    for evidence in future_evidence:
        with pytest.raises(CalendarEvidenceValidationError):
            _proof(calendar_evidence=evidence)


def test_release_proof_rejects_evidence_not_visible_or_valid_at_release() -> None:
    evidence = _calendar_evidence(
        published_at=datetime(2026, 10, 16, 1, 55, tzinfo=UTC),
        publication_recorded_at=datetime(2026, 10, 16, 1, 56, tzinfo=UTC),
    )
    expired = replace(
        evidence,
        publication=replace(
            cast(CalendarPublicationReference, evidence.publication),
            reference_valid_until=datetime(2026, 10, 20, 1, 59, tzinfo=UTC),
        ),
    )

    with pytest.raises(CalendarEvidenceValidationError):
        _proof(calendar_evidence=expired)


@pytest.mark.parametrize(
    ("release_at", "release_session"),
    (
        (_RELEASED_AT, date(2026, 10, 21)),
        (datetime(2026, 10, 19, 2, 0, tzinfo=UTC), _FILL_SESSION),
    ),
)
def test_release_proof_requires_exact_current_session_and_elapsed_lag(
    release_at: datetime,
    release_session: date,
) -> None:
    with pytest.raises(CalendarEvidenceValidationError):
        _proof(released_at=release_at, release_session=release_session)


def test_release_proof_accepts_a_published_calendar_revision() -> None:
    revised_evidence = _calendar_evidence(
        closed_dates=frozenset({date(2026, 10, 20), date(2026, 10, 24)}),
        source_published_at=datetime(2026, 10, 20, 1, 0, tzinfo=UTC),
        snapshot_recorded_at=datetime(2026, 10, 20, 1, 2, tzinfo=UTC),
        published_at=datetime(2026, 10, 20, 1, 3, tzinfo=UTC),
        publication_recorded_at=datetime(2026, 10, 20, 1, 4, tzinfo=UTC),
    )
    revised_release_at = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)

    proof = _proof(
        calendar_evidence=revised_evidence,
        released_at=revised_release_at,
        release_session=date(2026, 10, 21),
    )

    proof.validate()
    assert proof.release_session != _RELEASE_SESSION


def test_release_proof_requires_exact_evidence_and_exchange_scope() -> None:
    with pytest.raises(CalendarEvidenceValidationError):
        _proof(calendar_evidence=cast(ExecutionCalendarEvidence, None))
    with pytest.raises(CalendarEvidenceValidationError):
        _proof(settlement_exchange="SZ")
    reference_only = replace(_calendar_evidence(), publication=None)
    with pytest.raises(CalendarEvidenceValidationError):
        _proof(calendar_evidence=reference_only)


def test_release_proof_allows_zero_lag_on_the_fill_session() -> None:
    proof = _proof(
        settlement_lag_sessions=0,
        released_at=datetime(2026, 10, 19, 2, 0, tzinfo=UTC),
        release_session=_FILL_SESSION,
    )

    proof.validate()
    assert proof.release_session == proof.fill_market_session


@pytest.mark.parametrize(
    ("fill_session", "released_at"),
    (
        (date(2026, 10, 18), _RELEASED_AT),
        (_FILL_SESSION, datetime(2026, 10, 24, 2, 0, tzinfo=UTC)),
    ),
)
def test_release_proof_rejects_uncovered_fill_or_closed_release_session(
    fill_session: date,
    released_at: datetime,
) -> None:
    release_session = date(2026, 10, 24) if released_at.day == 24 else _RELEASE_SESSION
    with pytest.raises(CalendarEvidenceValidationError):
        _proof(
            fill_market_session=fill_session,
            released_at=released_at,
            release_session=release_session,
        )


def test_codec_round_trip_seals_exact_payload_and_returns_fresh_mappings() -> None:
    proof = _proof()
    encoded = encode_order_fill_settlement_release_proof(proof)
    decoded = decode_order_fill_settlement_release_proof(
        json.loads(encoded.proof_json),
        proof_hash=encoded.proof_hash,
    )

    assert encoded.proof is proof
    assert decoded == proof
    assert decoded is not proof
    assert encoded.proof_hash == proof.proof_hash
    assert set(encoded.to_payload()) == {
        "schema",
        "trade_id",
        "reservation_id",
        "account_id",
        "user_id",
        "receipt_hash",
        "security_id",
        "settlement_exchange",
        "fill_market_session",
        "settlement_lag_sessions",
        "released_at",
        "release_session",
        "calendar_evidence",
    }
    first_payload = encoded.to_payload()
    first_payload["trade_id"] = 999
    assert encoded.to_payload()["trade_id"] == 71
    cast(dict[str, object], first_payload["calendar_evidence"])["evidence_hash"] = "0" * 64
    fresh_evidence = cast(dict[str, object], encoded.to_payload()["calendar_evidence"])
    assert fresh_evidence["evidence_hash"] == proof.calendar_evidence.evidence_hash


@pytest.mark.parametrize(
    "mutation",
    ("missing", "extra", "version", "trade_id_bool", "lag_bool"),
)
def test_codec_rejects_unknown_schema_keys_and_bool_aliases(mutation: str) -> None:
    encoded = encode_order_fill_settlement_release_proof(_proof())
    payload = json.loads(encoded.proof_json)
    if mutation == "missing":
        del payload["receipt_hash"]
    elif mutation == "extra":
        payload["unexpected"] = "value"
    elif mutation == "version":
        payload["schema"] = "simulated-order-fill-settlement-release-proof.v99"
    elif mutation == "trade_id_bool":
        payload["trade_id"] = True
    else:
        payload["settlement_lag_sessions"] = True

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_fill_settlement_release_proof(
            payload,
            proof_hash=encoded.proof_hash,
        )


@pytest.mark.parametrize(
    "mutation",
    ("missing", "extra", "hash", "snapshot_extra", "snapshot_hash"),
)
def test_codec_rejects_bad_nested_calendar_payloads(mutation: str) -> None:
    encoded = encode_order_fill_settlement_release_proof(_proof())
    payload = json.loads(encoded.proof_json)
    evidence = cast(dict[str, object], payload["calendar_evidence"])
    if mutation == "missing":
        del evidence["publication"]
    elif mutation == "extra":
        evidence["unknown"] = None
    elif mutation == "hash":
        evidence["evidence_hash"] = "0" * 64
    else:
        snapshot = cast(dict[str, object], evidence["snapshot"])
        if mutation == "snapshot_extra":
            snapshot["unknown"] = None
        else:
            snapshot["content_hash"] = "sha256:" + "0" * 64

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_fill_settlement_release_proof(
            payload,
            proof_hash=encoded.proof_hash,
        )


def test_codec_rejects_stored_hash_mismatch_and_missing_stored_hash() -> None:
    encoded = encode_order_fill_settlement_release_proof(_proof())
    payload = json.loads(encoded.proof_json)

    with pytest.raises(SimulatedSettlementContractError):
        decode_order_fill_settlement_release_proof(payload, proof_hash="0" * 64)
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_fill_settlement_release_proof(payload, proof_hash=None)


def test_encoded_dto_rejects_noncanonical_json_and_unrelated_hash() -> None:
    encoded = encode_order_fill_settlement_release_proof(_proof())
    with pytest.raises(SimulatedSettlementContractError):
        replace(encoded, proof_json=encoded.proof_json + " ")
    with pytest.raises(SimulatedSettlementContractError):
        replace(encoded, proof_hash="0" * 64)


def test_codec_rejects_noncanonical_typed_values_and_enforces_json_size_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = encode_order_fill_settlement_release_proof(_proof())
    payload = json.loads(encoded.proof_json)
    payload["release_session"] = "2026-10-20T00:00:00Z"
    with pytest.raises(SimulatedSettlementContractError):
        decode_order_fill_settlement_release_proof(
            payload,
            proof_hash=encoded.proof_hash,
        )

    monkeypatch.setattr(
        order_reservation_fill_calendar_codec,
        "_MAX_PROOF_JSON_LENGTH",
        32,
    )
    with pytest.raises(SimulatedSettlementContractError):
        encode_order_fill_settlement_release_proof(_proof())
