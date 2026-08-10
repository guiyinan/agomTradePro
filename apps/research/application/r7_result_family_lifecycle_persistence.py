"""Read and immutable-audit use cases for persisted R7 family lifecycles."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.application.r7_result_family_lifecycle import (
    R7FamilyAuthorizationRef,
    R7FamilyLifecycleUnavailable,
    R7ResultFamilyRef,
)
from apps.research.domain.r7_result_family_lifecycle import (
    R7FamilyLifecycleAction,
    R7FamilyLifecycleAuthorization,
    R7FamilyLifecycleEvent,
)
from apps.research.domain.scenario_research_hashing import require_sha256, require_token


def _aware(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


@dataclass(frozen=True)
class R7FamilyEventRef:
    event_id: str
    event_version: str

    def __post_init__(self) -> None:
        require_token(self.event_id, "R7 family event ref event_id", maximum=192)
        require_token(self.event_version, "R7 family event ref event_version", maximum=192)


@dataclass(frozen=True)
class GetExactR7FamilyAuthorizationCommand:
    authorization_ref: R7FamilyAuthorizationRef
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.authorization_ref) is not R7FamilyAuthorizationRef:
            raise TypeError("R7 family authorization query ref is invalid")
        self.authorization_ref.__post_init__()
        _aware(self.as_of, "R7 family authorization query as_of")


@dataclass(frozen=True)
class GetExactR7FamilyEventCommand:
    event_ref: R7FamilyEventRef
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.event_ref) is not R7FamilyEventRef:
            raise TypeError("R7 family event query ref is invalid")
        self.event_ref.__post_init__()
        _aware(self.as_of, "R7 family event query as_of")


@dataclass(frozen=True)
class AuditR7FamilyLifecycleCommand:
    family_ref: R7ResultFamilyRef
    as_of: datetime
    page_size: int
    cursor: str | None = None

    def __post_init__(self) -> None:
        if type(self.family_ref) is not R7ResultFamilyRef:
            raise TypeError("R7 family audit family ref is invalid")
        self.family_ref.__post_init__()
        _aware(self.as_of, "R7 family audit as_of")
        if type(self.page_size) is not int or not 1 <= self.page_size <= 200:
            raise ValueError("R7 family audit page_size is invalid")
        if self.cursor is not None:
            require_token(self.cursor, "R7 family audit cursor", maximum=4096)


@dataclass(frozen=True)
class R7FamilyLifecycleAuditEntry:
    sequence: int
    event_ref: R7FamilyEventRef
    action: R7FamilyLifecycleAction
    event_hash: str
    authorization_hash: str
    owner_recorded_at: datetime
    ledger_recorded_at: datetime

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("R7 family audit sequence is invalid")
        self.event_ref.__post_init__()
        if type(self.action) is not R7FamilyLifecycleAction:
            raise TypeError("R7 family audit action is invalid")
        require_sha256(self.event_hash, "R7 family audit event_hash")
        require_sha256(self.authorization_hash, "R7 family audit authorization_hash")
        _aware(self.owner_recorded_at, "R7 family audit owner_recorded_at")
        _aware(self.ledger_recorded_at, "R7 family audit ledger_recorded_at")
        if self.owner_recorded_at > self.ledger_recorded_at:
            raise ValueError("R7 family audit ledger predates owner evidence")


@dataclass(frozen=True)
class R7FamilyLifecycleAuditPage:
    snapshot_id: str
    snapshot_version: str
    snapshot_hash: str
    total_count: int
    entries: tuple[R7FamilyLifecycleAuditEntry, ...]
    next_cursor: str | None

    def __post_init__(self) -> None:
        require_token(self.snapshot_id, "R7 family audit snapshot_id", maximum=192)
        require_token(self.snapshot_version, "R7 family audit snapshot_version", maximum=96)
        require_sha256(self.snapshot_hash, "R7 family audit snapshot_hash")
        if type(self.total_count) is not int or self.total_count < 0:
            raise ValueError("R7 family audit total_count is invalid")
        if type(self.entries) is not tuple or any(
            type(entry) is not R7FamilyLifecycleAuditEntry for entry in self.entries
        ):
            raise TypeError("R7 family audit entries are invalid")
        for entry in self.entries:
            entry.__post_init__()
        if self.next_cursor is not None:
            require_token(self.next_cursor, "R7 family audit next_cursor", maximum=4096)


class R7FamilyLifecycleEvidenceQueryRepository(Protocol):
    """Read-only exact/PIT and immutable audit persistence port."""

    def atomic(self) -> AbstractContextManager[None]: ...

    def get_exact_authorization(
        self,
        *,
        authorization_ref: R7FamilyAuthorizationRef,
        as_of: datetime,
    ) -> R7FamilyLifecycleAuthorization | None: ...

    def get_exact_event(
        self,
        *,
        event_ref: R7FamilyEventRef,
        as_of: datetime,
    ) -> R7FamilyLifecycleEvent | None: ...

    def audit_events(
        self,
        *,
        family_ref: R7ResultFamilyRef,
        as_of: datetime,
        page_size: int,
        cursor: str | None,
    ) -> R7FamilyLifecycleAuditPage: ...


class GetExactR7FamilyAuthorization:
    def __init__(self, repository: R7FamilyLifecycleEvidenceQueryRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR7FamilyAuthorizationCommand,
    ) -> R7FamilyLifecycleAuthorization | None:
        try:
            if type(command) is not GetExactR7FamilyAuthorizationCommand:
                raise TypeError("R7 family authorization query command is invalid")
            command.__post_init__()
            return self._repository.get_exact_authorization(
                authorization_ref=command.authorization_ref,
                as_of=command.as_of,
            )
        except R7FamilyLifecycleUnavailable:
            raise
        except Exception as error:
            raise R7FamilyLifecycleUnavailable(
                "R7 family authorization query is unavailable"
            ) from error


class GetExactR7FamilyEvent:
    def __init__(self, repository: R7FamilyLifecycleEvidenceQueryRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR7FamilyEventCommand,
    ) -> R7FamilyLifecycleEvent | None:
        try:
            if type(command) is not GetExactR7FamilyEventCommand:
                raise TypeError("R7 family event query command is invalid")
            command.__post_init__()
            return self._repository.get_exact_event(
                event_ref=command.event_ref,
                as_of=command.as_of,
            )
        except R7FamilyLifecycleUnavailable:
            raise
        except Exception as error:
            raise R7FamilyLifecycleUnavailable("R7 family event query is unavailable") from error


class AuditR7FamilyLifecycle:
    def __init__(self, repository: R7FamilyLifecycleEvidenceQueryRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: AuditR7FamilyLifecycleCommand,
    ) -> R7FamilyLifecycleAuditPage:
        try:
            if type(command) is not AuditR7FamilyLifecycleCommand:
                raise TypeError("R7 family audit command is invalid")
            command.__post_init__()
            with self._repository.atomic():
                return self._repository.audit_events(
                    family_ref=command.family_ref,
                    as_of=command.as_of,
                    page_size=command.page_size,
                    cursor=command.cursor,
                )
        except R7FamilyLifecycleUnavailable:
            raise
        except Exception as error:
            raise R7FamilyLifecycleUnavailable("R7 family audit is unavailable") from error


__all__ = [
    "AuditR7FamilyLifecycle",
    "AuditR7FamilyLifecycleCommand",
    "GetExactR7FamilyAuthorization",
    "GetExactR7FamilyAuthorizationCommand",
    "GetExactR7FamilyEvent",
    "GetExactR7FamilyEventCommand",
    "R7FamilyEventRef",
    "R7FamilyLifecycleAuditEntry",
    "R7FamilyLifecycleAuditPage",
    "R7FamilyLifecycleEvidenceQueryRepository",
]
