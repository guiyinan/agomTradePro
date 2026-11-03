"""Strictly narrow JSON-shaped source records into risk evidence values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)

_SOURCE_KEYS = frozenset(
    {
        "source_id",
        "source_record_id",
        "original_payload_sha256",
        "observation_precision",
        "observed_at",
        "observed_on",
        "available_at",
        "known_at",
        "valid_until",
        "source_purpose",
        "allowed_purposes",
        "restrictions",
        "must_not_use_for_decision",
        "coverage",
        "effective_on",
        "effective_until",
    }
)
_REQUIRED_SOURCE_KEYS = frozenset(
    {
        "source_id",
        "source_record_id",
        "observation_precision",
        "source_purpose",
        "allowed_purposes",
        "restrictions",
        "must_not_use_for_decision",
        "coverage",
    }
)
_COVERAGE_KEYS = frozenset(
    {
        "status",
        "precision_basis",
        "reported_weight_fraction",
        "expected_item_count",
        "observed_item_count",
    }
)
_REQUIRED_COVERAGE_KEYS = frozenset({"status", "precision_basis"})


@dataclass(frozen=True, slots=True)
class PortfolioRiskSourcePayload:
    """Source-origin fields that can be copied back without decision cutoffs."""

    source_id: str
    source_record_id: str
    original_payload_sha256: str | None
    observation_precision: SourceObservationPrecision
    observed_at: datetime | None
    observed_on: date | None
    available_at: datetime | None
    known_at: datetime | None
    valid_until: datetime | None
    source_purpose: str
    allowed_purposes: tuple[str, ...]
    restrictions: tuple[str, ...]
    must_not_use_for_decision: bool
    coverage: PortfolioRiskCoverage
    effective_on: date | None
    effective_until: date | None


def decode_portfolio_risk_source_evidence(
    raw: Mapping[str, object],
    *,
    decision_cutoff: datetime,
    decision_date_cutoff: date | None,
) -> PortfolioRiskSourceEvidence:
    """Validate a JSON mapping and bind only server-supplied decision cutoffs.

    Source observation, availability, known, validity and effective clocks are
    parsed without changing offsets or substituting request time. Missing optional
    source facts remain ``None``; the evidence type and qualifier decide whether
    those facts are sufficient for a risk decision.
    """

    if not isinstance(raw, Mapping):
        raise TypeError("risk source payload must be a mapping")
    missing_keys = _REQUIRED_SOURCE_KEYS - set(raw)
    unknown_keys = set(raw) - _SOURCE_KEYS
    if missing_keys:
        raise ValueError("risk source payload is missing required fields")
    if unknown_keys:
        raise ValueError("risk source payload contains unsupported fields")

    precision_text = _required_string(raw["observation_precision"], "observation_precision")
    try:
        precision = SourceObservationPrecision(precision_text)
    except ValueError as exc:
        raise ValueError("observation_precision is not supported") from exc

    return PortfolioRiskSourceEvidence(
        source_id=_required_string(raw["source_id"], "source_id"),
        source_record_id=_required_string(raw["source_record_id"], "source_record_id"),
        original_payload_sha256=_optional_string(
            raw.get("original_payload_sha256"),
            "original_payload_sha256",
        ),
        observation_precision=precision,
        observed_at=_optional_datetime(raw.get("observed_at"), "observed_at"),
        observed_on=_optional_date(raw.get("observed_on"), "observed_on"),
        available_at=_optional_datetime(raw.get("available_at"), "available_at"),
        known_at=_optional_datetime(raw.get("known_at"), "known_at"),
        decision_cutoff=decision_cutoff,
        decision_date_cutoff=decision_date_cutoff,
        valid_until=_optional_datetime(raw.get("valid_until"), "valid_until"),
        source_purpose=_required_string(raw["source_purpose"], "source_purpose"),
        allowed_purposes=_string_tuple(raw["allowed_purposes"], "allowed_purposes"),
        restrictions=_string_tuple(raw["restrictions"], "restrictions", allow_empty=True),
        must_not_use_for_decision=_required_bool(
            raw["must_not_use_for_decision"],
            "must_not_use_for_decision",
        ),
        coverage=_decode_coverage(raw["coverage"]),
        effective_on=_optional_date(raw.get("effective_on"), "effective_on"),
        effective_until=_optional_date(raw.get("effective_until"), "effective_until"),
    )


def decode_portfolio_risk_source_payload(
    raw: Mapping[str, object],
) -> PortfolioRiskSourcePayload:
    """Decode source-origin fields without inventing a decision cutoff.

    Admission records are captured before any risk request exists, so they do
    not contain service decision cutoffs.  This parser retains only the
    explicitly supplied source clocks, permissions, restrictions, and coverage.
    """

    if not isinstance(raw, Mapping):
        raise TypeError("risk source payload must be a mapping")
    missing_keys = _REQUIRED_SOURCE_KEYS - set(raw)
    unknown_keys = set(raw) - _SOURCE_KEYS
    if missing_keys:
        raise ValueError("risk source payload is missing required fields")
    if unknown_keys:
        raise ValueError("risk source payload contains unsupported fields")

    precision_text = _required_string(raw["observation_precision"], "observation_precision")
    try:
        precision = SourceObservationPrecision(precision_text)
    except ValueError as exc:
        raise ValueError("observation_precision is not supported") from exc

    source_id = _source_token(raw["source_id"], "source_id")
    source_record_id = _source_token(raw["source_record_id"], "source_record_id")
    source_purpose = _source_token(raw["source_purpose"], "source_purpose")
    allowed_purposes = _string_tuple(raw["allowed_purposes"], "allowed_purposes")
    restrictions = _string_tuple(raw["restrictions"], "restrictions", allow_empty=True)
    original_payload_sha256 = _optional_string(
        raw.get("original_payload_sha256"),
        "original_payload_sha256",
    )
    if original_payload_sha256 is not None and (
        len(original_payload_sha256) != 64
        or any(character not in "0123456789abcdef" for character in original_payload_sha256)
    ):
        raise ValueError("original_payload_sha256 must be a lowercase SHA-256 digest")

    observed_at = _optional_datetime(raw.get("observed_at"), "observed_at")
    observed_on = _optional_date(raw.get("observed_on"), "observed_on")
    if precision is SourceObservationPrecision.TIMESTAMP:
        if observed_at is None or observed_on is not None:
            raise ValueError("timestamp precision requires observed_at and forbids observed_on")
    elif precision is SourceObservationPrecision.DATE:
        if observed_on is None or observed_at is not None:
            raise ValueError("date precision requires observed_on and forbids observed_at")
    elif observed_at is not None or observed_on is not None:
        raise ValueError("unknown precision cannot carry an observation clock")

    evidence = PortfolioRiskSourcePayload(
        source_id=source_id,
        source_record_id=source_record_id,
        original_payload_sha256=original_payload_sha256,
        observation_precision=precision,
        observed_at=observed_at,
        observed_on=observed_on,
        available_at=_optional_datetime(raw.get("available_at"), "available_at"),
        known_at=_optional_datetime(raw.get("known_at"), "known_at"),
        valid_until=_optional_datetime(raw.get("valid_until"), "valid_until"),
        source_purpose=source_purpose,
        allowed_purposes=allowed_purposes,
        restrictions=restrictions,
        must_not_use_for_decision=_required_bool(
            raw["must_not_use_for_decision"],
            "must_not_use_for_decision",
        ),
        coverage=_decode_coverage(raw["coverage"]),
        effective_on=_optional_date(raw.get("effective_on"), "effective_on"),
        effective_until=_optional_date(raw.get("effective_until"), "effective_until"),
    )
    if (
        evidence.effective_on is not None
        and evidence.effective_until is not None
        and evidence.effective_until < evidence.effective_on
    ):
        raise ValueError("effective_until cannot precede effective_on")
    return evidence


def encode_portfolio_risk_source_payload(
    evidence: PortfolioRiskSourceEvidence,
) -> PortfolioRiskSourcePayload:
    """Project only source-origin fields, excluding service-bound cutoffs."""

    if type(evidence) is not PortfolioRiskSourceEvidence:
        raise TypeError("evidence must be PortfolioRiskSourceEvidence")
    return PortfolioRiskSourcePayload(
        source_id=evidence.source_id,
        source_record_id=evidence.source_record_id,
        original_payload_sha256=evidence.original_payload_sha256,
        observation_precision=evidence.observation_precision,
        observed_at=evidence.observed_at,
        observed_on=evidence.observed_on,
        available_at=evidence.available_at,
        known_at=evidence.known_at,
        valid_until=evidence.valid_until,
        source_purpose=evidence.source_purpose,
        allowed_purposes=evidence.allowed_purposes,
        restrictions=evidence.restrictions,
        must_not_use_for_decision=evidence.must_not_use_for_decision,
        coverage=evidence.coverage,
        effective_on=evidence.effective_on,
        effective_until=evidence.effective_until,
    )


def evidence_from_portfolio_risk_source_payload(
    payload: PortfolioRiskSourcePayload,
    *,
    decision_cutoff: datetime,
    decision_date_cutoff: date | None,
) -> PortfolioRiskSourceEvidence:
    """Rebuild source evidence with new explicit service decision cutoffs."""

    if type(payload) is not PortfolioRiskSourcePayload:
        raise TypeError("payload must be PortfolioRiskSourcePayload")
    return PortfolioRiskSourceEvidence(
        source_id=payload.source_id,
        source_record_id=payload.source_record_id,
        original_payload_sha256=payload.original_payload_sha256,
        observation_precision=payload.observation_precision,
        observed_at=payload.observed_at,
        observed_on=payload.observed_on,
        available_at=payload.available_at,
        known_at=payload.known_at,
        decision_cutoff=decision_cutoff,
        decision_date_cutoff=decision_date_cutoff,
        valid_until=payload.valid_until,
        source_purpose=payload.source_purpose,
        allowed_purposes=payload.allowed_purposes,
        restrictions=payload.restrictions,
        must_not_use_for_decision=payload.must_not_use_for_decision,
        coverage=payload.coverage,
        effective_on=payload.effective_on,
        effective_until=payload.effective_until,
    )


def _decode_coverage(raw: object) -> PortfolioRiskCoverage:
    if not isinstance(raw, Mapping):
        raise TypeError("coverage must be a mapping")
    missing_keys = _REQUIRED_COVERAGE_KEYS - set(raw)
    unknown_keys = set(raw) - _COVERAGE_KEYS
    if missing_keys:
        raise ValueError("coverage is missing required fields")
    if unknown_keys:
        raise ValueError("coverage contains unsupported fields")
    status_text = _required_string(raw["status"], "coverage.status")
    try:
        status = CoverageStatus(status_text)
    except ValueError as exc:
        raise ValueError("coverage.status is not supported") from exc
    return PortfolioRiskCoverage(
        status=status,
        precision_basis=_required_string(raw["precision_basis"], "coverage.precision_basis"),
        reported_weight_fraction=_optional_decimal(
            raw.get("reported_weight_fraction"),
            "coverage.reported_weight_fraction",
        ),
        expected_item_count=_optional_count(
            raw.get("expected_item_count"),
            "coverage.expected_item_count",
        ),
        observed_item_count=_optional_count(
            raw.get("observed_item_count"),
            "coverage.observed_item_count",
        ),
    )


def _required_string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a nonempty canonical string")
    return value


def _source_token(value: object, field_name: str) -> str:
    """Validate a source identifier without normalizing its spelling."""

    token = _required_string(value, field_name)
    if any(character.isspace() for character in token):
        raise ValueError(f"{field_name} cannot contain whitespace")
    return token


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, field_name)


def _string_tuple(value: object, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if isinstance(value, list):
        raw_tokens = tuple(value)
    elif isinstance(value, tuple):
        raw_tokens = value
    else:
        raise TypeError(f"{field_name} must be a JSON string array")
    tokens = tuple(_required_string(item, field_name) for item in raw_tokens)
    if not allow_empty and not tokens:
        raise ValueError(f"{field_name} cannot be empty")
    if any(any(character.isspace() for character in token) for token in tokens):
        raise ValueError(f"{field_name} tokens cannot contain whitespace")
    if len(tokens) != len(set(tokens)):
        raise ValueError(f"{field_name} cannot contain duplicate tokens")
    return tokens


def _required_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a boolean")
    return value


def _optional_datetime(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    if type(value) is datetime:
        parsed = value
    elif type(value) is str:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO datetime") from exc
    else:
        raise TypeError(f"{field_name} must be a datetime, ISO datetime string, or None")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must retain an explicit timezone")
    return parsed


def _optional_date(value: object, field_name: str) -> date | None:
    if value is None:
        return None
    if type(value) is date:
        return value
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a date, ISO date string, or None")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date without time") from exc


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if type(value) is Decimal:
        parsed = value
    elif type(value) is int:
        parsed = Decimal(value)
    elif type(value) is str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{field_name} must be exact decimal text") from exc
    else:
        raise TypeError(f"{field_name} must be Decimal, integer, decimal text, or None")
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _optional_count(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an exact integer or None")
    return value


__all__ = (
    "PortfolioRiskSourcePayload",
    "decode_portfolio_risk_source_evidence",
    "decode_portfolio_risk_source_payload",
    "encode_portfolio_risk_source_payload",
    "evidence_from_portfolio_risk_source_payload",
)
