"""Explicit, simulation-only acceptance of a captured same-day date snapshot.

This application helper is deliberately separate from generic source qualification
and execution deadlines. It never writes local receipt time into source-origin
``available_at`` or ``valid_until``. A caller must select the mode from a pinned
simulation policy reference and keep the returned proof with the risk report.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.risk_center.application.portfolio_risk_policy import (
    PortfolioRiskPolicyBundle,
    PortfolioRiskSourceReference,
)
from apps.risk_center.application.portfolio_risk_policy_deadline import (
    earliest_portfolio_risk_acceptance_deadline,
)
from apps.risk_center.domain.portfolio_exposure_types import (
    EffectiveEndState,
    IndustryMembership,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import (
    PortfolioRiskCaptureReceipt,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import (
    PortfolioRiskDateSnapshotProof as DomainPortfolioRiskDateSnapshotProof,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PortfolioRiskClockEvidenceMode(StrEnum):
    """Policy-selected clock qualification; strict source clocks remain the default."""

    SOURCE_CLOCKS_REQUIRED = "source_clocks_required"
    POLICY_BOUNDED_DATE_SNAPSHOT = "policy_bounded_date_snapshot"
    POLICY_BOUNDED_TIMESTAMP_SNAPSHOT = "policy_bounded_timestamp_snapshot"
    POLICY_BOUNDED_CLOSE_SNAPSHOT_STATE = "policy_bounded_close_snapshot_state"


@dataclass(frozen=True, slots=True)
class PortfolioRiskDateSnapshotProof:
    """Lossless eligibility proof, separate from source-origin clocks."""

    profile_key: str
    profile_version: int
    profile_content_hash: str
    policy_snapshot_id: str
    policy_snapshot_hash: str
    policy_content_sha256: str
    policy_known_at: datetime
    policy_effective_at: datetime
    source_reference_hash: str
    clock_evidence_mode: str
    capture_id: str
    account_id: int
    asset_code: str
    security_id: str
    source_id: str
    source_record_id: str
    original_body_sha256: str
    as_of: datetime
    business_date: date
    known_at: datetime
    proven_available_at: datetime
    http_status: int
    body_size_bytes: int
    body_complete: bool
    observed_on: date
    effective_from: date
    effective_until: date
    business_timezone_name: str
    coverage_status: CoverageStatus
    coverage_precision_basis: str
    source_max_date_age_days: int
    date_age_deadline: datetime
    membership_deadline: datetime
    policy_deadlines: tuple[datetime, ...]
    policy_acceptance_deadline: datetime
    source_available_at: datetime | None
    source_valid_until: datetime | None

    def to_domain(self) -> DomainPortfolioRiskDateSnapshotProof:
        """Return the immutable Domain form attached to source evidence."""

        return DomainPortfolioRiskDateSnapshotProof(
            scope="simulation_only",
            source_kind="industry_membership",
            clock_evidence_mode="policy_bounded_date_snapshot",
            profile_key=self.profile_key,
            profile_version=self.profile_version,
            profile_content_hash=self.profile_content_hash,
            policy_snapshot_id=self.policy_snapshot_id,
            policy_snapshot_hash=self.policy_snapshot_hash,
            policy_content_sha256=self.policy_content_sha256,
            policy_known_at=self.policy_known_at,
            policy_effective_at=self.policy_effective_at,
            source_reference_hash=self.source_reference_hash,
            account_id=self.account_id,
            asset_code=self.asset_code,
            security_id=self.security_id,
            source_id=self.source_id,
            source_record_id=self.source_record_id,
            capture_id=self.capture_id,
            original_body_sha256=self.original_body_sha256,
            as_of=self.as_of,
            business_date=self.business_date,
            known_at=self.known_at,
            proven_available_at=self.proven_available_at,
            http_status=self.http_status,
            body_size_bytes=self.body_size_bytes,
            body_complete=self.body_complete,
            observed_on=self.observed_on,
            effective_from=self.effective_from,
            effective_until=self.effective_until,
            business_timezone_name=self.business_timezone_name,
            coverage_status=cast(Literal["complete", "partial"], self.coverage_status.value),
            coverage_precision_basis=self.coverage_precision_basis,
            source_max_date_age_days=self.source_max_date_age_days,
            date_age_deadline=self.date_age_deadline,
            membership_deadline=self.membership_deadline,
            policy_deadlines=self.policy_deadlines,
            policy_acceptance_deadline=self.policy_acceptance_deadline,
            source_available_at=None,
            source_valid_until=None,
        )

    def __post_init__(self) -> None:
        """Reject any proof that cannot be replayed against its explicit bounds."""

        for name, value in (
            ("profile_key", self.profile_key),
            ("policy_snapshot_id", self.policy_snapshot_id),
            ("asset_code", self.asset_code),
            ("security_id", self.security_id),
            ("source_id", self.source_id),
            ("source_record_id", self.source_record_id),
            ("capture_id", self.capture_id),
            ("business_timezone_name", self.business_timezone_name),
            ("coverage_precision_basis", self.coverage_precision_basis),
        ):
            _require_token(value, name)
        for name, value in (
            ("policy_snapshot_hash", self.policy_snapshot_hash),
            ("policy_content_sha256", self.policy_content_sha256),
            ("profile_content_hash", self.profile_content_hash),
            ("original_body_sha256", self.original_body_sha256),
        ):
            if type(value) is not str or _SHA256.fullmatch(value) is None:
                raise ValueError(f"{name} must be lowercase SHA-256 hex")
        if type(self.source_reference_hash) is not str or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.source_reference_hash
        ):
            raise ValueError("source_reference_hash must be a prefixed SHA-256")
        if type(self.profile_version) is not int or self.profile_version < 1:
            raise ValueError("profile_version must be positive")
        if type(self.account_id) is not int or self.account_id < 1:
            raise ValueError("account_id must be a positive exact integer")
        if self.clock_evidence_mode != PortfolioRiskClockEvidenceMode.POLICY_BOUNDED_DATE_SNAPSHOT:
            raise ValueError("proof clock mode is unsupported")
        for clock_name, clock_value in (
            ("as_of", self.as_of),
            ("known_at", self.known_at),
            ("policy_known_at", self.policy_known_at),
            ("policy_effective_at", self.policy_effective_at),
            ("proven_available_at", self.proven_available_at),
            ("date_age_deadline", self.date_age_deadline),
            ("membership_deadline", self.membership_deadline),
            ("policy_acceptance_deadline", self.policy_acceptance_deadline),
        ):
            _require_aware(clock_value, clock_name)
        if type(self.policy_deadlines) is not tuple or any(
            type(value) is not datetime or not _is_aware(value) for value in self.policy_deadlines
        ):
            raise ValueError("policy_deadlines must contain aware instants")
        if type(self.business_date) is not date or type(self.observed_on) is not date:
            raise TypeError("business_date and observed_on must be exact dates")
        if self.observed_on != self.business_date or self.effective_from != self.business_date:
            raise ValueError("proof must bind one exact business-date observation")
        if self.effective_until != self.business_date:
            raise ValueError("proof must bind an inclusive same-day effective end")
        if self.known_at < self.proven_available_at or self.proven_available_at > self.as_of:
            raise ValueError("proof capture and known clocks are inconsistent")
        if self.policy_known_at > self.as_of or self.policy_effective_at > self.as_of:
            raise ValueError("proof policy was not known and effective by cutoff")
        try:
            named_timezone = ZoneInfo(self.business_timezone_name)
        except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("business_timezone_name must resolve to an IANA timezone") from exc
        if self.business_date != self.as_of.astimezone(named_timezone).date():
            raise ValueError("proof business date differs from the named timezone")
        if type(self.http_status) is not int or not 200 <= self.http_status < 300:
            raise ValueError("proof must bind a successful HTTP response")
        if (
            type(self.body_size_bytes) is not int
            or self.body_size_bytes < 1
            or type(self.body_complete) is not bool
            or not self.body_complete
        ):
            raise ValueError("proof must bind a complete nonempty response body")
        if type(self.source_max_date_age_days) is not int or self.source_max_date_age_days < 0:
            raise ValueError("source_max_date_age_days must be nonnegative")
        if not isinstance(self.coverage_status, CoverageStatus):
            raise TypeError("coverage_status must be CoverageStatus")
        if self.coverage_status is CoverageStatus.UNKNOWN:
            raise ValueError("unknown coverage cannot have a qualified date proof")
        if self.source_available_at is not None or self.source_valid_until is not None:
            raise ValueError("special proof cannot rewrite or replace source-origin clocks")
        candidate_deadlines = (
            self.date_age_deadline,
            self.membership_deadline,
            *self.policy_deadlines,
        )
        if self.policy_acceptance_deadline != min(candidate_deadlines):
            raise ValueError("policy_acceptance_deadline must be the exact earliest bound")
        if self.policy_acceptance_deadline <= self.as_of:
            raise ValueError("proof acceptance deadline must be in the future")


@dataclass(frozen=True, slots=True)
class PortfolioRiskDateSnapshotQualification:
    """Qualification result plus a proof only when every scoped gate passes."""

    qualified: bool
    reason_codes: tuple[str, ...]
    proof: PortfolioRiskDateSnapshotProof | None

    def __post_init__(self) -> None:
        """Keep result status and proof/reason presence consistent."""

        if type(self.qualified) is not bool:
            raise TypeError("qualified must be a boolean")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or not code.strip() for code in self.reason_codes
        ):
            raise ValueError("reason_codes must be a tuple of stable codes")
        if self.qualified == bool(self.reason_codes):
            raise ValueError("qualified result and reason codes are inconsistent")
        if self.qualified != (self.proof is not None):
            raise ValueError("qualified result and proof presence are inconsistent")


def qualify_policy_bounded_industry_date_snapshot(
    *,
    clock_evidence_mode: PortfolioRiskClockEvidenceMode,
    policy: PortfolioRiskPolicyBundle,
    source_reference: PortfolioRiskSourceReference,
    retained_payload_hash: str,
    account_id: int,
    asset_code: str,
    security_id: str,
    membership: IndustryMembership,
    receipt: PortfolioRiskCaptureReceipt | None,
    original_body: bytes,
    as_of: datetime,
    business_date: date,
    business_timezone: tzinfo,
    business_timezone_name: str,
    additional_policy_deadlines: tuple[datetime, ...] = (),
) -> PortfolioRiskDateSnapshotQualification:
    """Qualify one pinned same-day bounded industry fact for simulation risk only.

    The policy may replace only the two missing source-origin clocks
    ``available_at`` and ``valid_until`` with a transport receipt and a separately
    derived acceptance deadline. All other generic source blockers remain active.
    The retained-input reader attaches the returned proof to immutable source
    evidence. Domain exposure, report serialization and the simulated execution
    deadline independently revalidate that proof; generic source qualification
    and all other source kinds retain the original strict clock requirements.
    """

    reasons: list[str] = []
    if type(clock_evidence_mode) is not PortfolioRiskClockEvidenceMode:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_CLOCK_MODE_INVALID")
    elif clock_evidence_mode is not PortfolioRiskClockEvidenceMode.POLICY_BOUNDED_DATE_SNAPSHOT:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_CLOCK_MODE_NOT_ENABLED")
    if type(policy) is not PortfolioRiskPolicyBundle or policy.scope != "simulation_only":
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_SCOPE_NOT_SIMULATION_ONLY")
    if type(account_id) is not int or account_id < 1:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_ACCOUNT_ID_INVALID")
    elif type(source_reference) is not PortfolioRiskSourceReference:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_REFERENCE_INVALID")
    elif source_reference.kind != "industry_membership":
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_KIND_NOT_ALLOWED")
    else:
        if source_reference.clock_evidence_mode != clock_evidence_mode.value:
            reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_POLICY_MODE_MISMATCH")
        if source_reference not in policy.source_references:
            reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_REFERENCE_NOT_PINNED")
        if source_reference.asset_code != asset_code or source_reference.security_id != security_id:
            reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_ASSET_SCOPE_MISMATCH")
        if source_reference.raw_payload_hash != retained_payload_hash:
            reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_MANIFEST_PIN_MISMATCH")
    if type(membership) is not IndustryMembership:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_MEMBERSHIP_INVALID")
    if receipt is None or type(receipt) is not PortfolioRiskCaptureReceipt:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_CAPTURE_PROOF_UNKNOWN")
    if type(original_body) is not bytes or not original_body:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_ORIGINAL_BODY_UNKNOWN")
    if type(as_of) is not datetime or not _is_aware(as_of):
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_CUTOFF_INVALID")
    if type(business_date) is not date:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_BUSINESS_DATE_INVALID")
    if not isinstance(business_timezone, tzinfo):
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_TIMEZONE_UNKNOWN")
    if (
        type(business_timezone_name) is not str
        or not business_timezone_name.strip()
        or business_timezone_name.strip() != business_timezone_name
    ):
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_TIMEZONE_NAME_UNKNOWN")
    elif not _timezone_binding_matches(
        business_timezone,
        business_timezone_name,
        business_date,
        policy.source_max_date_age_days if type(policy) is PortfolioRiskPolicyBundle else 0,
    ):
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_TIMEZONE_BINDING_MISMATCH")
    if type(additional_policy_deadlines) is not tuple:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_POLICY_DEADLINES_INVALID")

    if reasons:
        return _blocked(reasons)

    receipt = cast(PortfolioRiskCaptureReceipt, receipt)
    if account_id not in policy.account_ids:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_ACCOUNT_SCOPE_MISMATCH")
    if policy.as_of != as_of or policy.business_date != business_date:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_POLICY_CUTOFF_MISMATCH")
    try:
        named_timezone = ZoneInfo(business_timezone_name)
        if as_of.astimezone(named_timezone).date() != business_date:
            reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_TIMEZONE_DATE_MISMATCH")
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_TIMEZONE_UNKNOWN")
    if source_reference.kind != "industry_membership":
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_KIND_NOT_ALLOWED")
    if membership.source_evidence.source_record_id != source_reference.source_record_id:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_RECORD_ID_MISMATCH")
    if membership.source_evidence.source_id != receipt.source_id:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_SOURCE_ID_MISMATCH")
    if membership.source_evidence.source_record_id != receipt.source_record_id:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_RECEIPT_RECORD_MISMATCH")
    if (
        membership.source_evidence.original_payload_sha256 != receipt.original_body_sha256
        or hashlib.sha256(original_body).hexdigest() != receipt.original_body_sha256
        or len(original_body) != receipt.body_size_bytes
    ):
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_RECEIPT_BODY_MISMATCH")
    if not receipt.body_complete:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_CAPTURE_INCOMPLETE")
    if receipt.http_status < 200 or receipt.http_status >= 300 or receipt.body_size_bytes < 1:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_CAPTURE_NOT_SUCCESSFUL")
    if receipt.response_completed_at > as_of:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_CAPTURE_AFTER_CUTOFF")

    evidence = membership.source_evidence
    if evidence.available_at is not None or evidence.valid_until is not None:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_SOURCE_CLOCK_MODE_CONFLICT")
    if evidence.known_at is None:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_KNOWN_AT_UNKNOWN")
    elif evidence.known_at < receipt.response_completed_at:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_KNOWN_BEFORE_RECEIPT")
    if evidence.observation_precision is not SourceObservationPrecision.DATE:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_OBSERVATION_PRECISION_NOT_DATE")
    if evidence.observed_on != business_date or evidence.decision_date_cutoff != business_date:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_OBSERVATION_DATE_MISMATCH")
    if evidence.effective_on != business_date or evidence.effective_until != business_date:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_SOURCE_EFFECTIVE_WINDOW_MISMATCH")
    if membership.effective_end_state is not EffectiveEndState.BOUNDED:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_MEMBERSHIP_NOT_BOUNDED")
    if membership.effective_from != business_date or membership.effective_until != business_date:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_MEMBERSHIP_NOT_SAME_DAY")
    industry_policy = policy.industry_policy
    if (
        membership.taxonomy_id != industry_policy.taxonomy_id
        or membership.taxonomy_kind != industry_policy.taxonomy_kind
        or membership.provider_id != industry_policy.provider_id
        or membership.provider_version != industry_policy.provider_version
    ):
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_TAXONOMY_BINDING_MISMATCH")
    if evidence.coverage.status is CoverageStatus.UNKNOWN:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_COVERAGE_UNKNOWN")
    if business_date != as_of.astimezone(business_timezone).date():
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_BUSINESS_DATE_NOT_CURRENT")

    qualification = qualify_portfolio_risk_source(
        evidence=evidence,
        requested_purpose=industry_policy.requested_purpose,
        allowed_observation_precisions=industry_policy.allowed_observation_precisions,
        as_of=as_of,
        allowed_restrictions=industry_policy.allowed_source_restrictions,
    )
    special_missing_clock_reasons = {
        "RISK_SOURCE_AVAILABLE_AT_UNKNOWN",
        "RISK_SOURCE_VALID_UNTIL_UNKNOWN",
    }
    reasons.extend(
        reason
        for reason in qualification.reason_codes
        if reason not in special_missing_clock_reasons
    )
    if (
        SourceObservationPrecision.DATE not in industry_policy.allowed_observation_precisions
        or industry_policy.requested_purpose not in industry_policy.date_precision_purposes
    ):
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_POLICY_PURPOSE_NOT_ALLOWED")
    if evidence.coverage.status is CoverageStatus.UNKNOWN:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_COVERAGE_UNKNOWN")
    if evidence.observed_on is None:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_OBSERVATION_DATE_UNKNOWN")
    elif business_date < evidence.observed_on:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_OBSERVATION_IN_FUTURE")
    elif (business_date - evidence.observed_on).days > policy.source_max_date_age_days:
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_DATE_AGE_EXCEEDED")
    if any(
        type(deadline) is not datetime or not _is_aware(deadline)
        for deadline in additional_policy_deadlines
    ):
        reasons.append("PORTFOLIO_RISK_DATE_SNAPSHOT_POLICY_DEADLINE_INVALID")

    if reasons:
        return _blocked(reasons)

    known_at = evidence.known_at
    if known_at is None:
        return _blocked(("PORTFOLIO_RISK_DATE_SNAPSHOT_KNOWN_AT_UNKNOWN",))

    try:
        date_age_deadline = _next_local_midnight(
            business_date + timedelta(days=policy.source_max_date_age_days), business_timezone
        )
        membership_deadline = _next_local_midnight(business_date, business_timezone)
        policy_deadlines = tuple(
            deadline.astimezone(UTC)
            for deadline in (
                industry_policy.effective_until,
                policy.capacity_policy.effective_until,
                *additional_policy_deadlines,
            )
            if deadline is not None
        )
        deadline = earliest_portfolio_risk_acceptance_deadline(
            as_of=as_of,
            policy_deadlines=(date_age_deadline, membership_deadline, *policy_deadlines),
            source_valid_until=evidence.valid_until,
        )
    except (OverflowError, TypeError, ValueError):
        deadline = None
        date_age_deadline = None
        membership_deadline = None
        policy_deadlines = ()
    if (
        deadline is None
        or date_age_deadline is None
        or membership_deadline is None
        or deadline <= as_of.astimezone(UTC)
    ):
        return _blocked(("PORTFOLIO_RISK_DATE_SNAPSHOT_ACCEPTANCE_WINDOW_EXPIRED",))

    proof = PortfolioRiskDateSnapshotProof(
        profile_key=policy.profile_key,
        profile_version=policy.profile_version,
        profile_content_hash=policy.profile_content_hash,
        policy_snapshot_id=policy.snapshot_id,
        policy_snapshot_hash=policy.snapshot_hash,
        policy_content_sha256=policy.normalized_config_sha256,
        policy_known_at=policy.known_at,
        policy_effective_at=policy.effective_at,
        source_reference_hash=source_reference.raw_payload_hash,
        clock_evidence_mode=clock_evidence_mode.value,
        capture_id=receipt.capture_id,
        account_id=account_id,
        asset_code=asset_code,
        security_id=security_id,
        source_id=evidence.source_id,
        source_record_id=evidence.source_record_id,
        original_body_sha256=receipt.original_body_sha256,
        as_of=as_of,
        business_date=business_date,
        known_at=known_at,
        proven_available_at=receipt.response_completed_at,
        http_status=receipt.http_status,
        body_size_bytes=receipt.body_size_bytes,
        body_complete=receipt.body_complete,
        observed_on=business_date,
        effective_from=membership.effective_from,
        effective_until=business_date,
        business_timezone_name=business_timezone_name,
        coverage_status=evidence.coverage.status,
        coverage_precision_basis=evidence.coverage.precision_basis,
        source_max_date_age_days=policy.source_max_date_age_days,
        date_age_deadline=date_age_deadline,
        membership_deadline=membership_deadline,
        policy_deadlines=policy_deadlines,
        policy_acceptance_deadline=deadline,
        source_available_at=evidence.available_at,
        source_valid_until=evidence.valid_until,
    )
    return PortfolioRiskDateSnapshotQualification(qualified=True, reason_codes=(), proof=proof)


def _next_local_midnight(day: date, business_timezone: tzinfo) -> datetime:
    """Return midnight after an inclusive business date in the configured zone."""

    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=business_timezone).astimezone(
        UTC
    )


def _blocked(reasons: list[str] | tuple[str, ...]) -> PortfolioRiskDateSnapshotQualification:
    """Create one stable fail-closed result from deduplicated reason codes."""

    codes = tuple(dict.fromkeys(reasons))
    if not codes:
        codes = ("PORTFOLIO_RISK_DATE_SNAPSHOT_UNQUALIFIED",)
    return PortfolioRiskDateSnapshotQualification(qualified=False, reason_codes=codes, proof=None)


def _is_aware(value: datetime) -> bool:
    """Return whether a datetime carries a real UTC offset."""

    return value.tzinfo is not None and value.utcoffset() is not None


def _require_aware(value: datetime, field_name: str) -> None:
    """Reject naive receipt timestamps without applying a timezone guess."""

    if type(value) is not datetime or not _is_aware(value):
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_token(value: str, field_name: str) -> None:
    """Require a canonical nonempty proof identity."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a nonempty canonical token")


def _timezone_binding_matches(
    business_timezone: tzinfo,
    timezone_name: str,
    business_date: date,
    date_age_days: int,
) -> bool:
    """Ensure the persisted IANA name represents the timezone used for bounds."""

    try:
        named_timezone = ZoneInfo(timezone_name)
        if isinstance(business_timezone, ZoneInfo):
            return business_timezone.key == named_timezone.key
        dates = (business_date, business_date + timedelta(days=date_age_days + 1))
        return all(
            datetime.combine(day, time.min, tzinfo=business_timezone).astimezone(UTC)
            == datetime.combine(day, time.min, tzinfo=named_timezone).astimezone(UTC)
            for day in dates
        )
    except (ArithmeticError, OverflowError, TypeError, ValueError, ZoneInfoNotFoundError):
        return False


__all__ = [
    "PortfolioRiskCaptureReceipt",
    "PortfolioRiskClockEvidenceMode",
    "PortfolioRiskDateSnapshotProof",
    "PortfolioRiskDateSnapshotQualification",
    "qualify_policy_bounded_industry_date_snapshot",
]
