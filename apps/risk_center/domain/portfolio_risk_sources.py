"""Typed source evidence shared by simulated portfolio-risk projections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from apps.risk_center.domain.portfolio_risk_clock_evidence import (
    PortfolioRiskCloseSnapshotStateProof,
    PortfolioRiskDateSnapshotProof,
    PortfolioRiskTimestampSnapshotProof,
)


class CoverageStatus(StrEnum):
    """How much of a source's expected contents is explicitly accounted for."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class SourceObservationPrecision(StrEnum):
    """Actual precision of the source observation clock."""

    TIMESTAMP = "timestamp"
    DATE = "date"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PortfolioRiskCoverage:
    """Coverage facts carried with a source, without assuming missing rows are zero."""

    status: CoverageStatus
    precision_basis: str
    reported_weight_fraction: Decimal | None = None
    expected_item_count: int | None = None
    observed_item_count: int | None = None

    def __post_init__(self) -> None:
        """Reject malformed counts and coverage ratios while preserving unknowns."""

        if not isinstance(self.status, CoverageStatus):
            raise TypeError("status must be CoverageStatus")
        _require_token(self.precision_basis, "precision_basis")
        if self.reported_weight_fraction is not None:
            _require_fraction(self.reported_weight_fraction, "reported_weight_fraction")
        counts = (self.expected_item_count, self.observed_item_count)
        if (counts[0] is None) != (counts[1] is None):
            raise ValueError("coverage item counts must both be present or both be absent")
        if counts[0] is not None and counts[1] is not None:
            if type(counts[0]) is not int or type(counts[1]) is not int:
                raise TypeError("coverage item counts must be exact integers")
            if counts[0] < 0 or counts[1] < 0 or counts[1] > counts[0]:
                raise ValueError("coverage item counts are outside their valid range")
        if self.status is CoverageStatus.COMPLETE:
            count_evidence = counts[0] is not None and counts[0] == counts[1]
            weight_evidence = self.reported_weight_fraction == Decimal("1")
            if not count_evidence and not weight_evidence:
                raise ValueError("complete coverage requires exact count or full-weight evidence")
        elif self.status is CoverageStatus.PARTIAL:
            count_evidence = (
                counts[0] is not None and counts[1] is not None and counts[1] < counts[0]
            )
            weight_evidence = (
                self.reported_weight_fraction is not None
                and self.reported_weight_fraction < Decimal("1")
            )
            if not count_evidence and not weight_evidence:
                raise ValueError("partial coverage requires an explicit observed gap")


