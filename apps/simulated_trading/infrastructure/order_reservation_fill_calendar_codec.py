"""Strictly decode and encode the immutable G2 per-fill calendar proof.

This module validates persisted JSON against the existing Domain calendar and
settlement contracts. It does not qualify a fill source or write ledger rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast

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
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
)

_PROOF_SCHEMA = "simulated-order-fill-settlement-proof.v1"
_EVIDENCE_KEYS = ("evidence_hash", "snapshot", "publication")
_SNAPSHOT_KEYS = (
    "schema",
    "exchange",
    "coverage_start",
    "coverage_end",
    "days",
    "provider_name",
    "raw_reference",
    "first_seen_at",
    "source_published_at",
    "snapshot_id",
    "recorded_at",
    "content_hash",
    "record_digest",
)
_DAY_KEYS = ("exchange", "calendar_date", "is_open", "previous_open_date")
_RAW_REFERENCE_KEYS = (
    "payload_id",
    "payload_hash",
    "record_digest",
    "body_sha256",
    "retained_content_sha256",
    "request_scope_sha256",
    "original_body_retained",
    "response_completed_at",
    "response_time_semantics",
    "provider_name",
    "dataset_key",
    "transport",
)
_PUBLICATION_KEYS = (
    "publication_id",
    "member_id",
    "publication_hash",
    "fact_content_hash",
    "policy_hash",
    "published_at",
    "recorded_at",
    "reference_valid_from",
    "reference_valid_until",
    "timezone_name",
)
_PROOF_KEYS = (
    "schema",
    "calendar_evidence",
    "calendar_read_cutoff",
    "fill_occurred_at",
    "settlement_exchange",
    "fill_market_session",
    "settlement_lag_sessions",
    "expected_release_session",
)
_MAX_PROOF_JSON_LENGTH = 524_288
_RAW_RESPONSE_TIME_SEMANTICS = "local_response_body_completion"


def _expect_object(
    value: object,
    *,
    field_names: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    """Narrow one JSON object and require its exact declared keys."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise SimulatedSettlementContractError(f"{label} must be a JSON object")
    payload = cast(dict[str, object], value)
    if frozenset(payload) != frozenset(field_names):
        raise SimulatedSettlementContractError(f"{label} fields are missing or unknown")
    return payload


def _require_text(value: object, field_name: str) -> str:
    """Require one literal string at the untrusted JSON boundary."""

    if type(value) is not str:
        raise SimulatedSettlementContractError(f"{field_name} must be text")
    return value


def _require_bool(value: object, field_name: str) -> bool:
    """Require a literal JSON boolean, excluding integers."""

    if type(value) is not bool:
        raise SimulatedSettlementContractError(f"{field_name} must be a boolean")
    return value


def _require_int(value: object, field_name: str) -> int:
    """Require a literal JSON integer, excluding booleans."""

    if type(value) is not int:
        raise SimulatedSettlementContractError(f"{field_name} must be an integer")
    return value


def _canonical_json(payload: dict[str, object], label: str) -> str:
    """Serialize one JSON object and bound its UTF-8 storage representation."""

    try:
        serialized = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        payload_size = len(serialized.encode("utf-8"))
    except (TypeError, ValueError) as error:
        raise SimulatedSettlementContractError(f"{label} is not canonical JSON") from error
    if payload_size > _MAX_PROOF_JSON_LENGTH:
        raise SimulatedSettlementContractError(f"{label} exceeds the size limit")
    return serialized


