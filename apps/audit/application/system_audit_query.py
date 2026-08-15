"""Staff-only, ID/PIT bounded reads for the system audit ledger.

The application layer knows only the Domain event and a repository Protocol.
Concrete Django composition remains a later step; in particular, this module
does not turn an authenticated request into an audit authority by itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from apps.audit.domain.system_audit_event import SystemAuditEvent

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_READER_CONTEXT_CAPABILITY = object()


def _require_token(value: object, field: str) -> None:
    """Require one bounded, whitespace-free query identity token."""

    if (
        type(value) is not str
        or not value
        or len(value) > 192
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field} must be a bounded canonical token")


def _require_digest(value: object, field: str) -> None:
    """Require one lowercase SHA-256 authority digest."""

    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


class SystemAuditQueryUnavailable(Exception):
    """The caller is not eligible or the requested PIT is unavailable."""


class SystemAuditQueryCorruption(Exception):
    """The repository returned a value that does not match the selector."""


@dataclass(frozen=True, slots=True)
class SystemAuditReaderContext:
    """Provider-issued staff scope used only for read authorization."""

    actor_id: str
    user_id: int
    tenant_id: str
    owner_id: str
    authority_content_hash: str
    is_authenticated: bool
    is_staff: bool
    role: str
    _capability: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "audit reader actor_id")
        if not isinstance(self.user_id, int) or isinstance(self.user_id, bool) or self.user_id <= 0:
            raise ValueError("audit reader user_id must be a positive integer")
        _require_token(self.tenant_id, "audit reader tenant_id")
        _require_token(self.owner_id, "audit reader owner_id")
        _require_digest(self.authority_content_hash, "audit reader authority_content_hash")
        if not isinstance(self.is_authenticated, bool) or not isinstance(self.is_staff, bool):
            raise TypeError("audit reader authentication flags must be bools")
        _require_token(self.role, "audit reader role")

    @classmethod
    def _from_authority(
        cls,
        *,
        actor_id: str,
        user_id: int,
        tenant_id: str,
        owner_id: str,
        authority_content_hash: str,
        is_authenticated: bool,
        is_staff: bool,
        role: str,
    ) -> "SystemAuditReaderContext":
        """Issue a context only for the authority composition boundary."""

        context = cls(
            actor_id=actor_id,
            user_id=user_id,
            tenant_id=tenant_id,
            owner_id=owner_id,
            authority_content_hash=authority_content_hash,
            is_authenticated=is_authenticated,
            is_staff=is_staff,
            role=role,
        )
        object.__setattr__(context, "_capability", _READER_CONTEXT_CAPABILITY)
        return context

    @property
    def can_read(self) -> bool:
        """Return whether this context is staff-authenticated and user-bound.

        The application contract does not decide the eventual RBAC policy, but
        it must never treat an arbitrary service/actor string as the staff
        user represented by ``user_id``.  Concrete composition still has to
        source these facts from the authoritative authentication provider.
        """

        return (
            self._capability is _READER_CONTEXT_CAPABILITY
            and self.is_authenticated
            and self.is_staff
            and self.actor_id == f"django-user:{self.user_id}"
        )


class SystemAuditQueryRepository(Protocol):
    """Minimal repository surface required by the query use cases."""

    def list_events(self, *, stream_id: str, as_of: datetime) -> tuple[SystemAuditEvent, ...]:
        """Return the complete knowable stream prefix in sequence order."""

    def get_exact_by_hash(
        self,
        *,
        event_id: str,
        event_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Return one exact historical event or ``None`` at the PIT."""


@dataclass(frozen=True, slots=True)
class ListSystemAuditEventsCommand:
    """Bounded stream/PIT query command."""

    stream_id: str
    as_of: datetime
    reader: SystemAuditReaderContext
    page_size: int = 50
    after_sequence_no: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stream_id, str) or not self.stream_id:
            raise ValueError("audit stream_id must be a non-empty string")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("audit as_of must be timezone-aware")
        if self.page_size <= 0 or self.page_size > 100:
            raise ValueError("audit page_size must be between 1 and 100")
        if self.after_sequence_no is not None and self.after_sequence_no < 0:
            raise ValueError("audit after_sequence_no cannot be negative")


@dataclass(frozen=True, slots=True)
class GetSystemAuditEventCommand:
    """Exact identity/version/hash/PIT query command."""

    event_id: str
    event_version: str
    expected_content_hash: str
    as_of: datetime
    reader: SystemAuditReaderContext

    def __post_init__(self) -> None:
        for name, value in (
            ("event_id", self.event_id),
            ("event_version", self.event_version),
            ("expected_content_hash", self.expected_content_hash),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"audit {name} must be a non-empty string")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("audit as_of must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ListSystemAuditEventsResult:
    """Paged immutable audit event result."""

    events: tuple[SystemAuditEvent, ...]
    next_after_sequence_no: int | None


class ListSystemAuditEventsUseCase:
    """Authorize and page one immutable event stream."""

    def __init__(self, repository: SystemAuditQueryRepository) -> None:
        self._repository = repository

    def execute(self, command: ListSystemAuditEventsCommand) -> ListSystemAuditEventsResult:
        """Return only the staff-authorized, knowable stream prefix."""

        if not command.reader.can_read:
            raise SystemAuditQueryUnavailable(
                "system audit reads require an authenticated staff reader"
            )
        events = self._repository.list_events(
            stream_id=command.stream_id,
            as_of=command.as_of,
        )
        if any(event.stream_id != command.stream_id for event in events):
            raise SystemAuditQueryCorruption("repository returned an event from another stream")
        if any(
            previous.sequence_no >= current.sequence_no
            for previous, current in zip(events, events[1:])
        ):
            raise SystemAuditQueryCorruption("repository returned an unsorted audit stream")
        visible = tuple(
            event
            for event in events
            if command.after_sequence_no is None or event.sequence_no > command.after_sequence_no
        )[: command.page_size]
        has_more = (
            len(visible) == command.page_size
            and any(event.sequence_no > visible[-1].sequence_no for event in events)
            if visible
            else False
        )
        return ListSystemAuditEventsResult(
            events=visible,
            next_after_sequence_no=visible[-1].sequence_no if has_more else None,
        )


class GetSystemAuditEventUseCase:
    """Authorize and read one exact historical audit event."""

    def __init__(self, repository: SystemAuditQueryRepository) -> None:
        self._repository = repository

    def execute(self, command: GetSystemAuditEventCommand) -> SystemAuditEvent | None:
        """Return an exact event, preserving ``None`` for a missing PIT row."""

        if not command.reader.can_read:
            raise SystemAuditQueryUnavailable(
                "system audit reads require an authenticated staff reader"
            )
        event = self._repository.get_exact_by_hash(
            event_id=command.event_id,
            event_version=command.event_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if event is not None and (
            event.event_id != command.event_id
            or event.event_version != command.event_version
            or event.content_hash != command.expected_content_hash
        ):
            raise SystemAuditQueryCorruption("repository substituted the exact audit selector")
        return event


__all__ = [
    "GetSystemAuditEventCommand",
    "GetSystemAuditEventUseCase",
    "ListSystemAuditEventsCommand",
    "ListSystemAuditEventsResult",
    "ListSystemAuditEventsUseCase",
    "SystemAuditQueryCorruption",
    "SystemAuditQueryRepository",
    "SystemAuditQueryUnavailable",
    "SystemAuditReaderContext",
]
