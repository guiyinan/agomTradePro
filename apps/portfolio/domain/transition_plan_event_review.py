"""Pure event identity, coverage-pin, and revision-comparison contracts for plans."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from apps.portfolio.domain.transition_plan_revision_basis import TransitionPlanSourceBinding

SECURITY_DISCLOSURE_EVENT_SOURCE_KIND = "security_disclosure_event"
SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID = "__coverage__"


class TransitionPlanEventCoverageStatus(StrEnum):
    """Coverage claimed for one exact security and source at one knowledge cutoff."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class TransitionPlanEventCoverageLeasePolicy:
    """Injected versioned lease values and their explicitly approved upper bound."""

    policy_version: str
    ttl: timedelta
    maximum_ttl: timedelta

    def __post_init__(self) -> None:
        """Require explicit positive TTLs within the injected, versioned policy bound."""

        _require_token(self.policy_version, "policy_version")
        if type(self.ttl) is not timedelta or type(self.maximum_ttl) is not timedelta:
            raise ValueError("event coverage lease values must be exact timedeltas")
        if (
            self.maximum_ttl <= timedelta(0)
            or self.ttl <= timedelta(0)
            or self.ttl > self.maximum_ttl
        ):
            raise ValueError("event coverage lease TTL is outside the explicit policy bound")


class TransitionPlanEventReviewState(StrEnum):
    """Outcome of comparing the pinned event snapshot with current source facts."""

    UNCHANGED = "unchanged"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class TransitionPlanEventRevision:
    """One exact source-event revision visible at a supplied knowledge cutoff."""

    asset_code: str
    security_id: str
    source_id: str
    source_event_id: str
    source_revision_id: str
    event_type: str
    announced_at: date | datetime | None
    available_at: datetime
    known_at: datetime
    effective_at: date | datetime | None
    body_sha256: str
    manifest_sha256: str

    def __post_init__(self) -> None:
        """Validate stable identity, explicit clocks, and source revision hashes."""

        for name in (
            "asset_code",
            "security_id",
            "source_id",
            "source_event_id",
            "source_revision_id",
            "event_type",
        ):
            _require_token(getattr(self, name), name)
        if self.source_event_id.startswith(SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID):
            raise ValueError("source_event_id uses the reserved coverage marker namespace")
        for name in ("available_at", "known_at"):
            _require_aware(getattr(self, name), name)
        if self.available_at > self.known_at:
            raise ValueError("event first observation must not follow its durable known_at clock")
        for name in ("announced_at", "effective_at"):
            _require_date_or_aware_datetime(getattr(self, name), name)
        _require_digest(self.body_sha256, "body_sha256")
        _require_digest(self.manifest_sha256, "manifest_sha256")

    def to_digest_payload(self) -> dict[str, str | None]:
        """Return every event fact used to determine whether a plan needs review."""

        return {
            "asset_code": self.asset_code,
            "security_id": self.security_id,
            "source_id": self.source_id,
            "source_event_id": self.source_event_id,
            "source_revision_id": self.source_revision_id,
            "event_type": self.event_type,
            "announced_at": _date_or_datetime_text(self.announced_at),
            "available_at": self.available_at.isoformat(),
            "known_at": self.known_at.isoformat(),
            "effective_at": _date_or_datetime_text(self.effective_at),
            "body_sha256": self.body_sha256,
            "manifest_sha256": self.manifest_sha256,
        }


@dataclass(frozen=True, slots=True)
class TransitionPlanEventAssetSnapshot:
    """All event facts and certified source scope for one security at one cutoff."""

    asset_code: str
    security_id: str
    source_id: str
    start_on: date
    end_on: date
    as_of: datetime
    first_observed_at: datetime
    source_observed_at: datetime
    proof_recorded_at: datetime
    coverage_status: TransitionPlanEventCoverageStatus
    source_scope_sha256: str | None
    events: tuple[TransitionPlanEventRevision, ...]

    def __post_init__(self) -> None:
        """Reject ambiguous event sets and incomplete claims of certified coverage."""

        for name in ("asset_code", "security_id", "source_id"):
            _require_token(getattr(self, name), name)
        for name in ("start_on", "end_on"):
            value = getattr(self, name)
            if type(value) is not date or type(value) is datetime:
                raise ValueError(f"{name} must be a pure calendar date")
        if self.start_on > self.end_on:
            raise ValueError("event coverage window start_on must not follow end_on")
        for name in ("as_of", "first_observed_at", "source_observed_at", "proof_recorded_at"):
            _require_aware(getattr(self, name), name)
        if (
            self.first_observed_at > self.source_observed_at
            or self.source_observed_at > self.proof_recorded_at
            or self.proof_recorded_at > self.as_of
        ):
            raise ValueError("event source/proof clock follows its knowledge cutoff")
        if type(self.coverage_status) is not TransitionPlanEventCoverageStatus:
            raise ValueError("coverage_status must be a recognized event coverage status")
        if self.source_scope_sha256 is not None:
            _require_digest(self.source_scope_sha256, "source_scope_sha256")
        if self.coverage_status is TransitionPlanEventCoverageStatus.COMPLETE:
            if self.source_scope_sha256 is None:
                raise ValueError("complete event coverage requires a certified source-scope hash")
            if self.proof_recorded_at != self.as_of:
                raise ValueError(
                    "complete event coverage must use its exact proof recorded_at cutoff"
                )
        event_ids = tuple(item.source_event_id for item in self.events)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("an event snapshot cannot contain duplicate source event identities")
        for item in self.events:
            if (
                item.asset_code != self.asset_code
                or item.security_id != self.security_id
                or item.source_id != self.source_id
            ):
                raise ValueError("event snapshot contains a fact outside its exact source scope")
            if item.available_at > self.as_of or item.known_at > self.as_of:
                raise ValueError(
                    "event snapshot contains a fact unavailable at its knowledge cutoff"
                )