def _parse_date(value: object, field_name: str) -> date:
    """Parse one exact ISO calendar date without accepting datetime values."""

    text = _require_text(value, field_name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise SimulatedSettlementContractError(f"{field_name} is not an ISO date") from error
    if type(parsed) is not date or parsed.isoformat() != text:
        raise SimulatedSettlementContractError(f"{field_name} is not a canonical ISO date")
    return parsed


def _utc_text(value: datetime, field_name: str) -> str:
    """Serialize one aware instant in the proof's UTC microsecond form."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise SimulatedSettlementContractError(f"{field_name} must be an aware datetime")
    try:
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError(
            f"{field_name} cannot be represented in UTC"
        ) from error


def _parse_utc_datetime(value: object, field_name: str) -> datetime:
    """Parse only canonical UTC-Z text with exactly six fractional digits."""

    text = _require_text(value, field_name)
    if not text.endswith("Z"):
        raise SimulatedSettlementContractError(f"{field_name} must use canonical UTC-Z text")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
        if type(parsed) is not datetime or _utc_text(parsed, field_name) != text:
            raise SimulatedSettlementContractError(f"{field_name} is not canonical UTC text")
        return parsed.astimezone(UTC)
    except SimulatedSettlementContractError:
        raise
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError(
            f"{field_name} is not an aware UTC instant"
        ) from error


def _same_json_value(actual: object, expected: object) -> bool:
    """Compare nested JSON with exact scalar types as well as exact values."""

    if type(actual) is not type(expected):
        return False
    if type(actual) is dict:
        actual_map = cast(dict[str, object], actual)
        expected_map = cast(dict[str, object], expected)
        return actual_map.keys() == expected_map.keys() and all(
            _same_json_value(actual_map[key], expected_map[key]) for key in actual_map
        )
    if type(actual) is list:
        actual_list = cast(list[object], actual)
        expected_list = cast(list[object], expected)
        return len(actual_list) == len(expected_list) and all(
            _same_json_value(left, right)
            for left, right in zip(actual_list, expected_list, strict=False)
        )
    return actual == expected


def _parse_raw_reference(value: object) -> RawCalendarReference:
    """Decode all retained-response identity without substituting source clocks."""

    payload = _expect_object(
        value,
        field_names=_RAW_REFERENCE_KEYS,
        label="calendar raw reference",
    )
    semantics = _require_text(
        payload["response_time_semantics"],
        "raw_reference.response_time_semantics",
    )
    if semantics != _RAW_RESPONSE_TIME_SEMANTICS:
        raise CalendarEvidenceValidationError("raw response completion semantics are unsupported")
    return RawCalendarReference(
        payload_id=_require_text(payload["payload_id"], "raw_reference.payload_id"),
        payload_hash=_require_text(payload["payload_hash"], "raw_reference.payload_hash"),
        record_digest=_require_text(payload["record_digest"], "raw_reference.record_digest"),
        body_sha256=_require_text(payload["body_sha256"], "raw_reference.body_sha256"),
        retained_content_sha256=_require_text(
            payload["retained_content_sha256"],
            "raw_reference.retained_content_sha256",
        ),
        request_scope_sha256=_require_text(
            payload["request_scope_sha256"],
            "raw_reference.request_scope_sha256",
        ),
        original_body_retained=_require_bool(
            payload["original_body_retained"],
            "raw_reference.original_body_retained",
        ),
        response_completed_at=_parse_utc_datetime(
            payload["response_completed_at"],
            "raw_reference.response_completed_at",
        ),
        provider_name=_require_text(payload["provider_name"], "raw_reference.provider_name"),
        dataset_key=_require_text(payload["dataset_key"], "raw_reference.dataset_key"),
        transport=_require_text(payload["transport"], "raw_reference.transport"),
    )


def _parse_day(value: object, index: int) -> ExchangeCalendarDay:
    """Decode one explicit open/closed calendar day."""

    label = f"calendar day {index}"
    payload = _expect_object(value, field_names=_DAY_KEYS, label=label)
    return ExchangeCalendarDay(
        exchange=_require_text(payload["exchange"], f"{label}.exchange"),
        calendar_date=_parse_date(payload["calendar_date"], f"{label}.calendar_date"),
        is_open=_require_bool(payload["is_open"], f"{label}.is_open"),
        previous_open_date=_parse_date(
            payload["previous_open_date"],
            f"{label}.previous_open_date",
        ),
    )


def _parse_snapshot(value: object) -> ExchangeCalendarSnapshot:
    """Rebuild the full snapshot so Domain content and record hashes are recalculated."""

    payload = _expect_object(
        value,
        field_names=_SNAPSHOT_KEYS,
        label="calendar snapshot",
    )
    snapshot_schema = _require_text(payload["schema"], "snapshot.schema")
    if snapshot_schema != "exchange-calendar-snapshot-v1":
        raise CalendarEvidenceValidationError("calendar snapshot schema is unsupported")
    days_value = payload["days"]
    if type(days_value) is not list:
        raise SimulatedSettlementContractError("calendar snapshot days must be a JSON array")
    days = tuple(_parse_day(day, index) for index, day in enumerate(days_value))
    source_published_value = payload["source_published_at"]
    source_published_at = (
        None
        if source_published_value is None
        else _parse_utc_datetime(source_published_value, "snapshot.source_published_at")
    )
    return ExchangeCalendarSnapshot(
        snapshot_id=_require_text(payload["snapshot_id"], "snapshot.snapshot_id"),
        exchange=_require_text(payload["exchange"], "snapshot.exchange"),
        coverage_start=_parse_date(payload["coverage_start"], "snapshot.coverage_start"),
        coverage_end=_parse_date(payload["coverage_end"], "snapshot.coverage_end"),
        days=days,
        provider_name=_require_text(payload["provider_name"], "snapshot.provider_name"),
        raw_reference=_parse_raw_reference(payload["raw_reference"]),
        content_hash=_require_text(payload["content_hash"], "snapshot.content_hash"),
        record_digest=_require_text(payload["record_digest"], "snapshot.record_digest"),
        first_seen_at=_parse_utc_datetime(payload["first_seen_at"], "snapshot.first_seen_at"),
        recorded_at=_parse_utc_datetime(payload["recorded_at"], "snapshot.recorded_at"),
        source_published_at=source_published_at,
    )


def _parse_publication(value: object) -> CalendarPublicationReference | None:
    """Decode the complete formal publication reference or preserve explicit absence."""

    if value is None:
        return None
    payload = _expect_object(
        value,
        field_names=_PUBLICATION_KEYS,
        label="calendar publication",
    )
    return CalendarPublicationReference(
        publication_id=_require_text(payload["publication_id"], "publication.publication_id"),
        member_id=_require_text(payload["member_id"], "publication.member_id"),
        publication_hash=_require_text(payload["publication_hash"], "publication.publication_hash"),
        fact_content_hash=_require_text(
            payload["fact_content_hash"],
            "publication.fact_content_hash",
        ),
        policy_hash=_require_text(payload["policy_hash"], "publication.policy_hash"),
        published_at=_parse_utc_datetime(payload["published_at"], "publication.published_at"),
        recorded_at=_parse_utc_datetime(payload["recorded_at"], "publication.recorded_at"),
        reference_valid_from=_parse_utc_datetime(
            payload["reference_valid_from"],
            "publication.reference_valid_from",
        ),
        reference_valid_until=_parse_utc_datetime(
            payload["reference_valid_until"],
            "publication.reference_valid_until",
        ),
        timezone_name=_require_text(payload["timezone_name"], "publication.timezone_name"),
    )


def _parse_evidence(value: object) -> ExecutionCalendarEvidence:
    """Rebuild and hash-check the exact snapshot and optional publication."""

    payload = _expect_object(
        value,
        field_names=_EVIDENCE_KEYS,
        label="calendar evidence",
    )
    snapshot = _parse_snapshot(payload["snapshot"])
    publication = _parse_publication(payload["publication"])
    evidence = ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)
    evidence_hash = _require_text(payload["evidence_hash"], "calendar evidence hash")
    if evidence.evidence_hash != evidence_hash:
        raise CalendarEvidenceValidationError(
            "calendar evidence hash differs from its complete typed evidence"
        )
    return evidence


def _parse_plan_datetime(value: object, field_name: str) -> datetime:
    """Parse one UTC timestamp exactly as the reservation plan stored it."""

    text = _require_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
        offset = parsed.utcoffset()
    except (OverflowError, TypeError, ValueError) as error:
        raise CalendarEvidenceValidationError(
            f"{field_name} is not a valid plan timestamp"
        ) from error
    if type(parsed) is not datetime or parsed.isoformat() != text or offset != timedelta(0):
        raise CalendarEvidenceValidationError(
            f"{field_name} is not the exact UTC timestamp representation from the plan"
        )
    return parsed


def _parse_plan_publication_datetime(value: object, field_name: str) -> datetime:
    """Parse the original publication ``_utc_text`` representation exactly."""

    text = _require_text(value, field_name)
    if not text.endswith("Z"):
        raise CalendarEvidenceValidationError(f"{field_name} must use its stored UTC-Z form")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
        if parsed.isoformat().replace("+00:00", "Z") != text:
            raise CalendarEvidenceValidationError(
                f"{field_name} is not the exact stored publication timestamp"
            )
        return parsed.astimezone(UTC)
    except CalendarEvidenceValidationError:
        raise
    except (OverflowError, TypeError, ValueError) as error:
        raise CalendarEvidenceValidationError(
            f"{field_name} is not a valid stored publication timestamp"
        ) from error


def _parse_plan_raw_reference(value: object) -> RawCalendarReference:
    """Decode a retained-response reference in the plan snapshot's time format."""

    payload = _expect_object(
        value,
        field_names=_RAW_REFERENCE_KEYS,
        label="sealed plan calendar raw reference",
    )
    if (
        _require_text(
            payload["response_time_semantics"],
            "raw_reference.response_time_semantics",
        )
        != _RAW_RESPONSE_TIME_SEMANTICS
    ):
        raise CalendarEvidenceValidationError("raw response completion semantics are unsupported")
    return RawCalendarReference(
        payload_id=_require_text(payload["payload_id"], "raw_reference.payload_id"),
        payload_hash=_require_text(payload["payload_hash"], "raw_reference.payload_hash"),
        record_digest=_require_text(payload["record_digest"], "raw_reference.record_digest"),
        body_sha256=_require_text(payload["body_sha256"], "raw_reference.body_sha256"),
        retained_content_sha256=_require_text(
            payload["retained_content_sha256"],
            "raw_reference.retained_content_sha256",
        ),
        request_scope_sha256=_require_text(
            payload["request_scope_sha256"],
            "raw_reference.request_scope_sha256",
        ),
        original_body_retained=_require_bool(
            payload["original_body_retained"],
            "raw_reference.original_body_retained",
        ),
        response_completed_at=_parse_plan_datetime(
            payload["response_completed_at"],
            "raw_reference.response_completed_at",
        ),
        provider_name=_require_text(payload["provider_name"], "raw_reference.provider_name"),
        dataset_key=_require_text(payload["dataset_key"], "raw_reference.dataset_key"),
        transport=_require_text(payload["transport"], "raw_reference.transport"),
    )


def _parse_plan_snapshot(value: object) -> ExchangeCalendarSnapshot:
    """Rebuild a plan calendar snapshot using its exact persisted timestamp text."""

    payload = _expect_object(
        value,
        field_names=_SNAPSHOT_KEYS,
        label="sealed plan calendar snapshot",
    )
    if _require_text(payload["schema"], "snapshot.schema") != "exchange-calendar-snapshot-v1":
        raise CalendarEvidenceValidationError("calendar snapshot schema is unsupported")
    days_value = payload["days"]
    if type(days_value) is not list:
        raise SimulatedSettlementContractError("calendar snapshot days must be a JSON array")
    source_published_value = payload["source_published_at"]
    source_published_at = (
        None
        if source_published_value is None
        else _parse_plan_datetime(source_published_value, "snapshot.source_published_at")
    )
    return ExchangeCalendarSnapshot(
        snapshot_id=_require_text(payload["snapshot_id"], "snapshot.snapshot_id"),
        exchange=_require_text(payload["exchange"], "snapshot.exchange"),
        coverage_start=_parse_date(payload["coverage_start"], "snapshot.coverage_start"),
        coverage_end=_parse_date(payload["coverage_end"], "snapshot.coverage_end"),
        days=tuple(_parse_day(day, index) for index, day in enumerate(days_value)),
        provider_name=_require_text(payload["provider_name"], "snapshot.provider_name"),
        raw_reference=_parse_plan_raw_reference(payload["raw_reference"]),
        content_hash=_require_text(payload["content_hash"], "snapshot.content_hash"),
        record_digest=_require_text(payload["record_digest"], "snapshot.record_digest"),
        first_seen_at=_parse_plan_datetime(payload["first_seen_at"], "snapshot.first_seen_at"),
        recorded_at=_parse_plan_datetime(payload["recorded_at"], "snapshot.recorded_at"),
        source_published_at=source_published_at,
    )


def _parse_plan_publication(value: object) -> CalendarPublicationReference | None:
    """Decode a publication using its original non-microsecond-fixed UTC text."""

    if value is None:
        return None
    payload = _expect_object(
        value,
        field_names=_PUBLICATION_KEYS,
        label="sealed plan calendar publication",
    )
    return CalendarPublicationReference(
        publication_id=_require_text(payload["publication_id"], "publication.publication_id"),
        member_id=_require_text(payload["member_id"], "publication.member_id"),
        publication_hash=_require_text(payload["publication_hash"], "publication.publication_hash"),
        fact_content_hash=_require_text(
            payload["fact_content_hash"],
            "publication.fact_content_hash",
        ),
        policy_hash=_require_text(payload["policy_hash"], "publication.policy_hash"),
        published_at=_parse_plan_publication_datetime(
            payload["published_at"],
            "publication.published_at",
        ),
        recorded_at=_parse_plan_publication_datetime(
            payload["recorded_at"],
            "publication.recorded_at",
        ),
        reference_valid_from=_parse_plan_publication_datetime(
            payload["reference_valid_from"],
            "publication.reference_valid_from",
        ),
        reference_valid_until=_parse_plan_publication_datetime(
            payload["reference_valid_until"],
            "publication.reference_valid_until",
        ),
        timezone_name=_require_text(payload["timezone_name"], "publication.timezone_name"),
    )


def decode_sealed_order_calendar_evidence(payload: object) -> ExecutionCalendarEvidence:
    """Decode exact typed calendar evidence from an immutable reservation plan.

    Plan snapshots serialize calendar snapshot clocks with ``datetime.isoformat``
    while fill proofs use a separate canonical UTC-Z representation. This decoder
    preserves and verifies the plan format rather than weakening the proof codec.
    """

    try:
        evidence_payload = _expect_object(
            payload,
            field_names=_EVIDENCE_KEYS,
            label="sealed plan calendar evidence",
        )
        _canonical_json(evidence_payload, "sealed plan calendar evidence")
        snapshot = _parse_plan_snapshot(evidence_payload["snapshot"])
        publication = _parse_plan_publication(evidence_payload["publication"])
        evidence = ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)
        evidence_hash = _require_text(
            evidence_payload["evidence_hash"],
            "calendar evidence hash",
        )
        expected_payload = {
            "snapshot": snapshot.to_payload(),
            "publication": publication.to_payload() if publication is not None else None,
            "evidence_hash": evidence.evidence_hash,
        }
        if evidence_hash != evidence.evidence_hash or not _same_json_value(
            evidence_payload,
            expected_payload,
        ):
            raise CalendarEvidenceValidationError(
                "sealed plan calendar differs from its exact typed evidence"
            )
        return evidence
    except CalendarEvidenceValidationError:
        raise
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise CalendarEvidenceValidationError(
            "sealed plan calendar evidence failed exact validation"
        ) from error


