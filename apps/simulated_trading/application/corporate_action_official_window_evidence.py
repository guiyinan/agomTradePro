"""Immutable original official-window evidence and read-only provider contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, TypeGuard

from apps.portfolio.domain.transition_plan_event_review import TransitionPlanEventRevision
from apps.simulated_trading.application.corporate_action_share_tax_proof import (
    ShareCapitalTaxQualificationProof,
)
from apps.simulated_trading.application.corporate_action_window_policy_provenance import (
    CorporateActionWindowPolicyProvenance,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_SZSE_ASSET_CODE = re.compile(r"[0-9]{6}\.SZ")


class CorporateActionCurrentOfficialWindowReason(StrEnum):
    """Stable outcomes for a read-only current-window prerequisite."""

    WINDOW_READY_PREREQUISITE_ONLY = "WINDOW_READY_PREREQUISITE_ONLY"
    REQUEST_INVALID = "REQUEST_INVALID"
    CUTOFF_INVALID = "CUTOFF_INVALID"
    CLOCK_UNAVAILABLE = "CLOCK_UNAVAILABLE"
    CLOCK_INVALID = "CLOCK_INVALID"
    CLOCK_AHEAD_OF_TRUSTED_NOW = "CLOCK_AHEAD_OF_TRUSTED_NOW"
    CLOCK_MOVED_BACKWARDS = "CLOCK_MOVED_BACKWARDS"
    OWNER_CALENDAR_UNAVAILABLE = "OWNER_CALENDAR_UNAVAILABLE"
    OWNER_CALENDAR_INVALID = "OWNER_CALENDAR_INVALID"
    CURRENT_DAY_CHANGED = "CURRENT_DAY_CHANGED"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    POLICY_CHANGED = "POLICY_CHANGED"
    SNAPSHOT_UNAVAILABLE = "SNAPSHOT_UNAVAILABLE"
    SNAPSHOT_INCOMPLETE = "SNAPSHOT_INCOMPLETE"
    SNAPSHOT_CHANGED = "SNAPSHOT_CHANGED"
    SOURCE_EVENT_MISSING = "SOURCE_EVENT_MISSING"
    SOURCE_EVENT_CHANGED = "SOURCE_EVENT_CHANGED"
    ORIGINAL_BODY_VERIFIER_UNAVAILABLE = "ORIGINAL_BODY_VERIFIER_UNAVAILABLE"
    ORIGINAL_BODY_UNVERIFIED = "ORIGINAL_BODY_UNVERIFIED"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"


class CorporateActionCurrentOfficialWindowClock(Protocol):
    """Supply the trusted aware wall clock used for start and finish checks."""

    def now(self) -> datetime:
        """Return one trusted timezone-aware current time."""
        ...


class ExchangeTimezoneEvidence(Protocol):
    """Structural shape of the exchange timezone evidence returned by Account."""

    @property
    def exchange(self) -> str:
        """Return the qualified exchange code."""
        ...

    @property
    def timezone_name(self) -> str:
        """Return the configured exchange timezone."""
        ...

    @property
    def policy_id(self) -> str:
        """Return the immutable timezone-policy identity."""
        ...

    @property
    def policy_sha256(self) -> str:
        """Return the immutable timezone-policy digest."""
        ...


class VerifiedAccountOriginCalendar(Protocol):
    """Structural shape of the Account-owned zero-origin date and timezone proof."""

    @property
    def origin_on(self) -> date:
        """Return the exact account-origin date in the exchange timezone."""
        ...

    @property
    def decision_on(self) -> date:
        """Return the exchange-local date at the supplied cutoff."""
        ...

    @property
    def timezone_policy(self) -> ExchangeTimezoneEvidence:
        """Return the qualified timezone policy evidence."""
        ...

    @property
    def as_of(self) -> datetime:
        """Return the exact cutoff used to read the calendar."""
        ...


class VerifiedAccountOriginCalendarReader(Protocol):
    """Read one exact physical account's immutable origin and exchange-local day."""

    def read_verified_zero_origin_calendar(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        exchange: str,
        as_of: datetime,
    ) -> VerifiedAccountOriginCalendar:
        """Return account-owned origin evidence or raise a typed scope failure."""
        ...


class OriginalDisclosureBodyVerifier(Protocol):
    """Verify one snapshot member against its retained original source body."""

    def verify_original_body(
        self,
        *,
        event: TransitionPlanEventRevision,
        body_store_root: Path,
    ) -> bool:
        """Return True only when the exact original body matches the event identity."""
        ...


