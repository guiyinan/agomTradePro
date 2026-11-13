"""Read a finite, non-authorizing SZSE disclosure-window prerequisite."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, TypeGuard, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.portfolio.application.transition_plan_event_review import (
    TransitionPlanEventSnapshotReader,
    TransitionPlanEventSnapshotReadError,
    TransitionPlanEventSnapshotReadRequest,
    TransitionPlanEventSourceRevisionChanged,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventAssetSnapshot,
    TransitionPlanEventCoverageLeasePolicy,
    TransitionPlanEventCoverageStatus,
    TransitionPlanEventRevision,
)
from apps.simulated_trading.application.corporate_action_current_official_window_contracts import (
    OfficialWindowRuntimePolicyReader,
    TransitionPlanDisclosureRuntimePolicy,
)
from apps.simulated_trading.domain.corporate_action_posting import CorporateActionStageRequest
from core.exceptions import AgomTradeProException

_SZSE_SOURCE_ID = "szse_official"
_SZSE_EXCHANGE = "SZSE"
_OFFICIAL_ACTION_NAMESPACE = "exchange_official_disclosure"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SZSE_ASSET_CODE = re.compile(r"[0-9]{6}\.SZ")
_MAXIMUM_WINDOW_LEASE = timedelta(seconds=60)


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
        if not (
            self.original_first_observed_at
            <= self.original_listing_verified_at
            <= self.original_proof_recorded_at
            <= self.checked_at
            < self.expires_at
        ):
            raise ValueError("current official-window clocks are not ordered")


class CorporateActionCurrentOfficialWindowReader:
    """Recheck active policy and latest complete SZSE proof without granting authority."""

    def __init__(
        self,
        *,
        origin_reader: VerifiedAccountOriginCalendarReader,
        policy_reader: OfficialWindowRuntimePolicyReader,
        snapshot_reader: TransitionPlanEventSnapshotReader,
        original_body_verifier: OriginalDisclosureBodyVerifier | None,
        runtime_environment: str,
        clock: CorporateActionCurrentOfficialWindowClock,
    ) -> None:
        """Bind explicit read-only public ports, verifier, environment, and trusted clock."""

        if (
            not callable(getattr(origin_reader, "read_verified_zero_origin_calendar", None))
            or not callable(getattr(policy_reader, "read_policy", None))
            or not callable(getattr(snapshot_reader, "read_latest_snapshot", None))
            or not _is_token(runtime_environment)
            or not callable(getattr(clock, "now", None))
            or (
                original_body_verifier is not None
                and not callable(getattr(original_body_verifier, "verify_original_body", None))
            )
        ):
            raise ValueError("current official-window reader dependencies are invalid")
        self._origin_reader = origin_reader
        self._policy_reader = policy_reader
        self._snapshot_reader = snapshot_reader
        self._original_body_verifier = original_body_verifier
        self._runtime_environment = runtime_environment
        self._clock = clock

    def read_current(
        self,
        request: CorporateActionStageRequest,
        *,
        as_of: datetime,
    ) -> CorporateActionCurrentOfficialWindowEvidence:
        """Return finite exact-window evidence only while policy, source, and clocks agree."""

        try:
            started_at = self._clock.now()
        except (
            AgomTradeProException,
            ArithmeticError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return _blocked(request, CorporateActionCurrentOfficialWindowReason.CLOCK_UNAVAILABLE)
        if not _is_aware(started_at):
            return _blocked(request, CorporateActionCurrentOfficialWindowReason.CLOCK_INVALID)
        if not _is_aware(as_of):
            return _blocked(
                request,
                CorporateActionCurrentOfficialWindowReason.CUTOFF_INVALID,
                checked_at=started_at,
            )
        if as_of > started_at:
            return _blocked(
                request,
                CorporateActionCurrentOfficialWindowReason.CLOCK_AHEAD_OF_TRUSTED_NOW,
                checked_at=started_at,
            )
        if not _valid_request(request, as_of=as_of):
            return self._finish_block(
                request,
                CorporateActionCurrentOfficialWindowReason.REQUEST_INVALID,
                started_at=started_at,
            )

        initial, reason = self._read_window(request, as_of=as_of)
        if initial is None:
            return self._finish_block(request, reason, started_at=started_at)
        if not _same_exchange_day(
            started_at,
            initial.calendar.timezone_policy.timezone_name,
            initial.calendar.decision_on,
        ):
            return self._finish_block(
                request,
                CorporateActionCurrentOfficialWindowReason.CURRENT_DAY_CHANGED,
                started_at=started_at,
            )
        if started_at >= initial.expires_at:
            return self._finish_block(
                request,
                CorporateActionCurrentOfficialWindowReason.WINDOW_EXPIRED,
                started_at=started_at,
            )

        final_read_at, clock_reason = self._finish_clock(started_at)
        if final_read_at is None:
            return _blocked(request, clock_reason, checked_at=started_at)
        if final_read_at >= initial.expires_at:
            return _blocked(
                request,
                CorporateActionCurrentOfficialWindowReason.WINDOW_EXPIRED,
                checked_at=final_read_at,
            )
        if not _same_exchange_day(
            final_read_at,
            initial.calendar.timezone_policy.timezone_name,
            initial.calendar.decision_on,
        ):
            return _blocked(
                request,
                CorporateActionCurrentOfficialWindowReason.CURRENT_DAY_CHANGED,
                checked_at=final_read_at,
            )

        final, final_reason = self._read_window(request, as_of=final_read_at)
        if final is None:
            return _blocked(request, final_reason, checked_at=final_read_at)

        body_completed_at, clock_reason = self._finish_clock(final_read_at)
        if body_completed_at is None:
            return _blocked(request, clock_reason, checked_at=final_read_at)
        if body_completed_at >= initial.expires_at:
            return _blocked(
                request,
                CorporateActionCurrentOfficialWindowReason.WINDOW_EXPIRED,
                checked_at=body_completed_at,
            )
        if not _same_exchange_day(
            body_completed_at,
            initial.calendar.timezone_policy.timezone_name,
            initial.calendar.decision_on,
        ):
            return _blocked(
                request,
                CorporateActionCurrentOfficialWindowReason.CURRENT_DAY_CHANGED,
                checked_at=body_completed_at,
            )

        metadata, metadata_reason = self._read_window(
            request,
            as_of=body_completed_at,
            verify_original_bodies=False,
        )
        if metadata is None:
            return _blocked(request, metadata_reason, checked_at=body_completed_at)

        completed_at, clock_reason = self._finish_clock(body_completed_at)
        if completed_at is None:
            return _blocked(request, clock_reason, checked_at=body_completed_at)
        if completed_at >= initial.expires_at:
            return _blocked(
                request,
                CorporateActionCurrentOfficialWindowReason.WINDOW_EXPIRED,
                checked_at=completed_at,
            )
        if not _same_exchange_day(
            completed_at,
            initial.calendar.timezone_policy.timezone_name,
            initial.calendar.decision_on,
        ):
            return _blocked(
                request,
                CorporateActionCurrentOfficialWindowReason.CURRENT_DAY_CHANGED,
                checked_at=completed_at,
            )

        for previous, current in ((initial, final), (final, metadata)):
            if previous.calendar.decision_on != current.calendar.decision_on:
                return _blocked(
                    request,
                    CorporateActionCurrentOfficialWindowReason.CURRENT_DAY_CHANGED,
                    checked_at=completed_at,
                )
            if not _same_calendar(previous.calendar, current.calendar):
                return _blocked(
                    request,
                    CorporateActionCurrentOfficialWindowReason.OWNER_CALENDAR_INVALID,
                    checked_at=completed_at,
                )
            if _policy_identity(previous.policy) != _policy_identity(current.policy):
                return _blocked(
                    request,
                    CorporateActionCurrentOfficialWindowReason.POLICY_CHANGED,
                    checked_at=completed_at,
                )
            if previous.snapshot != current.snapshot:
                return _blocked(
                    request,
                    CorporateActionCurrentOfficialWindowReason.SNAPSHOT_CHANGED,
                    checked_at=completed_at,
                )
            if (
                previous.selected_event != current.selected_event
                or previous.expires_at != current.expires_at
            ):
                return _blocked(
                    request,
                    CorporateActionCurrentOfficialWindowReason.SNAPSHOT_CHANGED,
                    checked_at=completed_at,
                )

        if (
            initial.snapshot.proof_recorded_at >= initial.expires_at
            or completed_at >= initial.expires_at
        ):
            return _blocked(
                request,
                CorporateActionCurrentOfficialWindowReason.WINDOW_EXPIRED,
                checked_at=completed_at,
            )
        return _ready(
            request,
            initial,
            runtime_environment=self._runtime_environment,
            checked_at=completed_at,
        )

    def _finish_block(
        self,
        request: CorporateActionStageRequest,
        reason: CorporateActionCurrentOfficialWindowReason,
        *,
        started_at: datetime,
    ) -> CorporateActionCurrentOfficialWindowEvidence:
        """Stamp a block after one final trusted-clock monotonicity check."""

        finished_at, clock_reason = self._finish_clock(started_at)
        if finished_at is None:
            return _blocked(request, clock_reason, checked_at=started_at)
        return _blocked(request, reason, checked_at=finished_at)

    def _finish_clock(
        self,
        started_at: datetime,
    ) -> tuple[datetime | None, CorporateActionCurrentOfficialWindowReason]:
        """Read the trusted completion clock and reject invalid or backwards time."""

        try:
            finished_at = self._clock.now()
        except (
            AgomTradeProException,
            ArithmeticError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return None, CorporateActionCurrentOfficialWindowReason.CLOCK_UNAVAILABLE
        if not _is_aware(finished_at):
            return None, CorporateActionCurrentOfficialWindowReason.CLOCK_INVALID
        if finished_at < started_at:
            return None, CorporateActionCurrentOfficialWindowReason.CLOCK_MOVED_BACKWARDS
        return (
            finished_at,
            CorporateActionCurrentOfficialWindowReason.WINDOW_READY_PREREQUISITE_ONLY,
        )

    def _read_window(
        self,
        request: CorporateActionStageRequest,
        *,
        as_of: datetime,
        verify_original_bodies: bool = True,
    ) -> tuple[_CurrentWindowState | None, CorporateActionCurrentOfficialWindowReason]:
        """Resolve and validate one caller-owned origin, policy, snapshot, and body set."""

        try:
            calendar = self._origin_reader.read_verified_zero_origin_calendar(
                account_id=request.account_id,
                owner_user_id=request.owner_user_id,
                exchange=_SZSE_EXCHANGE,
                as_of=as_of,
            )
        except (
            AgomTradeProException,
            ArithmeticError,
            AttributeError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return None, CorporateActionCurrentOfficialWindowReason.OWNER_CALENDAR_UNAVAILABLE
        if not _valid_calendar(calendar, as_of=as_of):
            return None, CorporateActionCurrentOfficialWindowReason.OWNER_CALENDAR_INVALID
        if not _same_exchange_day(
            as_of, calendar.timezone_policy.timezone_name, calendar.decision_on
        ):
            return None, CorporateActionCurrentOfficialWindowReason.CURRENT_DAY_CHANGED

        try:
            policy = self._policy_reader.read_policy(
                decision_on=calendar.decision_on,
                earliest_required_on=calendar.origin_on,
                as_of=as_of,
            )
        except (
            AgomTradeProException,
            ArithmeticError,
            AttributeError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return None, CorporateActionCurrentOfficialWindowReason.POLICY_UNAVAILABLE
        if not _valid_policy(
            policy,
            calendar=calendar,
            runtime_environment=self._runtime_environment,
            as_of=as_of,
        ):
            return None, CorporateActionCurrentOfficialWindowReason.POLICY_UNAVAILABLE
        if policy is None:
            return None, CorporateActionCurrentOfficialWindowReason.POLICY_UNAVAILABLE

        snapshot_request = TransitionPlanEventSnapshotReadRequest(
            asset_code=request.asset_code,
            security_id=request.security_id,
            source_id=_SZSE_SOURCE_ID,
            start_on=policy.start_on,
            end_on=policy.end_on,
            as_of=as_of,
        )
        try:
            snapshot = self._snapshot_reader.read_latest_snapshot(snapshot_request)
        except TransitionPlanEventSourceRevisionChanged:
            return None, CorporateActionCurrentOfficialWindowReason.SNAPSHOT_CHANGED
        except (
            TransitionPlanEventSnapshotReadError,
            AgomTradeProException,
            ArithmeticError,
            AttributeError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return None, CorporateActionCurrentOfficialWindowReason.SNAPSHOT_UNAVAILABLE
        if snapshot is None:
            return None, CorporateActionCurrentOfficialWindowReason.SNAPSHOT_UNAVAILABLE
        if not _valid_snapshot(
            snapshot,
            request=request,
            policy=policy,
            as_of=as_of,
        ):
            return None, CorporateActionCurrentOfficialWindowReason.SNAPSHOT_INCOMPLETE
        selected = _select_requested_event(request, snapshot)
        if selected is None:
            return None, CorporateActionCurrentOfficialWindowReason.SOURCE_EVENT_MISSING
        if not _selected_event_matches_request(request, selected, as_of=as_of):
            return None, CorporateActionCurrentOfficialWindowReason.SOURCE_EVENT_CHANGED
        if self._original_body_verifier is None:
            return (
                None,
                CorporateActionCurrentOfficialWindowReason.ORIGINAL_BODY_VERIFIER_UNAVAILABLE,
            )
        if verify_original_bodies and not _verify_every_original_body(
            self._original_body_verifier,
            events=snapshot.events,
            body_store_root=policy.body_store_root,
        ):
            return None, CorporateActionCurrentOfficialWindowReason.ORIGINAL_BODY_UNVERIFIED
        expires_at = _expiry_from_original_listing(snapshot, policy.lease_policy)
        if expires_at is None or snapshot.proof_recorded_at >= expires_at or as_of >= expires_at:
            return None, CorporateActionCurrentOfficialWindowReason.WINDOW_EXPIRED
        return (
            _CurrentWindowState(
                calendar=calendar,
                policy=policy,
                snapshot=snapshot,
                selected_event=selected,
                expires_at=expires_at,
            ),
            CorporateActionCurrentOfficialWindowReason.WINDOW_READY_PREREQUISITE_ONLY,
        )


@dataclass(frozen=True, slots=True)
class _CurrentWindowState:
    """One verified read pass retained only for the final equality check."""

    calendar: VerifiedAccountOriginCalendar
    policy: TransitionPlanDisclosureRuntimePolicy
    snapshot: TransitionPlanEventAssetSnapshot
    selected_event: TransitionPlanEventRevision
    expires_at: datetime


def _valid_request(request: object, *, as_of: datetime) -> bool:
    """Require one official exact-SZ source request whose provenance is cutoff-known."""

    if type(request) is not CorporateActionStageRequest:
        return False
    return (
        request.source_namespace == _OFFICIAL_ACTION_NAMESPACE
        and type(request.asset_code) is str
        and _SZSE_ASSET_CODE.fullmatch(request.asset_code) is not None
        and request.security_id == request.asset_code
        and _is_token(request.source_record_id)
        and _is_token(request.source_revision_id)
        and _is_sha256(request.source_payload_sha256)
        and _is_aware(request.source_observed_at)
        and _is_aware(request.qualified_at)
        and request.source_observed_at <= request.qualified_at <= as_of
    )


def _valid_calendar(value: object, *, as_of: datetime) -> bool:
    """Check exact account-origin result and its cutoff-known SZSE timezone policy."""

    if not all(
        hasattr(value, field_name)
        for field_name in ("origin_on", "decision_on", "timezone_policy", "as_of")
    ):
        return False
    calendar = cast(VerifiedAccountOriginCalendar, value)
    if not all(
        hasattr(calendar.timezone_policy, field_name)
        for field_name in ("exchange", "timezone_name", "policy_id", "policy_sha256")
    ):
        return False
    timezone_policy = calendar.timezone_policy
    return (
        type(calendar.as_of) is datetime
        and calendar.as_of == as_of
        and type(calendar.origin_on) is date
        and type(calendar.origin_on) is not datetime
        and type(calendar.decision_on) is date
        and type(calendar.decision_on) is not datetime
        and calendar.origin_on <= calendar.decision_on
        and type(timezone_policy.exchange) is str
        and timezone_policy.exchange == _SZSE_EXCHANGE
        and _is_token(timezone_policy.timezone_name)
        and _is_token(timezone_policy.policy_id)
        and _is_sha256(timezone_policy.policy_sha256)
        and _same_exchange_day(as_of, timezone_policy.timezone_name, calendar.decision_on)
    )


def _valid_policy(
    value: TransitionPlanDisclosureRuntimePolicy | None,
    *,
    calendar: VerifiedAccountOriginCalendar,
    runtime_environment: str,
    as_of: datetime,
) -> bool:
    """Require explicit, current-day policy and known Config Center provenance."""

    if type(value) is not TransitionPlanDisclosureRuntimePolicy:
        return False
    lease = value.lease_policy
    return (
        type(lease) is TransitionPlanEventCoverageLeasePolicy
        and value.runtime_environment == runtime_environment
        and value.source_id == _SZSE_SOURCE_ID
        and value.read_at == as_of
        and type(value.start_on) is date
        and type(value.start_on) is not datetime
        and type(value.end_on) is date
        and type(value.end_on) is not datetime
        and value.start_on <= calendar.origin_on <= calendar.decision_on
        and value.end_on == calendar.decision_on
        and value.policy_version == lease.policy_version
        and isinstance(value.body_store_root, Path)
        and value.body_store_root.is_absolute()
        and ".." not in value.body_store_root.parts
        and _is_token(value.policy_version)
        and _is_token(value.profile_id)
        and _is_token(value.profile_key)
        and type(value.profile_version) is int
        and value.profile_version > 0
        and _is_sha256(value.profile_content_hash)
        and _is_token(value.snapshot_id)
        and _is_sha256(value.snapshot_content_hash)
        and _is_sha256(value.policy_content_hash)
        and _is_aware(value.known_at)
        and _is_aware(value.effective_at)
        and value.known_at <= value.effective_at <= value.read_at == as_of
        and timedelta(0) < lease.ttl <= lease.maximum_ttl <= _MAXIMUM_WINDOW_LEASE
    )


def _valid_snapshot(
    value: object,
    *,
    request: CorporateActionStageRequest,
    policy: TransitionPlanDisclosureRuntimePolicy,
    as_of: datetime,
) -> bool:
    """Require latest-to-exact complete proof with all listed members known at cutoff."""

    if type(value) is not TransitionPlanEventAssetSnapshot:
        return False
    return (
        value.asset_code == request.asset_code
        and value.security_id == request.security_id
        and value.source_id == _SZSE_SOURCE_ID
        and value.start_on == policy.start_on
        and value.end_on == policy.end_on
        and value.as_of == value.proof_recorded_at
        and value.proof_recorded_at <= as_of
        and value.source_observed_at <= value.proof_recorded_at
        and value.first_observed_at <= value.source_observed_at
        and value.coverage_status is TransitionPlanEventCoverageStatus.COMPLETE
        and _is_sha256(value.source_scope_sha256)
        and type(value.events) is tuple
        and bool(value.events)
        and all(type(event) is TransitionPlanEventRevision for event in value.events)
        and all(event.event_type.upper() != "UNKNOWN" for event in value.events)
        and all(event.known_at <= as_of and event.available_at <= as_of for event in value.events)
    )


def _select_requested_event(
    request: CorporateActionStageRequest,
    snapshot: TransitionPlanEventAssetSnapshot,
) -> TransitionPlanEventRevision | None:
    """Select exactly one source-record member from the complete exact proof."""

    matches = tuple(
        event for event in snapshot.events if event.source_event_id == request.source_record_id
    )
    return matches[0] if len(matches) == 1 else None


def _selected_event_matches_request(
    request: CorporateActionStageRequest,
    event: TransitionPlanEventRevision,
    *,
    as_of: datetime,
) -> bool:
    """Bind the request's record, revision, body, and first-observation clocks exactly."""

    return (
        event.asset_code == request.asset_code
        and event.security_id == request.security_id
        and event.source_id == _SZSE_SOURCE_ID
        and event.source_event_id == request.source_record_id
        and event.source_revision_id == request.source_revision_id
        and event.body_sha256 == request.source_payload_sha256
        and event.available_at == request.source_observed_at
        and event.known_at <= as_of
        and event.available_at <= request.qualified_at <= as_of
    )


