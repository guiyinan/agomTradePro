"""Application gate for comparing immutable plan event pins with current source facts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.domain.transition_plan_event_review import (
    SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID,
    SECURITY_DISCLOSURE_EVENT_SOURCE_KIND,
    TransitionPlanEventAssetSnapshot,
    TransitionPlanEventCoverageStatus,
    TransitionPlanEventReviewAssessment,
    TransitionPlanEventReviewState,
    has_transition_plan_event_bindings,
    transition_plan_event_coverage_bindings,
    transition_plan_event_snapshot_sha256,
)
from apps.portfolio.domain.transition_plan_revision import TransitionPlanRevision
from apps.portfolio.domain.transition_plan_revision_basis import TransitionPlanSourceBinding

logger = logging.getLogger(__name__)


class TransitionPlanEventSnapshotReadError(RuntimeError):
    """A source adapter could not prove complete event history for a requested cutoff."""


@dataclass(frozen=True, slots=True)
class TransitionPlanEventSnapshotReadRequest:
    """Read one certified security/source snapshot at an exact knowledge cutoff."""

    asset_code: str
    security_id: str
    source_id: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Require exact asset/source scope and an aware point-in-time cutoff."""

        for name in ("asset_code", "security_id", "source_id"):
            value = getattr(self, name)
            if type(value) is not str or not value or value.strip() != value:
                raise ValueError(f"{name} must be a non-empty canonical token")
        if type(self.as_of) is not datetime or self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")


class TransitionPlanEventSnapshotReader(Protocol):
    """Read immutable, certified exchange-disclosure facts without write side effects."""

    def read_snapshot(
        self, request: TransitionPlanEventSnapshotReadRequest
    ) -> TransitionPlanEventAssetSnapshot | None:
        """Return complete or explicitly incomplete coverage; return None when unavailable."""
        ...