@dataclass(frozen=True, slots=True)
class CorporateActionCurrentOfficialWindowEvidence:
    """Finite original source-window clocks and hashes; never decision authority."""

    window_ready: bool
    reason_code: CorporateActionCurrentOfficialWindowReason
    freshness_status: Literal["current", "stale", "unknown"] = "unknown"
    reliability_status: Literal["verified", "unverified"] = "unverified"
    must_not_use_for_decision: Literal[True] = True
    decision_use_reason: Literal["window_evidence_only"] = "window_evidence_only"
    account_id: int | None = None
    owner_user_id: int | None = None
    asset_code: str | None = None
    security_id: str | None = None
    source_record_id: str | None = None
    source_revision_id: str | None = None
    source_payload_sha256: str | None = None
    source_observed_at: datetime | None = None
    window_start_on: date | None = None
    window_end_on: date | None = None
    original_first_observed_at: datetime | None = None
    original_listing_verified_at: datetime | None = None
    original_proof_recorded_at: datetime | None = None
    checked_at: datetime | None = None
    expires_at: datetime | None = None
    runtime_environment: str | None = None
    policy_sha256: str | None = None
    calendar_policy_sha256: str | None = None
    scope_sha256: str | None = None
    selected_event_sha256: str | None = None
    policy_provenance: CorporateActionWindowPolicyProvenance | None = None
    share_tax_proof: ShareCapitalTaxQualificationProof | None = None

    def __post_init__(self) -> None:
        """Keep readiness and its explicit window-only warning inseparable."""

        if (
            type(self.window_ready) is not bool
            or type(self.reason_code) is not CorporateActionCurrentOfficialWindowReason
            or self.must_not_use_for_decision is not True
            or self.decision_use_reason != "window_evidence_only"
            or self.freshness_status
            != (
                "current"
                if self.window_ready
                else (
                    "stale"
                    if self.reason_code
                    in {
                        CorporateActionCurrentOfficialWindowReason.CURRENT_DAY_CHANGED,
                        CorporateActionCurrentOfficialWindowReason.WINDOW_EXPIRED,
                    }
                    else "unknown"
                )
            )
            or self.reliability_status != ("verified" if self.window_ready else "unverified")
            or self.window_ready
            != (
                self.reason_code
                is CorporateActionCurrentOfficialWindowReason.WINDOW_READY_PREREQUISITE_ONLY
            )
        ):
            raise ValueError("current official-window result status is inconsistent")
        if not self.window_ready:
            return
        if type(self.policy_provenance) is not CorporateActionWindowPolicyProvenance:
            raise ValueError(
                "ready current window requires full immutable configuration provenance"
            )
        self.policy_provenance.__post_init__()
        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
            or type(self.asset_code) is not str
            or _SZSE_ASSET_CODE.fullmatch(self.asset_code) is None
            or self.security_id != self.asset_code
            or type(self.source_record_id) is not str
            or not self.source_record_id
            or type(self.source_revision_id) is not str
            or not self.source_revision_id
            or not _is_sha256(self.source_payload_sha256)
            or not _is_aware(self.source_observed_at)
            or type(self.window_start_on) is not date
            or type(self.window_start_on) is datetime
            or type(self.window_end_on) is not date
            or type(self.window_end_on) is datetime
            or self.window_start_on > self.window_end_on
            or not _is_aware(self.original_first_observed_at)
            or not _is_aware(self.original_listing_verified_at)
            or not _is_aware(self.original_proof_recorded_at)
            or not _is_aware(self.checked_at)
            or not _is_aware(self.expires_at)
            or type(self.runtime_environment) is not str
            or not self.runtime_environment
            or not _is_sha256(self.policy_sha256)
            or not _is_sha256(self.calendar_policy_sha256)
            or not _is_sha256(self.scope_sha256)
            or not _is_sha256(self.selected_event_sha256)
        ):
            raise ValueError("ready current official-window evidence is incomplete")
        if (
            self.policy_provenance.policy_content_sha256 != self.policy_sha256
            or self.policy_provenance.runtime_environment != self.runtime_environment
            or self.policy_provenance.effective_at > self.checked_at
        ):
            raise ValueError("window configuration provenance crosses policy, environment or time")
        if not (
            self.original_first_observed_at
            <= self.original_listing_verified_at
            <= self.original_proof_recorded_at
            <= self.checked_at
            < self.expires_at
        ):
            raise ValueError("current official-window clocks are not ordered")
        if self.share_tax_proof is not None:
            self.share_tax_proof.__post_init__()
            proof = self.share_tax_proof
            if (
                proof.environment != self.runtime_environment
                or proof.query.physical_account_id != self.account_id
                or proof.query.owner_user_id != self.owner_user_id
                or proof.query.asset_code != self.asset_code
                or proof.query.source_record_id != self.source_record_id
                or proof.query.source_revision_id != self.source_revision_id
                or proof.query.source_payload_sha256 != self.source_payload_sha256
                or proof.checked_at > self.checked_at
                or self.expires_at > proof.valid_until
            ):
                raise ValueError("share model proof differs from its financial window scope")


def _is_token(value: object) -> TypeGuard[str]:
    """Return whether a value is a bounded canonical identity token."""

    return (
        type(value) is str
        and bool(value)
        and len(value) <= 256
        and value == value.strip()
        and not any(character.isspace() for character in value)
    )


def _is_sha256(value: object) -> TypeGuard[str]:
    """Require a lowercase SHA-256 digest."""

    return type(value) is str and _SHA256.fullmatch(value) is not None


def _is_aware(value: object) -> TypeGuard[datetime]:
    """Return whether a value is an exact timezone-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() is not None
    except (OverflowError, TypeError, ValueError):
        return False
