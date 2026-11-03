"""Qualify narrowly opted-in timestamp sources for simulated portfolio risk."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from decimal import Decimal
from typing import Literal, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.risk_center.application.portfolio_risk_policy import (
    PortfolioRiskPolicyBundle,
    PortfolioRiskSourceReference,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import (
    PortfolioRiskCaptureReceipt,
    PortfolioRiskTimestampSnapshotProof,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)

TimestampSnapshotKind = Literal["valuation", "capacity_window"]
CapacityMeasureValue = Literal["volume", "amount"]
_TypedValue = TypeVar("_TypedValue")


@dataclass(frozen=True, slots=True)
class PortfolioRiskTimestampSnapshotFacts:
    """Typed, parsed source facts used only to bind units and market window shape."""

    source_kind: TimestampSnapshotKind
    valuation_price: Decimal | None = None
    valuation_quantity_unit: str | None = None
    valuation_price_unit: str | None = None
    capacity_window_kind: str | None = None
    capacity_window_start: date | None = None
    capacity_window_end: date | None = None
    capacity_window_sessions: int | None = None
    capacity_volume_value: Decimal | None = None
    capacity_volume_unit: str | None = None
    capacity_amount_value: Decimal | None = None
    capacity_amount_unit: str | None = None
    capacity_measure: CapacityMeasureValue | None = None
    capacity_policy_unit: str | None = None

    def __post_init__(self) -> None:
        """Reject facts that mix valuation and capacity source shapes."""

        if self.source_kind not in ("valuation", "capacity_window"):
            raise ValueError("source_kind must be valuation or capacity_window")
        if self.source_kind == "valuation":
            if any(
                fact_value is not None
                for fact_value in (
                    self.capacity_window_kind,
                    self.capacity_window_start,
                    self.capacity_window_end,
                    self.capacity_window_sessions,
                    self.capacity_volume_value,
                    self.capacity_volume_unit,
                    self.capacity_amount_value,
                    self.capacity_amount_unit,
                    self.capacity_measure,
                    self.capacity_policy_unit,
                )
            ):
                raise ValueError("valuation facts cannot contain capacity-window fields")
            if self.valuation_price is not None and (
                type(self.valuation_price) is not Decimal or not self.valuation_price.is_finite()
            ):
                raise TypeError("valuation_price must be a finite Decimal or None")
            for unit_value in (self.valuation_quantity_unit, self.valuation_price_unit):
                if unit_value is not None and not _valid_token(unit_value):
                    raise ValueError("valuation units must be canonical tokens or None")
        elif any(
            value is not None
            for value in (
                self.valuation_price,
                self.valuation_quantity_unit,
                self.valuation_price_unit,
            )
        ):
            raise ValueError("capacity facts cannot contain valuation fields")
        if self.source_kind == "capacity_window":
            if self.capacity_window_kind is not None and not _valid_token(
                self.capacity_window_kind
            ):
                raise ValueError("capacity_window_kind must be a canonical token or None")
            if any(
                value is not None and type(value) is not date
                for value in (self.capacity_window_start, self.capacity_window_end)
            ):
                raise TypeError("capacity window dates must be exact dates or None")
            if (
                self.capacity_window_sessions is not None
                and type(self.capacity_window_sessions) is not int
            ):
                raise TypeError("capacity_window_sessions must be an exact integer or None")
            for source_value in (self.capacity_volume_value, self.capacity_amount_value):
                if source_value is not None and (
                    type(source_value) is not Decimal
                    or not source_value.is_finite()
                    or source_value < 0
                ):
                    raise ValueError("capacity source values must be finite nonnegative Decimals")
            for unit_value in (
                self.capacity_volume_unit,
                self.capacity_amount_unit,
                self.capacity_policy_unit,
            ):
                if unit_value is not None and not _valid_token(unit_value):
                    raise ValueError("capacity units must be canonical tokens or None")
            if self.capacity_measure not in (None, "volume", "amount"):
                raise ValueError("capacity_measure is unsupported")


@dataclass(frozen=True, slots=True)
class PortfolioRiskTimestampSnapshotQualification:
    """A typed proof exists only when every scope, clock, unit and window gate passes."""

    qualified: bool
    reason_codes: tuple[str, ...]
    proof: PortfolioRiskTimestampSnapshotProof | None

    def __post_init__(self) -> None:
        """Keep outcome, reason codes and proof presence consistent."""

        if type(self.qualified) is not bool:
            raise TypeError("qualified must be a boolean")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must be a tuple of stable codes")
        if self.qualified == bool(self.reason_codes):
            raise ValueError("qualification and reason codes are inconsistent")
        if self.qualified != (self.proof is not None):
            raise ValueError("qualification and proof presence are inconsistent")


def qualify_policy_bounded_timestamp_snapshot(
    *,
    policy: PortfolioRiskPolicyBundle,
    source_reference: PortfolioRiskSourceReference,
    retained_payload_hash: str,
    account_id: int,
    source_evidence: PortfolioRiskSourceEvidence,
    facts: PortfolioRiskTimestampSnapshotFacts,
    receipt: PortfolioRiskCaptureReceipt | None,
    original_body: bytes,
    as_of: datetime,
    business_date: date,
    execution_session: date,
    requested_purpose: str,
    asset_code: str,
    security_id: str,
    business_timezone: tzinfo,
    business_timezone_name: str,
) -> PortfolioRiskTimestampSnapshotQualification:
    """Replace only missing source availability/expiry clocks for an exact source.

    Original timestamp observations and known-at values remain untouched. A
    receipt and configured maximum-age bound form a separate proof, while all
    purpose, restriction, source-pin, unit, policy and market-window checks stay
    in force. Capacity is limited to one source-declared cumulative session.
    """

    reasons: list[str] = []
    if type(policy) is not PortfolioRiskPolicyBundle or policy.scope != "simulation_only":
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_SCOPE_NOT_SIMULATION_ONLY")
    if type(source_reference) is not PortfolioRiskSourceReference:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_REFERENCE_INVALID")
    if type(account_id) is not int or account_id < 1:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_ACCOUNT_ID_INVALID")
    if type(source_evidence) is not PortfolioRiskSourceEvidence:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_EVIDENCE_INVALID")
    if type(facts) is not PortfolioRiskTimestampSnapshotFacts:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_FACTS_INVALID")
    if type(receipt) is not PortfolioRiskCaptureReceipt:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_CAPTURE_UNKNOWN")
    if type(original_body) is not bytes or not original_body:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_ORIGINAL_BODY_UNKNOWN")
    if type(as_of) is not datetime or not _is_aware(as_of):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_CUTOFF_INVALID")
    if type(business_date) is not date or type(execution_session) is not date:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_SESSION_INVALID")
    if not isinstance(business_timezone, tzinfo):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_TIMEZONE_UNKNOWN")
    if not _valid_token(business_timezone_name):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_TIMEZONE_NAME_UNKNOWN")
    elif not _timezone_matches(business_timezone, business_timezone_name):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_TIMEZONE_MISMATCH")
    if not _valid_token(requested_purpose):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_PURPOSE_UNKNOWN")
    if not _valid_token(asset_code) or not _valid_token(security_id):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_ASSET_IDENTITY_UNKNOWN")
    if reasons:
        return _blocked(reasons)

    receipt = _typed(receipt, PortfolioRiskCaptureReceipt)
    evidence = _typed(source_evidence, PortfolioRiskSourceEvidence)
    facts = _typed(facts, PortfolioRiskTimestampSnapshotFacts)
    policy_purposes = (
        policy.capacity_policy.allowed_observation_precisions
        if facts.source_kind == "capacity_window"
        else policy.industry_policy.allowed_observation_precisions
    )
    policy_restrictions = (
        policy.capacity_policy.allowed_source_restrictions
        if facts.source_kind == "capacity_window"
        else policy.industry_policy.allowed_source_restrictions
    )
    if (
        facts.source_kind == "valuation"
        and requested_purpose != policy.industry_policy.requested_purpose
    ):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_PURPOSE_POLICY_MISMATCH")
    if policy.as_of != as_of or policy.business_date != business_date:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_POLICY_CUTOFF_MISMATCH")
    if account_id not in policy.account_ids:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_ACCOUNT_SCOPE_MISMATCH")
    if (
        source_reference.clock_evidence_mode != "policy_bounded_timestamp_snapshot"
        or source_reference not in policy.source_references
        or source_reference.kind != facts.source_kind
        or source_reference.asset_code != asset_code
        or source_reference.security_id != security_id
        or source_reference.raw_payload_hash != retained_payload_hash
        or source_reference.source_record_id != evidence.source_record_id
    ):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_POLICY_PIN_MISMATCH")
    if evidence.source_record_id != receipt.source_record_id:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_RECORD_ID_MISMATCH")
    if evidence.source_id != receipt.source_id:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_SOURCE_ID_MISMATCH")
    if evidence.policy_clock_proof is not None:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_PREEXISTING_PROOF")
    if (
        evidence.original_payload_sha256 != receipt.original_body_sha256
        or hashlib_sha256(original_body) != receipt.original_body_sha256
        or len(original_body) != receipt.body_size_bytes
    ):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_RECEIPT_BODY_MISMATCH")
    if (
        receipt.http_status < 200
        or receipt.http_status >= 300
        or not receipt.body_complete
        or receipt.body_size_bytes < 1
    ):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_CAPTURE_NOT_SUCCESSFUL")
    if receipt.response_completed_at > as_of:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_CAPTURE_AFTER_CUTOFF")
    if evidence.known_at is None:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_KNOWN_AT_UNKNOWN")
    elif receipt.response_completed_at > evidence.known_at:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_KNOWN_BEFORE_RECEIPT")
    if evidence.observation_precision is not SourceObservationPrecision.TIMESTAMP:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_PRECISION_NOT_TIMESTAMP")
    if evidence.observed_at is None or evidence.observed_on is not None:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_OBSERVATION_UNKNOWN")
    elif evidence.observed_at > as_of:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_OBSERVATION_AFTER_CUTOFF")
    if evidence.available_at is not None or evidence.valid_until is not None:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_SOURCE_CLOCK_MODE_CONFLICT")
    if as_of.astimezone(business_timezone).date() != business_date:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_BUSINESS_DATE_MISMATCH")
    if evidence.observed_at is not None and (
        evidence.observed_at.astimezone(business_timezone).date() != business_date
    ):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_OBSERVATION_DATE_MISMATCH")
    if evidence.observed_at is not None and evidence.observed_at > receipt.response_completed_at:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_OBSERVATION_AFTER_CAPTURE")
    if (
        source_reference.kind not in ("valuation", "capacity_window")
        or facts.source_kind != source_reference.kind
    ):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_KIND_UNSUPPORTED")

    if facts.source_kind == "valuation":
        _validate_valuation(policy, facts, reasons)
    else:
        _validate_capacity(policy, facts, business_date, execution_session, reasons)
    if requested_purpose not in evidence.allowed_purposes:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_PURPOSE_NOT_ALLOWED")
    if SourceObservationPrecision.TIMESTAMP not in policy_purposes:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_POLICY_PRECISION_NOT_ALLOWED")
    if evidence.observation_precision not in policy_purposes:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_POLICY_PRECISION_NOT_ALLOWED")
    if evidence.must_not_use_for_decision:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_PROHIBITED")
    age_seconds = policy.source_max_timestamp_age_seconds
    if evidence.observed_at is not None:
        if as_of - evidence.observed_at > timedelta(seconds=age_seconds):
            reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_AGE_EXCEEDED")
    qualification = qualify_portfolio_risk_source(
        evidence=evidence,
        requested_purpose=requested_purpose,
        allowed_observation_precisions=policy_purposes,
        as_of=as_of,
        allowed_restrictions=policy_restrictions,
    )
    reasons.extend(
        code
        for code in qualification.reason_codes
        if code not in {"RISK_SOURCE_AVAILABLE_AT_UNKNOWN", "RISK_SOURCE_VALID_UNTIL_UNKNOWN"}
    )
    if reasons:
        return _blocked(reasons)

    observed_at = _typed(evidence.observed_at, datetime)
    try:
        timestamp_age_deadline = observed_at + timedelta(seconds=age_seconds)
        market_window_deadline = datetime.combine(
            business_date + timedelta(days=1), time.min, tzinfo=business_timezone
        ).astimezone(UTC)
        policy_deadlines = tuple(
            deadline.astimezone(UTC)
            for deadline in (
                policy.industry_policy.effective_until,
                policy.capacity_policy.effective_until,
            )
            if deadline is not None
        )
        deadline = min((timestamp_age_deadline, market_window_deadline, *policy_deadlines))
    except (ArithmeticError, OverflowError, TypeError, ValueError):
        return _blocked(("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_DEADLINE_INVALID",))
    if deadline <= as_of.astimezone(UTC):
        return _blocked(("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_DEADLINE_EXPIRED",))
    proof = PortfolioRiskTimestampSnapshotProof(
        scope="simulation_only",
        source_kind=facts.source_kind,
        clock_evidence_mode="policy_bounded_timestamp_snapshot",
        profile_key=policy.profile_key,
        profile_version=policy.profile_version,
        profile_content_hash=policy.profile_content_hash,
        policy_snapshot_id=policy.snapshot_id,
        policy_snapshot_hash=policy.snapshot_hash,
        policy_content_sha256=policy.normalized_config_sha256,
        policy_known_at=policy.known_at,
        policy_effective_at=policy.effective_at,
        source_reference_hash=source_reference.raw_payload_hash,
        account_id=account_id,
        asset_code=source_reference.asset_code,
        security_id=source_reference.security_id,
        source_id=evidence.source_id,
        source_record_id=evidence.source_record_id,
        capture_id=receipt.capture_id,
        original_body_sha256=receipt.original_body_sha256,
        as_of=as_of,
        business_date=business_date,
        execution_session=execution_session,
        known_at=_typed(evidence.known_at, datetime),
        proven_available_at=receipt.response_completed_at,
        observed_at=observed_at,
        http_status=receipt.http_status,
        body_size_bytes=receipt.body_size_bytes,
        body_complete=receipt.body_complete,
        business_timezone_name=business_timezone_name,
        source_max_timestamp_age_seconds=age_seconds,
        timestamp_age_deadline=timestamp_age_deadline,
        market_window_deadline=market_window_deadline,
        policy_deadlines=policy_deadlines,
        policy_acceptance_deadline=deadline,
        valuation_quantity_unit=facts.valuation_quantity_unit,
        valuation_price_unit=facts.valuation_price_unit,
        capacity_window_kind=(
            "session_cumulative" if facts.capacity_window_kind == "session_cumulative" else None
        ),
        capacity_window_start=facts.capacity_window_start,
        capacity_window_end=facts.capacity_window_end,
        capacity_window_sessions=facts.capacity_window_sessions,
        capacity_volume_unit=facts.capacity_volume_unit,
        capacity_amount_unit=facts.capacity_amount_unit,
        capacity_measure=facts.capacity_measure,
        capacity_policy_unit=facts.capacity_policy_unit,
        source_available_at=None,
        source_valid_until=None,
    )
    return PortfolioRiskTimestampSnapshotQualification(qualified=True, reason_codes=(), proof=proof)


def _validate_valuation(
    policy: PortfolioRiskPolicyBundle,
    facts: PortfolioRiskTimestampSnapshotFacts,
    reasons: list[str],
) -> None:
    """Require an actual positive price and the configured ledger/quantity units."""

    if facts.valuation_price is None:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_PRICE_UNKNOWN")
    elif (
        type(facts.valuation_price) is not Decimal
        or not facts.valuation_price.is_finite()
        or facts.valuation_price <= 0
    ):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_PRICE_NONPOSITIVE")
    if not _valid_token(facts.valuation_quantity_unit):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_QUANTITY_UNIT_UNKNOWN")
    if facts.valuation_price_unit != policy.ledger_money_unit:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_PRICE_UNIT_MISMATCH")


def _validate_capacity(
    policy: PortfolioRiskPolicyBundle,
    facts: PortfolioRiskTimestampSnapshotFacts,
    business_date: date,
    execution_session: date,
    reasons: list[str],
) -> None:
    """Require one same-session cumulative window and the explicitly selected unit."""

    capacity = policy.capacity_policy
    if (
        capacity.window_kind != "session_cumulative"
        or capacity.window_sessions != 1
        or capacity.capacity_basis != "session_total"
        or facts.capacity_window_kind != "session_cumulative"
        or facts.capacity_window_start != execution_session
        or facts.capacity_window_end != execution_session
        or facts.capacity_window_sessions != 1
        or execution_session != business_date
    ):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_CAPACITY_WINDOW_NOT_CURRENT_SESSION")
    source_unit = (
        facts.capacity_volume_unit if capacity.measure == "volume" else facts.capacity_amount_unit
    )
    source_value = (
        facts.capacity_volume_value if capacity.measure == "volume" else facts.capacity_amount_value
    )
    if (
        facts.capacity_measure != capacity.measure
        or facts.capacity_policy_unit != capacity.unit
        or source_unit != capacity.unit
    ):
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_CAPACITY_UNIT_MISMATCH")
    if type(source_value) is not Decimal or not source_value.is_finite() or source_value < 0:
        reasons.append("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_CAPACITY_VALUE_UNKNOWN")


def _timezone_matches(business_timezone: tzinfo, timezone_name: str) -> bool:
    """Require the injected timezone to have the exact persisted IANA key."""

    try:
        named = ZoneInfo(timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return False
    key = getattr(business_timezone, "key", None)
    return type(key) is str and key == named.key


def _valid_token(value: str | None) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value.strip() == value
        and not any(character.isspace() for character in value)
    )


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _blocked(reasons: list[str] | tuple[str, ...]) -> PortfolioRiskTimestampSnapshotQualification:
    codes = tuple(dict.fromkeys(reasons))
    if not codes:
        codes = ("PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_UNQUALIFIED",)
    return PortfolioRiskTimestampSnapshotQualification(False, codes, None)


def _typed(value: object, value_type: type[_TypedValue]) -> _TypedValue:
    if type(value) is not value_type:
        raise TypeError("typed value mismatch")
    return value


def hashlib_sha256(value: bytes) -> str:
    """Return the exact lowercase hash of a captured original response body."""

    return hashlib.sha256(value).hexdigest()