@dataclass(frozen=True, slots=True)
class EncodedOrderFillSettlementProof:
    """Canonical JSON plus the validated Domain proof and its independent digest."""

    proof: OrderFillSettlementProof
    proof_json: str
    proof_hash: str

    def __post_init__(self) -> None:
        """Reject a mutated proof or a digest unrelated to its canonical payload."""

        if type(self.proof) is not OrderFillSettlementProof:
            raise SimulatedSettlementContractError("proof must be the exact Domain value")
        self.proof.validate()
        expected_json = _canonical_json(self.proof.to_payload(), "proof")
        if type(self.proof_json) is not str or self.proof_json != expected_json:
            raise SimulatedSettlementContractError("proof JSON is not its canonical payload")
        if type(self.proof_hash) is not str or self.proof_hash != self.proof.proof_hash:
            raise SimulatedSettlementContractError("proof hash differs from its exact payload")

    def to_payload(self) -> dict[str, object]:
        """Return a fresh JSON object so callers cannot mutate the sealed DTO."""

        if len(self.proof_json.encode("utf-8")) > _MAX_PROOF_JSON_LENGTH:
            raise SimulatedSettlementContractError("proof JSON exceeds the configured size limit")
        try:
            value: object = json.loads(self.proof_json)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise SimulatedSettlementContractError("encoded proof JSON is invalid") from error
        return _expect_object(value, field_names=_PROOF_KEYS, label="encoded proof")