@dataclass(frozen=True, slots=True)
class PortfolioRiskSourceEvidence:
    """Original source identity, clocks, permission and coverage for one risk input.

    Missing source clocks remain ``None`` so the qualification result can explain
    why the evidence cannot support a decision. Local fetch or persistence time is
    not a substitute for source observation, availability, or first-known time.
    """

    source_id: str
    source_record_id: str
    original_payload_sha256: str | None
    observation_precision: SourceObservationPrecision
    observed_at: datetime | None
    observed_on: date | None
    available_at: datetime | None
    known_at: datetime | None
    decision_cutoff: datetime
    decision_date_cutoff: date | None
    valid_until: datetime | None
    source_purpose: str
    allowed_purposes: tuple[str, ...]
    restrictions: tuple[str, ...]
    must_not_use_for_decision: bool
    coverage: PortfolioRiskCoverage
    effective_on: date | None = None
    effective_until: date | None = None
    policy_clock_proof: (
        PortfolioRiskDateSnapshotProof
        | PortfolioRiskTimestampSnapshotProof
        | PortfolioRiskCloseSnapshotStateProof
        | None
    ) = None

    def __post_init__(self) -> None:
        """Validate exact identities and clocks without filling absent facts."""

        _require_token(self.source_id, "source_id")
        _require_token(self.source_record_id, "source_record_id")
        _require_token(self.source_purpose, "source_purpose")
        if self.original_payload_sha256 is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.original_payload_sha256
        ):
            raise ValueError("original_payload_sha256 must be a lowercase SHA-256 digest")
        _require_aware(self.decision_cutoff, "decision_cutoff")
        if not isinstance(self.observation_precision, SourceObservationPrecision):
            raise TypeError("observation_precision must be SourceObservationPrecision")
        for field_name, value in (
            ("observed_at", self.observed_at),
            ("available_at", self.available_at),
            ("known_at", self.known_at),
            ("valid_until", self.valid_until),
        ):
            if value is not None:
                _require_aware(value, field_name)
        if self.effective_on is not None and type(self.effective_on) is not date:
            raise TypeError("effective_on must be a date or None")
        if self.observed_on is not None and type(self.observed_on) is not date:
            raise TypeError("observed_on must be a date or None")
        if self.decision_date_cutoff is not None and type(self.decision_date_cutoff) is not date:
            raise TypeError("decision_date_cutoff must be a date or None")
        if self.effective_until is not None and type(self.effective_until) is not date:
            raise TypeError("effective_until must be a date or None")
        if (
            self.effective_on is not None
            and self.effective_until is not None
            and self.effective_until < self.effective_on
        ):
            raise ValueError("effective_until cannot precede effective_on")
        if self.observation_precision is SourceObservationPrecision.TIMESTAMP:
            if self.observed_at is None:
                raise ValueError("timestamp precision requires the original observed_at")
        elif self.observation_precision is SourceObservationPrecision.DATE:
            if self.observed_on is None or self.observed_at is not None:
                raise ValueError("date precision requires observed_on and forbids a synthetic time")
            if self.decision_date_cutoff is None:
                raise ValueError("date precision requires an explicit decision_date_cutoff")
        elif self.observed_at is not None or self.observed_on is not None:
            raise ValueError("unknown precision cannot carry an observation clock")
        _require_tokens(self.allowed_purposes, "allowed_purposes")
        _require_tokens(self.restrictions, "restrictions", allow_empty=True)
        if type(self.must_not_use_for_decision) is not bool:
            raise TypeError("must_not_use_for_decision must be a boolean")
        if type(self.coverage) is not PortfolioRiskCoverage:
            raise TypeError("coverage must be PortfolioRiskCoverage")
        if self.policy_clock_proof is not None and type(self.policy_clock_proof) not in (
            PortfolioRiskDateSnapshotProof,
            PortfolioRiskTimestampSnapshotProof,
            PortfolioRiskCloseSnapshotStateProof,
        ):
            raise TypeError("policy_clock_proof must be a typed source-clock proof or None")