def _verify_every_original_body(
    verifier: OriginalDisclosureBodyVerifier,
    *,
    events: tuple[TransitionPlanEventRevision, ...],
    body_store_root: Path,
) -> bool:
    """Call the verifier for every member, even after one body fails verification."""

    all_verified = True
    for event in events:
        try:
            verified = verifier.verify_original_body(
                event=event,
                body_store_root=body_store_root,
            )
        except (
            AgomTradeProException,
            ArithmeticError,
            AttributeError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            verified = False
        all_verified = type(verified) is bool and verified and all_verified
    return all_verified


def _expiry_from_original_listing(
    snapshot: TransitionPlanEventAssetSnapshot,
    lease_policy: TransitionPlanEventCoverageLeasePolicy,
) -> datetime | None:
    """Expire from original listing verification, bounded by the complete proof clock."""

    try:
        expires_at = snapshot.source_observed_at + lease_policy.ttl
    except OverflowError:
        return None
    if snapshot.proof_recorded_at >= expires_at:
        return None
    return expires_at


def _same_calendar(
    left: VerifiedAccountOriginCalendar,
    right: VerifiedAccountOriginCalendar,
) -> bool:
    """Compare stable calendar and timezone identities, excluding each read cutoff."""

    return (
        left.origin_on == right.origin_on
        and left.decision_on == right.decision_on
        and left.timezone_policy.exchange == right.timezone_policy.exchange
        and left.timezone_policy.timezone_name == right.timezone_policy.timezone_name
        and left.timezone_policy.policy_id == right.timezone_policy.policy_id
        and left.timezone_policy.policy_sha256 == right.timezone_policy.policy_sha256
    )


def _policy_identity(policy: TransitionPlanDisclosureRuntimePolicy) -> tuple[object, ...]:
    """Return the complete stable Config Center policy identity except per-read cutoff."""

    return (
        policy.source_id,
        policy.start_on,
        policy.end_on,
        str(policy.body_store_root),
        policy.lease_policy,
        policy.policy_version,
        policy.runtime_environment,
        policy.profile_id,
        policy.profile_key,
        policy.profile_version,
        policy.profile_content_hash,
        policy.snapshot_id,
        policy.snapshot_content_hash,
        policy.known_at,
        policy.effective_at,
        policy.policy_content_hash,
    )


def _same_exchange_day(as_of: datetime, timezone_name: str, expected_day: date) -> bool:
    """Require the supplied cutoff to belong to the verified exchange-local day."""

    try:
        exchange_timezone = ZoneInfo(timezone_name)
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        return False
    return as_of.astimezone(exchange_timezone).date() == expected_day


def _ready(
    request: CorporateActionStageRequest,
    state: _CurrentWindowState,
    *,
    runtime_environment: str,
    checked_at: datetime,
) -> CorporateActionCurrentOfficialWindowEvidence:
    """Project exact original source evidence with a permanent decision-use block."""

    event = state.selected_event
    snapshot = state.snapshot
    return CorporateActionCurrentOfficialWindowEvidence(
        window_ready=True,
        reason_code=CorporateActionCurrentOfficialWindowReason.WINDOW_READY_PREREQUISITE_ONLY,
        freshness_status="current",
        reliability_status="verified",
        account_id=request.account_id,
        owner_user_id=request.owner_user_id,
        asset_code=request.asset_code,
        security_id=request.security_id,
        source_record_id=event.source_event_id,
        source_revision_id=event.source_revision_id,
        source_payload_sha256=event.body_sha256,
        source_observed_at=event.available_at,
        window_start_on=snapshot.start_on,
        window_end_on=snapshot.end_on,
        original_first_observed_at=snapshot.first_observed_at,
        original_listing_verified_at=snapshot.source_observed_at,
        original_proof_recorded_at=snapshot.proof_recorded_at,
        checked_at=checked_at,
        expires_at=state.expires_at,
        runtime_environment=runtime_environment,
        policy_sha256=state.policy.policy_content_hash,
        calendar_policy_sha256=state.calendar.timezone_policy.policy_sha256,
        scope_sha256=snapshot.source_scope_sha256,
        selected_event_sha256=event.manifest_sha256,
    )


def _blocked(
    request: CorporateActionStageRequest,
    reason: CorporateActionCurrentOfficialWindowReason,
    *,
    checked_at: datetime | None = None,
) -> CorporateActionCurrentOfficialWindowEvidence:
    """Build a stable blocked result without promoting partial data into readiness."""

    if type(request) is CorporateActionStageRequest:
        return CorporateActionCurrentOfficialWindowEvidence(
            window_ready=False,
            reason_code=reason,
            freshness_status=(
                "stale"
                if reason
                in {
                    CorporateActionCurrentOfficialWindowReason.CURRENT_DAY_CHANGED,
                    CorporateActionCurrentOfficialWindowReason.WINDOW_EXPIRED,
                }
                else "unknown"
            ),
            account_id=request.account_id,
            owner_user_id=request.owner_user_id,
            asset_code=request.asset_code,
            security_id=request.security_id,
            source_record_id=request.source_record_id,
            source_revision_id=request.source_revision_id,
            source_payload_sha256=request.source_payload_sha256,
            source_observed_at=request.source_observed_at,
            checked_at=checked_at if _is_aware(checked_at) else None,
        )
    return CorporateActionCurrentOfficialWindowEvidence(
        window_ready=False,
        reason_code=reason,
        checked_at=checked_at if _is_aware(checked_at) else None,
    )


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


__all__ = (
    "CorporateActionCurrentOfficialWindowClock",
    "CorporateActionCurrentOfficialWindowEvidence",
    "CorporateActionCurrentOfficialWindowReader",
    "CorporateActionCurrentOfficialWindowReason",
    "OriginalDisclosureBodyVerifier",
    "VerifiedAccountOriginCalendarReader",
)