def decode_order_fill_settlement_proof(payload: object) -> OrderFillSettlementProof:
    """Decode untrusted proof JSON and recompute all calendar/domain invariants."""

    proof_payload = _expect_object(
        payload,
        field_names=_PROOF_KEYS,
        label="fill settlement proof",
    )
    _canonical_json(proof_payload, "fill settlement proof")
    proof_schema = _require_text(proof_payload["schema"], "proof.schema")
    if proof_schema != _PROOF_SCHEMA:
        raise CalendarEvidenceValidationError("fill settlement proof schema is unsupported")
    evidence = _parse_evidence(proof_payload["calendar_evidence"])
    lag = _require_int(
        proof_payload["settlement_lag_sessions"],
        "settlement_lag_sessions",
    )
    proof = OrderFillSettlementProof(
        calendar_evidence=evidence,
        calendar_read_cutoff=_parse_utc_datetime(
            proof_payload["calendar_read_cutoff"],
            "calendar_read_cutoff",
        ),
        fill_occurred_at=_parse_utc_datetime(
            proof_payload["fill_occurred_at"],
            "fill_occurred_at",
        ),
        settlement_exchange=_require_text(
            proof_payload["settlement_exchange"],
            "settlement_exchange",
        ),
        fill_market_session=_parse_date(
            proof_payload["fill_market_session"],
            "fill_market_session",
        ),
        settlement_lag_sessions=lag,
        expected_release_session=_parse_date(
            proof_payload["expected_release_session"],
            "expected_release_session",
        ),
    )
    if not _same_json_value(proof_payload, proof.to_payload()):
        raise SimulatedSettlementContractError(
            "fill settlement proof is not its exact canonical typed representation"
        )
    _canonical_json(proof.to_payload(), "fill settlement proof")
    return proof


def encode_order_fill_settlement_proof(
    proof: OrderFillSettlementProof,
) -> EncodedOrderFillSettlementProof:
    """Serialize a revalidated Domain proof without changing its source clocks."""

    if type(proof) is not OrderFillSettlementProof:
        raise SimulatedSettlementContractError("proof must be the exact Domain value")
    proof.validate()
    proof_json = _canonical_json(proof.to_payload(), "fill settlement proof")
    return EncodedOrderFillSettlementProof(
        proof=proof,
        proof_json=proof_json,
        proof_hash=proof.proof_hash,
    )


__all__: tuple[str, ...] = (
    "EncodedOrderFillSettlementProof",
    "decode_sealed_order_calendar_evidence",
    "decode_order_fill_settlement_proof",
    "encode_order_fill_settlement_proof",
)
