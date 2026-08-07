"""ID-only Application contracts for R7 result Promotion, retirement, and audit."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.r7_research_result_lifecycle import (
    R7ResearchResultRef,
    R7ResultLifecycleAction,
    R7ResultLifecycleEvent,
    R7ResultLifecycleStatus,
    R7ResultPromotionAuthorization,
    create_r7_result_lifecycle_event,
    derive_r7_result_lifecycle_state,
)
from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
)
from apps.research.domain.scenario_probability_contracts import ResearchEvidenceStatus
from apps.research.domain.scenario_research_hashing import require_token


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class R7ResultLifecycleConflict(ValueError):
    """An immutable identity, sequence, or terminal transition conflicts."""


class R7ResultLifecycleCorruption(ValueError):
    """Persisted lifecycle bytes, headers, relations, or hash chain diverged."""


class R7ResultLifecycleUnavailable(ValueError):
    """An exact owner authorization or result was not knowable at the cutoff."""


@dataclass(frozen=True)
class R7ResultLifecycleAuthorizationRef:
    """Identifier-only reference to an authorization owned by Research."""

    authorization_id: str
    authorization_version: str

    def __post_init__(self) -> None:
        require_token(self.authorization_id, "authorization_id", maximum=192)
        require_token(self.authorization_version, "authorization_version", maximum=192)


@dataclass(frozen=True)
class ApplyR7ResultLifecycleCommand:
    """Exact result/action/authorization identifiers without caller evidence."""

    result_ref: R7ResearchResultRef
    action: R7ResultLifecycleAction
    authorization_ref: R7ResultLifecycleAuthorizationRef

    def __post_init__(self) -> None:
        if not isinstance(self.action, R7ResultLifecycleAction):
            raise ValueError("R7 result lifecycle action is invalid")


@dataclass(frozen=True)
class R7ResearchResultAuditEntry:
    """One immutable result and PIT-derived internal research lifecycle state."""

    result_ref: R7ResearchResultRef
    policy_id: str
    policy_version: str
    policy_record_hash: str
    scope_content_hash: str
    evaluated_at: datetime
    recorded_at: datetime
    result_persisted_at: datetime
    subjective_calibration_status: ResearchEvidenceStatus
    model_inferred_calibration_status: ResearchEvidenceStatus
    historical_analogy_status: ResearchEvidenceStatus
    path_research_status: ResearchEvidenceStatus
    blocker_codes: tuple[str, ...]
    lifecycle_status: R7ResultLifecycleStatus
    lifecycle_sequence: int
    head_event_hash: str | None
    promoted_at: datetime | None
    retired_at: datetime | None
    research_only: bool
    must_not_use_for_decision: bool
    must_not_execute: bool


@dataclass(frozen=True)
class R7ResearchResultAuditPage:
    """Stable page bound to one explicit materialized PIT snapshot."""

    entries: tuple[R7ResearchResultAuditEntry, ...]
    next_cursor: str | None
    snapshot_as_of: datetime


class ExactR7ResultLifecycleAuthorizationProvider(Protocol):
    """Research-owner port for one exact authorization known at ``as_of``."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the owner's transaction boundary key."""

    def get_exact(
        self,
        *,
        authorization_ref: R7ResultLifecycleAuthorizationRef,
        result_ref: R7ResearchResultRef,
        action: R7ResultLifecycleAction,
        as_of: datetime,
    ) -> R7ResultPromotionAuthorization | None:
        """Return the exact owner record without latest/current fallback."""


class R7ResultLifecycleRepository(Protocol):
    """Composition-owned exact result, append, and internal audit boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the repository transaction boundary key."""

    def atomic(self) -> AbstractContextManager[None]:
        """Enter the exact result/authorization/event transaction."""

    def server_now(self) -> datetime:
        """Return the authoritative server clock."""

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedR7ResearchResult | None:
        """Return one exact immutable result knowable at ``as_of``."""

    def load_lifecycle_stream(
        self,
        *,
        result_ref: R7ResearchResultRef,
    ) -> tuple[R7ResultLifecycleEvent, ...]:
        """Load a complete exact stream, never an active/current projection."""

    def get_event_by_authorization(
        self,
        *,
        authorization_ref: R7ResultLifecycleAuthorizationRef,
    ) -> R7ResultLifecycleEvent | None:
        """Resolve an idempotent event winner by exact authorization identity."""

    def append_lifecycle(
        self,
        *,
        authorization: R7ResultPromotionAuthorization,
        event: R7ResultLifecycleEvent,
    ) -> R7ResultLifecycleEvent:
        """Append the exact authorization and event atomically."""

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R7ResearchResultAuditPage:
        """Return one materialized snapshot-bound audit page."""


