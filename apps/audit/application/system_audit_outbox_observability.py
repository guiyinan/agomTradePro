"""Read-only application contracts for transactional outbox observability.

The snapshot is deliberately separate from the dispatcher contract.  It does
not claim rows, renew leases, publish events, or expose claim credentials; a
composition root can later project it into metrics or an operator query.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class SystemAuditOutboxBacklogCorruption(Exception):
    """The repository returned a snapshot that does not match the request."""


@dataclass(frozen=True, slots=True)
class SystemAuditOutboxBacklogSnapshot:
    """Immutable, credential-free counts for one outbox observation point.

    ``backlog_count`` contains pending and currently claimed rows.  Failed
    rows are terminal and therefore counted separately rather than hidden in
    the recovery backlog.  ``oldest_backlog_at`` is based on immutable event
    creation time; ``oldest_claimed_at`` is based on the current lease claim
    time so lease recovery can be observed independently.
    """

    as_of: datetime
    pending_count: int
    due_pending_count: int
    claimed_count: int
    expired_claimed_count: int
    failed_count: int
    delivered_count: int
    oldest_backlog_at: datetime | None
    oldest_claimed_at: datetime | None

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "as_of")
        for name in (
            "pending_count",
            "due_pending_count",
            "claimed_count",
            "expired_claimed_count",
            "failed_count",
            "delivered_count",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.due_pending_count > self.pending_count:
            raise ValueError("due_pending_count cannot exceed pending_count")
        if self.expired_claimed_count > self.claimed_count:
            raise ValueError("expired_claimed_count cannot exceed claimed_count")
        if self.backlog_count == 0 and self.oldest_backlog_at is not None:
            raise ValueError("oldest_backlog_at requires a non-empty backlog")
        if self.backlog_count > 0 and self.oldest_backlog_at is None:
            raise ValueError("non-empty backlog requires oldest_backlog_at")
        if self.claimed_count == 0 and self.oldest_claimed_at is not None:
            raise ValueError("oldest_claimed_at requires a claimed row")
        if self.claimed_count > 0 and self.oldest_claimed_at is None:
            raise ValueError("claimed rows require oldest_claimed_at")
        if self.oldest_backlog_at is not None:
            _require_aware(self.oldest_backlog_at, "oldest_backlog_at")
            if self.oldest_backlog_at > self.as_of:
                raise ValueError("oldest_backlog_at cannot be after as_of")
        if self.oldest_claimed_at is not None:
            _require_aware(self.oldest_claimed_at, "oldest_claimed_at")
            if self.oldest_claimed_at > self.as_of:
                raise ValueError("oldest_claimed_at cannot be after as_of")

    @property
    def backlog_count(self) -> int:
        """Return pending plus currently claimed rows."""

        return self.pending_count + self.claimed_count

    @property
    def oldest_backlog_age_seconds(self) -> float | None:
        """Return the non-negative age of the oldest pending/claimed event."""

        return _age_seconds(self.as_of, self.oldest_backlog_at)

    @property
    def oldest_claimed_age_seconds(self) -> float | None:
        """Return the non-negative age of the oldest current claim lease."""

        return _age_seconds(self.as_of, self.oldest_claimed_at)


class SystemAuditOutboxBacklogReader(Protocol):
    """Read-only repository port for one outbox backlog observation."""

    def get_backlog_snapshot(self, *, as_of: datetime) -> SystemAuditOutboxBacklogSnapshot:
        """Return a closed-world snapshot without changing outbox state."""


@dataclass(frozen=True, slots=True)
class GetSystemAuditOutboxBacklogCommand:
    """Bounded read request for one timezone-aware observation point."""

    as_of: datetime

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "as_of")


class GetSystemAuditOutboxBacklogUseCase:
    """Read and validate one immutable outbox backlog snapshot."""

    __slots__ = ("_reader",)

    def __init__(self, reader: SystemAuditOutboxBacklogReader) -> None:
        self._reader = reader

    def execute(
        self, command: GetSystemAuditOutboxBacklogCommand
    ) -> SystemAuditOutboxBacklogSnapshot:
        """Return the exact requested observation point without side effects."""

        snapshot = self._reader.get_backlog_snapshot(as_of=command.as_of)
        if snapshot.as_of != command.as_of:
            raise SystemAuditOutboxBacklogCorruption(
                "outbox backlog reader substituted the observation cutoff"
            )
        return snapshot


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _age_seconds(as_of: datetime, observed_at: datetime | None) -> float | None:
    if observed_at is None:
        return None
    return (as_of - observed_at).total_seconds()


__all__ = [
    "GetSystemAuditOutboxBacklogCommand",
    "GetSystemAuditOutboxBacklogUseCase",
    "SystemAuditOutboxBacklogCorruption",
    "SystemAuditOutboxBacklogReader",
    "SystemAuditOutboxBacklogSnapshot",
]