@dataclass(frozen=True, slots=True)
class TransitionPlanEventReviewAssessment:
    """Typed, side-effect-free decision consumed by review and locked-action gates."""

    state: TransitionPlanEventReviewState
    reason_code: str

    def __post_init__(self) -> None:
        """Require a known result and stable machine-readable explanation."""

        if type(self.state) is not TransitionPlanEventReviewState:
            raise ValueError("state must be a recognized event review outcome")
        _require_token(self.reason_code, "reason_code")


def has_transition_plan_event_bindings(
    source_bindings: tuple[TransitionPlanSourceBinding, ...],
) -> bool:
    """Return whether an immutable revision explicitly opted into event revalidation."""

    return any(item.kind == SECURITY_DISCLOSURE_EVENT_SOURCE_KIND for item in source_bindings)


def transition_plan_event_coverage_bindings(
    source_bindings: tuple[TransitionPlanSourceBinding, ...],
) -> tuple[TransitionPlanSourceBinding, ...]:
    """Return exact and legacy marker bindings for fail-closed validation."""

    return tuple(
        item
        for item in source_bindings
        if item.kind == SECURITY_DISCLOSURE_EVENT_SOURCE_KIND
        and item.source_record_id.startswith(SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID)
    )


def transition_plan_event_snapshot_sha256(
    snapshot: TransitionPlanEventAssetSnapshot,
) -> str:
    """Hash the certified source scope and complete as-of-visible event revision set."""

    if type(snapshot) is not TransitionPlanEventAssetSnapshot:
        raise TypeError("snapshot must be an exact TransitionPlanEventAssetSnapshot")
    if snapshot.coverage_status is not TransitionPlanEventCoverageStatus.COMPLETE:
        raise ValueError("only complete certified event snapshots can be pinned")
    payload = {
        "asset_code": snapshot.asset_code,
        "security_id": snapshot.security_id,
        "source_id": snapshot.source_id,
        "start_on": snapshot.start_on.isoformat(),
        "end_on": snapshot.end_on.isoformat(),
        "source_scope_sha256": snapshot.source_scope_sha256,
        "events": [
            event.to_digest_payload()
            for event in sorted(snapshot.events, key=lambda item: item.source_event_id)
        ],
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def transition_plan_event_revision_sha256(event: TransitionPlanEventRevision) -> str:
    """Hash one exact event revision, including its correction/revision identity."""

    if type(event) is not TransitionPlanEventRevision:
        raise TypeError("event must be an exact TransitionPlanEventRevision")
    encoded = json.dumps(
        event.to_digest_payload(),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_token(value: object, field_name: str) -> None:
    """Require a bounded canonical identity without hidden whitespace."""

    if type(value) is not str or not value or value.strip() != value or len(value) > 192:
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_digest(value: object, field_name: str) -> None:
    """Require one lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    """Reject timestamps without an explicit timezone offset."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_date_or_aware_datetime(value: object, field_name: str) -> None:
    """Allow unknown dates while preserving date precision and aware timestamps."""

    if value is None:
        return
    if type(value) is date:
        return
    if type(value) is datetime:
        _require_aware(value, field_name)
        return
    raise ValueError(f"{field_name} must be date, aware datetime, or None")


def _date_or_datetime_text(value: date | datetime | None) -> str | None:
    """Serialize a date without collapsing it to midnight or a naive timestamp."""

    return None if value is None else value.isoformat()


__all__ = [
    "SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID",
    "SECURITY_DISCLOSURE_EVENT_SOURCE_KIND",
    "TransitionPlanEventAssetSnapshot",
    "TransitionPlanEventCoverageLeasePolicy",
    "TransitionPlanEventCoverageStatus",
    "TransitionPlanEventRevision",
    "TransitionPlanEventReviewAssessment",
    "TransitionPlanEventReviewState",
    "has_transition_plan_event_bindings",
    "transition_plan_event_coverage_bindings",
    "transition_plan_event_snapshot_sha256",
    "transition_plan_event_revision_sha256",
]