class TransitionPlanEventReviewValidator(Protocol):
    """Assess whether an exact immutable plan still matches its bound event evidence."""

    def assess(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> TransitionPlanEventReviewAssessment:
        """Return unchanged, review-required, or blocked without mutating plan status."""
        ...


class AssessTransitionPlanEventReview:
    """Compare exact plan coverage pins against complete historical and current snapshots."""

    def __init__(self, *, reader: TransitionPlanEventSnapshotReader | None) -> None:
        """Inject a read-only source adapter; absent adapters fail closed for opted-in plans."""

        self._reader = reader

    def assess(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> TransitionPlanEventReviewAssessment:
        """Assess event change without writing lifecycle state or inventing coverage."""

        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            return _blocked("EVENT_REVIEW_CUTOFF_INVALID")
        bindings = revision.basis.source_bindings
        if not has_transition_plan_event_bindings(bindings):
            return _unchanged()
        if self._reader is None:
            return _blocked("EVENT_SOURCE_READER_UNAVAILABLE")
        try:
            return self._assess_bound_revision(revision, bindings, as_of=as_of)
        except (TransitionPlanEventSnapshotReadError, TypeError, ValueError):
            return _blocked("EVENT_SNAPSHOT_INCONSISTENT")

    def _assess_bound_revision(
        self,
        revision: TransitionPlanRevision,
        bindings: tuple[TransitionPlanSourceBinding, ...],
        *,
        as_of: datetime,
    ) -> TransitionPlanEventReviewAssessment:
        """Validate every opt-in security/source and compare event revision identities."""

        event_bindings = tuple(
            item for item in bindings if item.kind == SECURITY_DISCLOSURE_EVENT_SOURCE_KIND
        )
        coverage_bindings = transition_plan_event_coverage_bindings(bindings)
        if not coverage_bindings:
            return _blocked("EVENT_COVERAGE_PIN_MISSING")
        marker_keys = tuple(
            (item.asset_code, item.security_id, item.source_id) for item in coverage_bindings
        )
        if len(marker_keys) != len(set(marker_keys)):
            return _blocked("EVENT_COVERAGE_PIN_AMBIGUOUS")
        marker_key_set = set(marker_keys)
        if any(
            (item.asset_code, item.security_id, item.source_id) not in marker_key_set
            for item in event_bindings
            if item.source_record_id != SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID
        ):
            return _blocked("EVENT_COVERAGE_PIN_MISSING")
        if any(item.coverage_status != "complete" for item in coverage_bindings):
            return _blocked("EVENT_COVERAGE_PIN_INCOMPLETE")
        if any(
            item.decision_cutoff > revision.basis.prepared_at
            or item.decision_cutoff > revision.identity.recorded_at
            or item.decision_cutoff > as_of
            for item in coverage_bindings
        ):
            return _blocked("EVENT_COVERAGE_PIN_CUTOFF_INVALID")

        changed = False
        for pin in coverage_bindings:
            request_at_plan = TransitionPlanEventSnapshotReadRequest(
                asset_code=pin.asset_code,
                security_id=pin.security_id,
                source_id=pin.source_id,
                as_of=pin.decision_cutoff,
            )
            historical = self._read_complete_snapshot(request_at_plan)
            if historical is None:
                return _blocked("EVENT_HISTORY_MISSING")
            historical_hash = transition_plan_event_snapshot_sha256(historical)
            if (
                historical_hash != pin.body_sha256
                or historical.source_scope_sha256 != pin.manifest_sha256
            ):
                return _blocked("EVENT_HISTORY_PIN_MISMATCH")
            bound_event_pins = tuple(
                item
                for item in event_bindings
                if item.source_record_id != SECURITY_DISCLOSURE_EVENT_COVERAGE_RECORD_ID
                and (item.asset_code, item.security_id, item.source_id)
                == (pin.asset_code, pin.security_id, pin.source_id)
            )
            historical_events = {item.source_event_id: item for item in historical.events}
            for event_pin in bound_event_pins:
                event = historical_events.get(event_pin.source_record_id)
                if (
                    event is None
                    or event.body_sha256 != event_pin.body_sha256
                    or event.manifest_sha256 != event_pin.manifest_sha256
                ):
                    return _blocked("EVENT_HISTORY_PIN_MISMATCH")

            current = self._read_complete_snapshot(
                TransitionPlanEventSnapshotReadRequest(
                    asset_code=pin.asset_code,
                    security_id=pin.security_id,
                    source_id=pin.source_id,
                    as_of=as_of,
                )
            )
            if current is None:
                return _blocked("EVENT_CURRENT_PROOF_MISSING")
            current_events = {item.source_event_id: item for item in current.events}
            if any(event_id not in current_events for event_id in historical_events):
                return _blocked("EVENT_CURRENT_PROOF_MISSING")
            if any(_is_unknown_event(item.event_type) for item in current.events):
                return _blocked("EVENT_TYPE_UNKNOWN")
            if transition_plan_event_snapshot_sha256(current) != historical_hash:
                changed = True

        if changed:
            return TransitionPlanEventReviewAssessment(
                state=TransitionPlanEventReviewState.REVIEW_REQUIRED,
                reason_code="EVENT_REVISION_CHANGED",
            )
        return _unchanged()

    def _read_complete_snapshot(
        self, request: TransitionPlanEventSnapshotReadRequest
    ) -> TransitionPlanEventAssetSnapshot | None:
        """Read and validate one exact complete coverage proof at the requested cutoff."""

        if self._reader is None:
            return None
        snapshot = self._reader.read_snapshot(request)
        if snapshot is None:
            return None
        if type(snapshot) is not TransitionPlanEventAssetSnapshot:
            return None
        if (
            snapshot.asset_code != request.asset_code
            or snapshot.security_id != request.security_id
            or snapshot.source_id != request.source_id
            or snapshot.as_of != request.as_of
            or snapshot.coverage_status is not TransitionPlanEventCoverageStatus.COMPLETE
            or snapshot.source_scope_sha256 is None
        ):
            return None
        if any(_is_unknown_event(item.event_type) for item in snapshot.events):
            logger.warning(
                "Unknown disclosure event type blocks transition plan review for %s",
                request.asset_code,
            )
            return None
        return snapshot


def _is_unknown_event(event_type: str) -> bool:
    """Identify the dedicated unknown event classification without coercion."""

    return event_type.upper() == "UNKNOWN"


def _unchanged() -> TransitionPlanEventReviewAssessment:
    """Build the stable no-change event assessment."""

    return TransitionPlanEventReviewAssessment(
        state=TransitionPlanEventReviewState.UNCHANGED,
        reason_code="EVENTS_UNCHANGED",
    )


def _blocked(reason_code: str) -> TransitionPlanEventReviewAssessment:
    """Build a stable fail-closed event assessment."""

    return TransitionPlanEventReviewAssessment(
        state=TransitionPlanEventReviewState.BLOCKED,
        reason_code=reason_code,
    )


__all__ = [
    "AssessTransitionPlanEventReview",
    "TransitionPlanEventReviewValidator",
    "TransitionPlanEventSnapshotReadError",
    "TransitionPlanEventSnapshotReadRequest",
    "TransitionPlanEventSnapshotReader",
]
