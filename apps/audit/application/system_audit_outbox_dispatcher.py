"""Dormant application contract for claiming and publishing audit outbox rows.

This module intentionally has no Django or publisher implementation import.  A
composition root may inject the infrastructure repository and a concrete
publisher later; until then the contract only proves claim ownership, stable
failure handling, and bounded batch accounting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from apps.audit.domain.system_audit_event import SystemAuditEvent


class SystemAuditOutboxDispatchUnavailable(Exception):
    """The dispatcher cannot claim or finalize a requested outbox row."""


class SystemAuditOutboxDispatchConflict(Exception):
    """A claim token or transition no longer belongs to this dispatcher."""


class SystemAuditOutboxPublisher(Protocol):
    """Injected side-effect boundary; no concrete publisher is wired here."""

    def publish(self, event: SystemAuditEvent) -> None:
        """Publish one immutable event or raise a bounded implementation error."""


@dataclass(frozen=True, slots=True)
class SystemAuditOutboxClaimDTO:
    """Claim returned by an infrastructure repository."""

    outbox_id: UUID
    event: SystemAuditEvent
    worker_id: str
    claim_token: str
    claimed_at: datetime
    attempt_count: int


class SystemAuditOutboxDispatchRepository(Protocol):
    """Minimal repository port used by the application dispatcher."""

    def claim_due(
        self, *, worker_id: str, as_of: datetime, limit: int
    ) -> tuple[SystemAuditOutboxClaimDTO, ...]:
        """Claim due rows under one repository unit of work."""

    def mark_delivered(
        self,
        *,
        outbox_id: UUID,
        worker_id: str,
        claim_token: str,
        delivered_at: datetime,
    ) -> object:
        """Finalize one claim as delivered."""

    def mark_failed(
        self,
        *,
        outbox_id: UUID,
        worker_id: str,
        claim_token: str,
        error_code: str,
        failed_at: datetime,
    ) -> object:
        """Finalize one claim as failed without exception text."""


class SystemAuditOutboxDispatchUnitOfWork(Protocol):
    """One same-alias transaction boundary for claim and finalization."""

    def __enter__(self) -> None:
        """Enter the private repository transaction."""

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Exit and commit/rollback the private repository transaction."""


@dataclass(frozen=True, slots=True)
class DispatchSystemAuditOutboxCommand:
    """Bounded worker dispatch request."""

    worker_id: str
    as_of: datetime
    limit: int = 20


@dataclass(frozen=True, slots=True)
class DispatchSystemAuditOutboxResult:
    """Stable batch outcome counters."""

    requested: int
    claimed: int
    delivered: int
    failed: int

    @property
    def outcome(self) -> str:
        """Publish a task-contract-compatible business outcome."""

        if self.failed:
            return "partial" if self.delivered else "failed"
        return "success" if self.delivered else "noop"


class DispatchSystemAuditOutboxUseCase:
    """Claim and publish a bounded batch without wiring a real publisher."""

    __slots__ = ("_repository", "_publisher", "_unit_of_work")

    def __init__(
        self,
        repository: SystemAuditOutboxDispatchRepository,
        publisher: SystemAuditOutboxPublisher,
        unit_of_work: SystemAuditOutboxDispatchUnitOfWork,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._unit_of_work = unit_of_work

    def execute(self, command: DispatchSystemAuditOutboxCommand) -> DispatchSystemAuditOutboxResult:
        """Claim, publish, and finalize one bounded batch."""

        self._validate(command)
        claimed: tuple[SystemAuditOutboxClaimDTO, ...]
        try:
            with self._unit_of_work:
                claimed = self._repository.claim_due(
                    worker_id=command.worker_id,
                    as_of=command.as_of,
                    limit=command.limit,
                )
        except Exception as error:
            raise SystemAuditOutboxDispatchUnavailable("outbox claim failed") from error

        delivered = 0
        failed = 0
        for item in claimed:
            try:
                self._publisher.publish(item.event)
            except Exception:
                failed += 1
                try:
                    with self._unit_of_work:
                        self._repository.mark_failed(
                            outbox_id=item.outbox_id,
                            worker_id=item.worker_id,
                            claim_token=item.claim_token,
                            error_code="publisher_error",
                            failed_at=command.as_of,
                        )
                except Exception as error:
                    raise SystemAuditOutboxDispatchConflict(
                        "outbox failure transition was not committed"
                    ) from error
                continue
            try:
                with self._unit_of_work:
                    self._repository.mark_delivered(
                        outbox_id=item.outbox_id,
                        worker_id=item.worker_id,
                        claim_token=item.claim_token,
                        delivered_at=command.as_of,
                    )
            except Exception as error:
                raise SystemAuditOutboxDispatchConflict(
                    "outbox delivery transition was not committed"
                ) from error
            delivered += 1
        return DispatchSystemAuditOutboxResult(
            requested=command.limit,
            claimed=len(claimed),
            delivered=delivered,
            failed=failed,
        )

    @staticmethod
    def _validate(command: DispatchSystemAuditOutboxCommand) -> None:
        if not isinstance(command.worker_id, str) or not command.worker_id:
            raise SystemAuditOutboxDispatchUnavailable("worker_id is required")
        if command.as_of.tzinfo is None or command.as_of.utcoffset() is None:
            raise SystemAuditOutboxDispatchUnavailable("as_of must be timezone-aware")
        if (
            not isinstance(command.limit, int)
            or isinstance(command.limit, bool)
            or not 0 < command.limit <= 100
        ):
            raise SystemAuditOutboxDispatchUnavailable("limit must be between 1 and 100")


__all__ = [
    "DispatchSystemAuditOutboxCommand",
    "DispatchSystemAuditOutboxResult",
    "DispatchSystemAuditOutboxUseCase",
    "SystemAuditOutboxClaimDTO",
    "SystemAuditOutboxDispatchConflict",
    "SystemAuditOutboxDispatchRepository",
    "SystemAuditOutboxDispatchUnavailable",
    "SystemAuditOutboxPublisher",
]
