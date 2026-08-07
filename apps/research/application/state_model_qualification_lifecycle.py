"""ID-only Research lifecycle orchestration for R6 qualification evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.application.state_model_qualification_persistence import (
    R6QualificationAssessmentRepository,
)
from apps.research.domain.state_model_qualification import (
    StateModelQualificationAssessment,
    StateModelQualificationStatus,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationLifecycleAction,
    R6QualificationLifecycleEvent,
    R6QualificationPromotionAuthorization,
    R6QualificationRef,
    create_r6_qualification_lifecycle_event,
    derive_r6_qualification_lifecycle_state,
)


@dataclass(frozen=True)
class R6QualificationAuthorizationRef:
    """ID/version-only authorization locator."""

    authorization_id: str
    authorization_version: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("authorization_id", self.authorization_id),
            ("authorization_version", self.authorization_version),
        ):
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 192
                or any(character.isspace() for character in value)
            ):
                raise ValueError(f"{field_name} must be a bounded non-blank token")


class R6QualificationLifecycleAuthorizationProvider(Protocol):
    """Read owner authorization without accepting caller clocks or reasons."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary key."""

    def get_exact(
        self,
        *,
        authorization_ref: R6QualificationAuthorizationRef,
        qualification_ref: R6QualificationRef,
        action: R6QualificationLifecycleAction,
    ) -> R6QualificationPromotionAuthorization | None:
        """Return one exact manual authorization."""


class R6QualificationClock(Protocol):
    """Authoritative server clock used for PIT/future guards."""

    def now(self) -> datetime:
        """Return a timezone-aware server timestamp."""


class R6QualificationLifecycleRepository(R6QualificationAssessmentRepository, Protocol):
    """Append-only shared-UoW lifecycle repository."""

    def atomic(self) -> AbstractContextManager[None]:
        """Enter one shared transaction boundary."""

    def load_lifecycle_stream(
        self,
        *,
        assessment_ref: R6QualificationRef,
    ) -> tuple[R6QualificationLifecycleEvent, ...]:
        """Return the complete canonical stream."""

    def get_event_by_authorization(
        self,
        *,
        authorization_ref: R6QualificationAuthorizationRef,
    ) -> R6QualificationLifecycleEvent | None:
        """Return one exact idempotent event winner."""

    def append_lifecycle_event(
        self,
        *,
        authorization: R6QualificationPromotionAuthorization,
        event: R6QualificationLifecycleEvent,
    ) -> R6QualificationLifecycleEvent:
        """Append or replay one exact authorization/event pair."""


@dataclass(frozen=True)
class ApplyR6QualificationLifecycleCommand:
    """ID-only lifecycle command with no caller clocks, reasons, or output."""

    qualification_ref: R6QualificationRef
    action: R6QualificationLifecycleAction
    authorization_ref: R6QualificationAuthorizationRef


class ApplyR6QualificationLifecycle:
    """Apply one manually authorized PROMOTE/RETIRE transition."""

    def __init__(
        self,
        *,
        authorization_provider: R6QualificationLifecycleAuthorizationProvider,
        repository: R6QualificationLifecycleRepository,
    ) -> None:
        if authorization_provider.unit_of_work_key != repository.unit_of_work_key:
            raise ValueError("R6 qualification lifecycle owners use different units of work")
        self._authorization_provider = authorization_provider
        self._repository = repository

    def execute(
        self,
        command: ApplyR6QualificationLifecycleCommand,
    ) -> R6QualificationLifecycleEvent:
        """Resolve exact authorization, replay the stream, then append one event."""

        with self._repository.atomic():
            authorization = self._authorization_provider.get_exact(
                authorization_ref=command.authorization_ref,
                qualification_ref=command.qualification_ref,
                action=command.action,
            )
            if authorization is None:
                raise ValueError("R6 qualification lifecycle authorization is unavailable")
            if (
                (authorization.authorization_id, authorization.authorization_version)
                != (
                    command.authorization_ref.authorization_id,
                    command.authorization_ref.authorization_version,
                )
                or authorization.qualification_ref != command.qualification_ref
                or authorization.action is not command.action
            ):
                raise ValueError("R6 qualification lifecycle authorization substitution")
            assessment = self._repository.get_exact(
                assessment_ref=command.qualification_ref,
                as_of=authorization.recorded_at,
            )
            if (
                assessment is None
                or assessment.status is not StateModelQualificationStatus.EVIDENCE_COMPLETE
            ):
                raise ValueError("R6 qualification evidence is unavailable or incomplete")
            history = self._repository.load_lifecycle_stream(
                assessment_ref=command.qualification_ref,
            )
            state = (
                None
                if not history
                else derive_r6_qualification_lifecycle_state(
                    history,
                    evaluated_at=authorization.recorded_at,
                )
            )
            expected_sequence = 1 if state is None else state.sequence + 1
            existing = self._repository.get_event_by_authorization(
                authorization_ref=command.authorization_ref,
            )
            if existing is not None:
                if (
                    existing.qualification_ref != command.qualification_ref
                    or existing.action is not command.action
                    or existing.authorization_hash != authorization.content_hash
                ):
                    raise ValueError("R6 qualification lifecycle winner substitution")
                return existing
            if authorization.expected_sequence != expected_sequence:
                raise ValueError("R6 qualification lifecycle authorization is stale")
            event = create_r6_qualification_lifecycle_event(
                authorization=authorization,
                sequence=expected_sequence,
                occurred_at=authorization.recorded_at,
                recorded_at=authorization.recorded_at,
                previous_event_hash=None if state is None else state.head_event_hash,
            )
            return self._repository.append_lifecycle_event(
                authorization=authorization,
                event=event,
            )


class GetActiveR6Qualification:
    """PIT active reader that replays lifecycle and exact assessment evidence."""

    def __init__(
        self,
        *,
        repository: R6QualificationLifecycleRepository,
        clock: R6QualificationClock,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def get_active(
        self,
        *,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> StateModelQualificationAssessment | None:
        """Return an exact active qualification or explicit absence."""

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("R6 qualification active as_of must be timezone-aware")
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None or as_of > now:
            return None
        with self._repository.atomic():
            history = self._repository.load_lifecycle_stream(
                assessment_ref=qualification_ref,
            )
            if not history:
                return None
            prefix = tuple(item for item in history if item.recorded_at <= as_of)
            if not prefix:
                return None
            state = derive_r6_qualification_lifecycle_state(prefix, evaluated_at=as_of)
            if not state.active or state.qualification_ref != qualification_ref:
                return None
            assessment = self._repository.get_exact(
                assessment_ref=qualification_ref,
                as_of=as_of,
            )
            if (
                assessment is None
                or assessment.status is not StateModelQualificationStatus.EVIDENCE_COMPLETE
            ):
                return None
            return assessment


__all__ = [
    "ApplyR6QualificationLifecycle",
    "ApplyR6QualificationLifecycleCommand",
    "GetActiveR6Qualification",
    "R6QualificationAuthorizationRef",
    "R6QualificationClock",
    "R6QualificationLifecycleAuthorizationProvider",
    "R6QualificationLifecycleRepository",
]