@dataclass(frozen=True, slots=True)
class PortfolioRiskSourceQualification:
    """Whether one exact source is eligible for a requested decision purpose."""

    eligible: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Keep the eligibility flag and stable reasons consistent."""

        if type(self.eligible) is not bool:
            raise TypeError("eligible must be a boolean")
        if type(self.reason_codes) is not tuple or any(
            type(reason) is not str or not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must be a tuple of nonempty strings")
        if self.eligible == bool(self.reason_codes):
            raise ValueError("eligible source qualification must have no blockers")


def qualify_portfolio_risk_source(
    *,
    evidence: PortfolioRiskSourceEvidence,
    requested_purpose: str,
    allowed_observation_precisions: tuple[SourceObservationPrecision, ...],
    as_of: datetime,
    allowed_restrictions: tuple[str, ...] = (),
    expected_source_kind: str | None = None,
) -> PortfolioRiskSourceQualification:
    """Fail closed on missing, future, expired, or prohibited source evidence.

    Coverage completeness is intentionally not folded into source permission:
    callers must preserve partial/unknown coverage and calculate conservative
    exposure bounds or return an unknown risk result.
    """

    _require_token(requested_purpose, "requested_purpose")
    _require_aware(as_of, "as_of")
    if type(allowed_observation_precisions) is not tuple or not allowed_observation_precisions:
        raise ValueError("allowed_observation_precisions must be a nonempty tuple")
    if any(
        not isinstance(precision, SourceObservationPrecision)
        for precision in allowed_observation_precisions
    ):
        raise TypeError("allowed_observation_precisions must contain source precision values")
    _require_tokens(allowed_restrictions, "allowed_restrictions", allow_empty=True)
    if any(_is_prohibited_restriction(item) for item in allowed_restrictions):
        raise ValueError("policy cannot allow an unconditional source prohibition")
    policy_clock_proof_is_valid = _policy_clock_proof_matches_source(
        evidence=evidence,
        proof=evidence.policy_clock_proof,
        expected_source_kind=expected_source_kind,
        as_of=as_of,
        requested_purpose=requested_purpose,
        allowed_restrictions=allowed_restrictions,
    )
    blockers: list[str] = []
    if as_of != evidence.decision_cutoff:
        blockers.append("RISK_SOURCE_CUTOFF_MISMATCH")
    if evidence.original_payload_sha256 is None:
        blockers.append("RISK_SOURCE_ORIGINAL_HASH_UNKNOWN")
    if evidence.observation_precision not in allowed_observation_precisions:
        blockers.append("RISK_SOURCE_OBSERVATION_PRECISION_NOT_ALLOWED")
    if evidence.observation_precision is SourceObservationPrecision.UNKNOWN:
        blockers.append("RISK_SOURCE_OBSERVATION_CLOCK_UNKNOWN")
    for name, value in (
        ("AVAILABLE_AT", evidence.available_at),
        ("KNOWN_AT", evidence.known_at),
        ("VALID_UNTIL", evidence.valid_until),
    ):
        if value is None:
            if not (policy_clock_proof_is_valid and name in {"AVAILABLE_AT", "VALID_UNTIL"}):
                blockers.append(f"RISK_SOURCE_{name}_UNKNOWN")
        elif name != "VALID_UNTIL" and value > as_of:
            blockers.append(f"RISK_SOURCE_{name}_AFTER_CUTOFF")
    if (
        evidence.observation_precision is SourceObservationPrecision.TIMESTAMP
        and evidence.observed_at is not None
        and evidence.observed_at > as_of
    ):
        blockers.append("RISK_SOURCE_OBSERVED_AT_AFTER_CUTOFF")
    if evidence.valid_until is not None and as_of >= evidence.valid_until:
        blockers.append("RISK_SOURCE_EXPIRED_AT_CUTOFF")
    if (
        evidence.observation_precision is SourceObservationPrecision.DATE
        and evidence.observed_on is not None
        and evidence.decision_date_cutoff is not None
        and evidence.observed_on > evidence.decision_date_cutoff
    ):
        blockers.append("RISK_SOURCE_OBSERVATION_DATE_AFTER_CUTOFF")
    if requested_purpose not in evidence.allowed_purposes:
        blockers.append("RISK_SOURCE_PURPOSE_NOT_ALLOWED")
    if evidence.must_not_use_for_decision:
        blockers.append("RISK_SOURCE_PROHIBITED_FOR_DECISION")
    if _is_prohibited_restriction(evidence.source_purpose):
        blockers.append("RISK_SOURCE_PROHIBITED_PURPOSE")
    for restriction in evidence.restrictions:
        if _is_prohibited_restriction(restriction):
            blockers.append("RISK_SOURCE_PROHIBITED_RESTRICTION")
        elif restriction not in allowed_restrictions:
            blockers.append("RISK_SOURCE_RESTRICTION_NOT_ALLOWED")
    reason_codes = tuple(dict.fromkeys(blockers))
    return PortfolioRiskSourceQualification(
        eligible=not reason_codes,
        reason_codes=reason_codes,
    )


def _policy_clock_proof_matches_source(
    *,
    evidence: PortfolioRiskSourceEvidence,
    proof: (
        PortfolioRiskDateSnapshotProof
        | PortfolioRiskTimestampSnapshotProof
        | PortfolioRiskCloseSnapshotStateProof
        | None
    ),
    expected_source_kind: str | None,
    as_of: datetime,
    requested_purpose: str,
    allowed_restrictions: tuple[str, ...],
) -> bool:
    """Permit only an exact configured proof matching this source's narrow mode."""

    if type(proof) is PortfolioRiskDateSnapshotProof:
        return (
            expected_source_kind == "industry_membership"
            and proof.scope == "simulation_only"
            and proof.source_kind == "industry_membership"
            and proof.clock_evidence_mode == "policy_bounded_date_snapshot"
            and proof.as_of == as_of == evidence.decision_cutoff
            and proof.source_id == evidence.source_id
            and proof.source_record_id == evidence.source_record_id
            and proof.original_body_sha256 == evidence.original_payload_sha256
            and proof.observed_on == evidence.observed_on == evidence.decision_date_cutoff
            and proof.business_date == evidence.decision_date_cutoff
            and proof.known_at == evidence.known_at
            and evidence.known_at is not None
            and proof.proven_available_at <= evidence.known_at
            and evidence.observation_precision is SourceObservationPrecision.DATE
            and evidence.available_at is None
            and evidence.valid_until is None
            and proof.source_available_at is None
            and proof.source_valid_until is None
            and proof.effective_from == evidence.effective_on == proof.business_date
            and proof.effective_until == evidence.effective_until == proof.business_date
            and proof.coverage_status == evidence.coverage.status.value
            and proof.coverage_precision_basis == evidence.coverage.precision_basis
            and proof.policy_acceptance_deadline > as_of
        )
    if type(proof) is PortfolioRiskTimestampSnapshotProof:
        if expected_source_kind != proof.source_kind:
            return False
        return (
            proof.scope == "simulation_only"
            and proof.clock_evidence_mode == "policy_bounded_timestamp_snapshot"
            and proof.as_of == as_of == evidence.decision_cutoff
            and proof.source_id == evidence.source_id
            and proof.source_record_id == evidence.source_record_id
            and proof.original_body_sha256 == evidence.original_payload_sha256
            and proof.observed_at == evidence.observed_at
            and proof.known_at == evidence.known_at
            and evidence.known_at is not None
            and proof.proven_available_at <= evidence.known_at
            and evidence.observation_precision is SourceObservationPrecision.TIMESTAMP
            and evidence.observed_on is None
            and evidence.available_at is None
            and evidence.valid_until is None
            and proof.source_available_at is None
            and proof.source_valid_until is None
            and proof.timestamp_age_deadline
            == proof.observed_at + timedelta(seconds=proof.source_max_timestamp_age_seconds)
            and proof.policy_acceptance_deadline > as_of
        )
    if type(proof) is PortfolioRiskCloseSnapshotStateProof:
        required_restrictions = set(proof.required_restrictions)
        return (
            expected_source_kind == "execution_session_state"
            and requested_purpose == proof.purpose == "close_snapshot_simulation"
            and required_restrictions <= set(allowed_restrictions)
            and required_restrictions <= set(evidence.restrictions)
            and proof.scope == "simulation_only"
            and proof.source_kind == "execution_session_state"
            and proof.clock_evidence_mode == "policy_bounded_close_snapshot_state"
            and proof.as_of == as_of == evidence.decision_cutoff
            and proof.source_id == evidence.source_id
            and proof.source_record_id == evidence.source_record_id
            and proof.original_body_sha256 == evidence.original_payload_sha256
            and proof.observed_at == evidence.observed_at
            and proof.known_at == evidence.known_at
            and evidence.known_at is not None
            and proof.proven_available_at <= evidence.known_at
            and evidence.observation_precision is SourceObservationPrecision.TIMESTAMP
            and evidence.observed_on is None
            and evidence.available_at is None
            and evidence.valid_until is None
            and proof.source_available_at is None
            and proof.source_valid_until is None
            and evidence.source_purpose == proof.purpose
            and proof.state_basis == "vendor_reported_at_quote_time"
            and proof.reported_trading_state == "TRADING"
            and proof.full_session_state == "unknown"
            and proof.policy_acceptance_deadline > as_of
        )
    return False


def _require_aware(value: datetime, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


def _require_fraction(value: Decimal, field_name: str) -> None:
    if type(value) is not Decimal or not value.is_finite() or not Decimal("0") <= value <= 1:
        raise ValueError(f"{field_name} must be an exact Decimal fraction in [0, 1]")


def _require_token(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a nonempty canonical token")


def _require_tokens(values: tuple[str, ...], field_name: str, *, allow_empty: bool = False) -> None:
    if type(values) is not tuple or (not allow_empty and not values):
        raise ValueError(f"{field_name} must be a nonempty tuple")
    for value in values:
        _require_token(value, field_name)
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} cannot contain duplicates")


def _is_prohibited_restriction(value: str) -> bool:
    normalized = value.lower()
    return (
        normalized.startswith("must_not_")
        or normalized.startswith("research_only")
        or normalized.startswith("observation_only")
    )


__all__ = (
    "CoverageStatus",
    "PortfolioRiskCoverage",
    "PortfolioRiskSourceEvidence",
    "PortfolioRiskSourceQualification",
    "SourceObservationPrecision",
    "qualify_portfolio_risk_source",
)