class ApplyR7ResultLifecycle:
    """Apply one owner-authorized internal research lifecycle transition."""

    def __init__(
        self,
        authorization_provider: ExactR7ResultLifecycleAuthorizationProvider,
        repository: R7ResultLifecycleRepository,
    ) -> None:
        if authorization_provider.unit_of_work_key != repository.unit_of_work_key:
            raise ValueError("R7 result lifecycle owners use different units of work")
        self._authorization_provider = authorization_provider
        self._repository = repository

    def execute(
        self,
        command: ApplyR7ResultLifecycleCommand,
    ) -> R7ResultLifecycleEvent:
        """Reread exact owner facts and append one server-clocked event."""

        with self._repository.atomic():
            now = self._repository.server_now()
            _require_aware(now, "R7 result lifecycle server clock")
            authorization = self._authorization_provider.get_exact(
                authorization_ref=command.authorization_ref,
                result_ref=command.result_ref,
                action=command.action,
                as_of=now,
            )
            if authorization is None:
                raise R7ResultLifecycleUnavailable(
                    "exact R7 result lifecycle authorization is unavailable"
                )
            self._validate_authorization(command, authorization, now)
            result = self._repository.get_exact(
                result_id=command.result_ref.result_id,
                result_version=command.result_ref.result_version,
                expected_content_hash=command.result_ref.content_hash,
                as_of=authorization.recorded_at,
            )
            if result is None:
                raise R7ResultLifecycleUnavailable(
                    "exact R7 research result was unavailable when authorized"
                )
            stream = self._repository.load_lifecycle_stream(result_ref=command.result_ref)
            if stream:
                try:
                    derive_r7_result_lifecycle_state(stream, evaluated_at=now)
                except ValueError as error:
                    raise R7ResultLifecycleCorruption(
                        "persisted R7 result lifecycle stream is invalid"
                    ) from error
            existing = self._repository.get_event_by_authorization(
                authorization_ref=command.authorization_ref
            )
            if existing is not None:
                self._validate_idempotent_event(
                    existing=existing,
                    authorization=authorization,
                    stream=stream,
                )
                return existing
            if not authorization.is_active_at(now):
                raise R7ResultLifecycleUnavailable("R7 result lifecycle authorization is inactive")
            expected_sequence = len(stream) + 1
            if authorization.expected_sequence != expected_sequence:
                raise R7ResultLifecycleConflict(
                    "R7 result lifecycle authorization sequence is stale"
                )
            previous_hash = stream[-1].content_hash if stream else None
            event = create_r7_result_lifecycle_event(
                authorization=authorization,
                occurred_at=now,
                recorded_at=now,
                previous_event_hash=previous_hash,
            )
            try:
                derive_r7_result_lifecycle_state(
                    (*stream, event),
                    evaluated_at=now,
                )
            except ValueError as error:
                raise R7ResultLifecycleConflict(
                    "R7 result lifecycle transition is invalid"
                ) from error
            return self._repository.append_lifecycle(
                authorization=authorization,
                event=event,
            )

    @staticmethod
    def _validate_authorization(
        command: ApplyR7ResultLifecycleCommand,
        authorization: R7ResultPromotionAuthorization,
        now: datetime,
    ) -> None:
        if (
            authorization.authorization_id != command.authorization_ref.authorization_id
            or authorization.authorization_version
            != command.authorization_ref.authorization_version
            or authorization.result_ref != command.result_ref
            or authorization.action is not command.action
        ):
            raise R7ResultLifecycleUnavailable("R7 result lifecycle authorization substitution")
        if authorization.recorded_at > now:
            raise R7ResultLifecycleUnavailable(
                "future R7 result lifecycle authorization is unavailable"
            )

    @staticmethod
    def _validate_idempotent_event(
        *,
        existing: R7ResultLifecycleEvent,
        authorization: R7ResultPromotionAuthorization,
        stream: tuple[R7ResultLifecycleEvent, ...],
    ) -> None:
        if (
            existing not in stream
            or existing.event_id != authorization.event_id
            or existing.event_version != authorization.event_version
            or existing.result_ref != authorization.result_ref
            or existing.authorization_hash != authorization.content_hash
            or existing.action is not authorization.action
            or existing.sequence != authorization.expected_sequence
            or existing.reason_codes != authorization.reason_codes
        ):
            raise R7ResultLifecycleCorruption(
                "R7 result lifecycle idempotent winner differs from authorization"
            )


class AuditR7ResearchResults:
    """Bounded audit snapshot facade; it is not a current-result selector."""

    def __init__(self, repository: R7ResultLifecycleRepository) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        as_of: datetime,
        cursor: str | None = None,
        limit: int = 50,
    ) -> R7ResearchResultAuditPage:
        """Return one exact PIT audit page."""

        _require_aware(as_of, "R7 result audit as_of")
        if isinstance(limit, bool) or limit < 1 or limit > 200:
            raise ValueError("R7 result audit limit must be between 1 and 200")
        return self._repository.list_audit(
            as_of=as_of,
            cursor=cursor,
            limit=limit,
        )


__all__ = [
    "ApplyR7ResultLifecycle",
    "ApplyR7ResultLifecycleCommand",
    "AuditR7ResearchResults",
    "ExactR7ResultLifecycleAuthorizationProvider",
    "R7ResearchResultAuditEntry",
    "R7ResearchResultAuditPage",
    "R7ResultLifecycleAuthorizationRef",
    "R7ResultLifecycleConflict",
    "R7ResultLifecycleCorruption",
    "R7ResultLifecycleRepository",
    "R7ResultLifecycleUnavailable",
]
