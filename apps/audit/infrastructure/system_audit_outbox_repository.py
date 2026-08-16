"""Closed-world claim repository for the system-audit transactional outbox.

The repository owns only outbox persistence and bounded claim-state changes.  It
does not publish to Data Center, Celery, Kafka, or any other runtime consumer.
Every selector restores the complete table first so a malformed unrelated row
cannot be hidden by a filtered query.  PostgreSQL lease/race evidence remains a
separate deployment gate; the isolated component tests are structural only.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.application.system_audit_outbox_observability import (
    SystemAuditOutboxBacklogSnapshot,
)
from apps.audit.domain.system_audit_event import JSONValue, SystemAuditEvent
from apps.audit.infrastructure.system_audit_event_codec import decode, encode
from apps.audit.infrastructure.system_audit_outbox_models import (
    _UOW,
    SystemAuditOutboxModel,
    _activate_system_audit_outbox_uow,
    _claim_system_audit_outbox_insert,
    _claim_system_audit_outbox_state_mutation,
)


class SystemAuditOutboxUnavailable(Exception):
    """The requested outbox row is absent or not claimable."""


class SystemAuditOutboxConflict(Exception):
    """A first-winner, claim-token, or state transition conflict occurred."""


class SystemAuditOutboxCorruption(Exception):
    """Persisted outbox state cannot be restored as one closed world."""


class SystemAuditOutboxClock(Protocol):
    """Authoritative clock for outbox mutation timestamps."""

    def now(self) -> datetime:
        """Return one timezone-aware timestamp."""


class DjangoSystemAuditOutboxClock:
    """Django timezone-backed clock used by a composition root."""

    def now(self) -> datetime:
        """Return the current timezone-aware timestamp."""

        return timezone.now()


@dataclass(frozen=True, slots=True)
class SystemAuditOutboxRecord:
    """Strictly restored outbox row and its immutable audit event."""

    outbox_id: UUID
    event: SystemAuditEvent
    status: str
    attempt_count: int
    available_at: datetime
    claimed_at: datetime | None
    claimed_by: str | None
    claim_token: str | None
    delivered_at: datetime | None
    last_error_code: str | None
    last_error_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SystemAuditOutboxClaim:
    """One claimed event handed to an injected publisher."""

    outbox_id: UUID
    event: SystemAuditEvent
    worker_id: str
    claim_token: str
    claimed_at: datetime
    attempt_count: int


class DjangoSystemAuditOutboxRepository:
    """Append-only outbox enqueue plus private claim-state transitions."""

    __slots__ = ("_clock", "_lease_duration", "_uow", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: SystemAuditOutboxClock | None = None,
        lease_duration: timedelta = timedelta(minutes=5),
    ) -> None:
        if not isinstance(lease_duration, timedelta) or lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._using = using
        self._clock = clock or DjangoSystemAuditOutboxClock()
        self._lease_duration = lease_duration
        self._uow: object | None = None

    @property
    def database_alias(self) -> str:
        """Return the database alias used for claims and state transitions."""

        return self._using

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one non-nested outbox unit of work."""

        if self._uow is not None or _UOW.get() is not None:
            raise SystemAuditOutboxConflict("system audit outbox UOW cannot be nested")
        token = object()
        self._uow = token
        try:
            with transaction.atomic(using=self._using), _activate_system_audit_outbox_uow(token):
                yield
        finally:
            self._uow = None

    def now(self) -> datetime:
        """Return an aware clock or fail closed."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise SystemAuditOutboxCorruption("system audit outbox clock is naive")
        return value

    def enqueue(
        self,
        event: SystemAuditEvent,
        *,
        available_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> SystemAuditOutboxRecord:
        """Insert one event, or return the exact idempotent first winner."""

        self._require_uow()
        try:
            event.validate_hashes()
        except (TypeError, ValueError) as error:
            raise SystemAuditOutboxCorruption("outbox event candidate is invalid") from error
        created = created_at or self.now()
        self._require_aware(created, "created_at")
        available = available_at or created
        self._require_aware(available, "available_at")
        if available < created:
            raise SystemAuditOutboxConflict("outbox availability precedes creation")

        state = self._state(lock=True)
        identity_matches = tuple(item for item in state if item.event.event_id == event.event_id)
        idempotency_matches = tuple(
            item for item in state if item.event.idempotency_key == event.idempotency_key
        )
        for matches in (identity_matches, idempotency_matches):
            if len(matches) > 1:
                raise SystemAuditOutboxCorruption("outbox first-winner identity is ambiguous")
        existing = (
            identity_matches[0]
            if identity_matches
            else (idempotency_matches[0] if idempotency_matches else None)
        )
        if existing is not None:
            if existing.event != event:
                raise SystemAuditOutboxConflict("outbox identity already has another payload")
            return existing.record

        row = SystemAuditOutboxModel(
            outbox_id=uuid4(),
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            payload=dict(encode(event)),
            payload_hash=event.content_hash,
            available_at=available,
            created_at=created,
            updated_at=created,
        )
        values = {
            "outbox_id": row.outbox_id,
            "event_id": row.event_id,
            "idempotency_key": row.idempotency_key,
            "payload": row.payload,
            "payload_hash": row.payload_hash,
            "status": row.status,
            "attempt_count": row.attempt_count,
            "available_at": row.available_at,
            "claimed_at": row.claimed_at,
            "claimed_by": row.claimed_by,
            "claim_token": row.claim_token,
            "delivered_at": row.delivered_at,
            "last_error_code": row.last_error_code,
            "last_error_at": row.last_error_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        try:
            with transaction.atomic(using=self._using):
                with _claim_system_audit_outbox_insert(
                    token=self._require_uow_token(),
                    model_type=SystemAuditOutboxModel,
                    expected_values=values,
                ):
                    row.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self._find_exact_identity(event)
            if winner is not None and winner.event == event:
                return winner
            raise SystemAuditOutboxConflict("outbox enqueue lost its first-winner race") from None
        return self._restore(row)

    def get_exact(self, *, outbox_id: UUID) -> SystemAuditOutboxRecord | None:
        """Restore one row after validating the entire outbox table."""

        state = self._state()
        matches = tuple(item for item in state if item.outbox_id == outbox_id)
        if len(matches) > 1:
            raise SystemAuditOutboxCorruption("outbox primary identity is ambiguous")
        return matches[0].record if matches else None

    def get_backlog_snapshot(self, *, as_of: datetime) -> SystemAuditOutboxBacklogSnapshot:
        """Aggregate a credential-free backlog view without changing state.

        The complete outbox is restored before aggregation, preserving the
        repository's closed-world corruption checks.  Pending and claimed
        rows form the recoverable backlog; failed and delivered rows remain
        visible as terminal counters but are not mixed into that backlog.
        """

        self._require_cutoff(as_of)
        state = self._state()
        for item in state:
            for field in (
                "created_at",
                "updated_at",
                "claimed_at",
                "delivered_at",
                "last_error_at",
            ):
                value = getattr(item, field)
                if value is not None and value > as_of:
                    raise SystemAuditOutboxCorruption(
                        f"outbox {field} is after backlog observation cutoff"
                    )
        pending = tuple(
            item for item in state if item.status == SystemAuditOutboxModel.STATUS_PENDING
        )
        claimed = tuple(
            item for item in state if item.status == SystemAuditOutboxModel.STATUS_CLAIMED
        )
        failed_count = sum(
            1 for item in state if item.status == SystemAuditOutboxModel.STATUS_FAILED
        )
        delivered_count = sum(
            1 for item in state if item.status == SystemAuditOutboxModel.STATUS_DELIVERED
        )
        expired_claimed_count = sum(
            1
            for item in claimed
            if item.claimed_at is not None and item.claimed_at + self._lease_duration <= as_of
        )
        backlog = pending + claimed
        oldest_backlog_at = min(
            (item.created_at for item in backlog),
            default=None,
        )
        oldest_claimed_at = min(
            (item.claimed_at for item in claimed if item.claimed_at is not None),
            default=None,
        )
        return SystemAuditOutboxBacklogSnapshot(
            as_of=as_of,
            pending_count=len(pending),
            due_pending_count=sum(1 for item in pending if item.available_at <= as_of),
            claimed_count=len(claimed),
            expired_claimed_count=expired_claimed_count,
            failed_count=failed_count,
            delivered_count=delivered_count,
            oldest_backlog_at=oldest_backlog_at,
            oldest_claimed_at=oldest_claimed_at,
        )

    def claim_due(
        self,
        *,
        worker_id: str,
        as_of: datetime,
        limit: int,
    ) -> tuple[SystemAuditOutboxClaim, ...]:
        """Atomically claim due rows and reclaim expired worker leases.

        A claimed row whose lease has expired is eligible for a new worker and
        receives a fresh token.  The previous token therefore cannot finalize
        the row after a worker timeout; the claim remains protected by the
        same row lock and private transition capability as a first claim.
        """

        self._require_uow()
        self._require_text(worker_id, "worker_id", max_length=128)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 0 < limit <= 100:
            raise SystemAuditOutboxConflict("outbox claim limit is outside 1..100")
        self._require_cutoff(as_of)
        state = self._state(lock=True)
        due = [
            item
            for item in state
            if (item.status == SystemAuditOutboxModel.STATUS_PENDING and item.available_at <= as_of)
            or (
                item.status == SystemAuditOutboxModel.STATUS_CLAIMED
                and item.claimed_at is not None
                and item.claimed_at + self._lease_duration <= as_of
            )
        ][:limit]
        claims: list[SystemAuditOutboxClaim] = []
        for item in due:
            row = item._row
            token = uuid4().hex
            row.status = SystemAuditOutboxModel.STATUS_CLAIMED
            row.attempt_count = item.attempt_count + 1
            row.claimed_at = as_of
            row.claimed_by = worker_id
            row.claim_token = token
            row.updated_at = as_of
            self._save_state(
                row,
                fields=(
                    "status",
                    "attempt_count",
                    "claimed_at",
                    "claimed_by",
                    "claim_token",
                    "updated_at",
                ),
            )
            claims.append(
                SystemAuditOutboxClaim(
                    outbox_id=item.outbox_id,
                    event=item.event,
                    worker_id=worker_id,
                    claim_token=token,
                    claimed_at=as_of,
                    attempt_count=item.attempt_count + 1,
                )
            )
        return tuple(claims)

    def mark_delivered(
        self,
        *,
        outbox_id: UUID,
        worker_id: str,
        claim_token: str,
        delivered_at: datetime,
    ) -> SystemAuditOutboxRecord:
        """Commit a claimed row as delivered with exact token ownership."""

        self._require_uow()
        self._require_claim_owner(worker_id, claim_token)
        self._require_cutoff(delivered_at)
        item = self._locked_item(outbox_id)
        self._require_claimed(item, worker_id, claim_token)
        if item.claimed_at is None or delivered_at < item.claimed_at:
            raise SystemAuditOutboxConflict("delivery clock precedes claim")
        row = item._row
        row.status = SystemAuditOutboxModel.STATUS_DELIVERED
        row.delivered_at = delivered_at
        row.updated_at = delivered_at
        self._save_state(row, fields=("status", "delivered_at", "updated_at"))
        return self._restore(row)

    def mark_failed(
        self,
        *,
        outbox_id: UUID,
        worker_id: str,
        claim_token: str,
        error_code: str,
        failed_at: datetime,
    ) -> SystemAuditOutboxRecord:
        """Commit a claimed row as terminal failed without leaking exception text."""

        self._require_uow()
        self._require_claim_owner(worker_id, claim_token)
        self._require_text(error_code, "error_code", max_length=128)
        self._require_cutoff(failed_at)
        item = self._locked_item(outbox_id)
        self._require_claimed(item, worker_id, claim_token)
        if item.claimed_at is None or failed_at < item.claimed_at:
            raise SystemAuditOutboxConflict("failure clock precedes claim")
        row = item._row
        row.status = SystemAuditOutboxModel.STATUS_FAILED
        row.last_error_code = error_code
        row.last_error_at = failed_at
        row.updated_at = failed_at
        self._save_state(
            row,
            fields=("status", "last_error_code", "last_error_at", "updated_at"),
        )
        return self._restore(row)

    def _save_state(self, row: SystemAuditOutboxModel, *, fields: tuple[str, ...]) -> None:
        """Persist one state transition through the model's private capability."""

        with _claim_system_audit_outbox_state_mutation(
            token=self._require_uow_token(),
            model_type=SystemAuditOutboxModel,
            outbox_id=row.outbox_id,
            fields=fields,
            expected_values={field: getattr(row, field) for field in fields},
        ):
            row.save(update_fields=fields, using=self._using)

    def _find_exact_identity(self, event: SystemAuditEvent) -> SystemAuditOutboxRecord | None:
        state = self._state(lock=True)
        matches = tuple(
            item
            for item in state
            if item.event.event_id == event.event_id
            or item.event.idempotency_key == event.idempotency_key
        )
        if len(matches) > 1:
            raise SystemAuditOutboxCorruption("outbox identity collision is ambiguous")
        return matches[0].record if matches else None

    def _locked_item(self, outbox_id: UUID) -> "_StateRow":
        state = self._state(lock=True)
        matches = tuple(item for item in state if item.outbox_id == outbox_id)
        if not matches:
            raise SystemAuditOutboxUnavailable("outbox row is absent")
        if len(matches) > 1:
            raise SystemAuditOutboxCorruption("outbox row identity is ambiguous")
        return matches[0]

    def _state(self, *, lock: bool = False) -> tuple["_StateRow", ...]:
        manager = SystemAuditOutboxModel._default_manager.using(self._using)
        rows = manager.select_for_update() if lock else manager
        restored = tuple(_StateRow(self._restore(row), row) for row in rows.all())
        _validate_closed_world(restored)
        return restored

    def _restore(self, row: SystemAuditOutboxModel) -> SystemAuditOutboxRecord:
        try:
            payload = cast(Mapping[str, JSONValue], row.payload)
            event = decode(payload)
        except (TypeError, ValueError) as error:
            raise SystemAuditOutboxCorruption(
                "outbox canonical payload cannot be restored"
            ) from error
        if encode(event) != row.payload:
            raise SystemAuditOutboxCorruption("outbox canonical payload is not exact")
        if (
            event.event_id != row.event_id
            or event.idempotency_key != row.idempotency_key
            or event.content_hash != row.payload_hash
        ):
            raise SystemAuditOutboxCorruption(
                "outbox identity or payload hash does not match event"
            )
        if row.updated_at < row.created_at:
            raise SystemAuditOutboxCorruption("outbox updated clock precedes created clock")
        for name in ("available_at", "created_at", "updated_at"):
            self._require_aware(getattr(row, name), name)
        for name in ("claimed_at", "delivered_at", "last_error_at"):
            value = getattr(row, name)
            if value is not None:
                self._require_aware(value, name)
        if row.available_at < row.created_at:
            raise SystemAuditOutboxCorruption("outbox available clock precedes created clock")
        if row.claimed_at is not None:
            if row.claimed_at < row.created_at:
                raise SystemAuditOutboxCorruption("outbox claim clock precedes created clock")
            if row.claimed_at > row.updated_at:
                raise SystemAuditOutboxCorruption("outbox claim clock exceeds updated clock")
        if row.delivered_at is not None:
            if row.claimed_at is None or row.delivered_at < row.claimed_at:
                raise SystemAuditOutboxCorruption("outbox delivery clock precedes claim clock")
            if row.delivered_at != row.updated_at:
                raise SystemAuditOutboxCorruption(
                    "outbox delivery clock does not equal updated clock"
                )
        if row.last_error_at is not None:
            if row.claimed_at is None or row.last_error_at < row.claimed_at:
                raise SystemAuditOutboxCorruption("outbox failure clock precedes claim clock")
            if row.last_error_at != row.updated_at:
                raise SystemAuditOutboxCorruption(
                    "outbox failure clock does not equal updated clock"
                )
        if row.status == SystemAuditOutboxModel.STATUS_PENDING:
            if (
                row.claimed_at is not None
                or row.claimed_by is not None
                or row.claim_token is not None
            ):
                raise SystemAuditOutboxCorruption("pending outbox row still has claim state")
            if row.delivered_at is not None or row.last_error_at is not None:
                raise SystemAuditOutboxCorruption("pending outbox row has terminal state")
            if row.last_error_code is not None:
                raise SystemAuditOutboxCorruption("pending outbox row has failure code")
            if row.updated_at != row.created_at:
                raise SystemAuditOutboxCorruption(
                    "pending outbox row updated clock does not equal created clock"
                )
        elif row.status == SystemAuditOutboxModel.STATUS_CLAIMED:
            if not row.claimed_at or not row.claimed_by or not row.claim_token:
                raise SystemAuditOutboxCorruption("claimed outbox row is missing claim state")
            if row.updated_at != row.claimed_at:
                raise SystemAuditOutboxCorruption(
                    "claimed outbox row updated clock does not equal claim clock"
                )
            if row.delivered_at is not None or row.last_error_at is not None:
                raise SystemAuditOutboxCorruption("claimed outbox row has terminal state")
            if row.last_error_code is not None:
                raise SystemAuditOutboxCorruption("claimed outbox row has failure code")
        elif row.status == SystemAuditOutboxModel.STATUS_DELIVERED:
            if (
                not row.claimed_at
                or not row.claimed_by
                or not row.claim_token
                or not row.delivered_at
            ):
                raise SystemAuditOutboxCorruption("delivered outbox row is missing terminal state")
            if row.last_error_at is not None or row.last_error_code is not None:
                raise SystemAuditOutboxCorruption("delivered outbox row has failure state")
        elif row.status == SystemAuditOutboxModel.STATUS_FAILED:
            if not row.claimed_at or not row.claimed_by or not row.claim_token:
                raise SystemAuditOutboxCorruption("failed outbox row is missing claim state")
            if not row.last_error_code or not row.last_error_at:
                raise SystemAuditOutboxCorruption("failed outbox row is missing failure state")
            if row.delivered_at is not None:
                raise SystemAuditOutboxCorruption("failed outbox row is already delivered")
        else:
            raise SystemAuditOutboxCorruption("outbox status is not canonical")
        return SystemAuditOutboxRecord(
            outbox_id=row.outbox_id,
            event=event,
            status=row.status,
            attempt_count=row.attempt_count,
            available_at=row.available_at,
            claimed_at=row.claimed_at,
            claimed_by=row.claimed_by,
            claim_token=row.claim_token,
            delivered_at=row.delivered_at,
            last_error_code=row.last_error_code,
            last_error_at=row.last_error_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _require_claimed(self, item: "_StateRow", worker_id: str, claim_token: str) -> None:
        if item.status != SystemAuditOutboxModel.STATUS_CLAIMED:
            raise SystemAuditOutboxConflict("outbox row is no longer claimed")
        if item.claimed_by != worker_id or item.claim_token != claim_token:
            raise SystemAuditOutboxConflict("outbox claim token does not belong to worker")

    def _require_uow(self) -> None:
        if self._uow is None or _UOW.get() is not self._uow:
            raise SystemAuditOutboxConflict("outbox mutation requires repository.atomic()")

    def _require_uow_token(self) -> object:
        self._require_uow()
        assert self._uow is not None
        return self._uow

    def _require_cutoff(self, value: datetime) -> None:
        self._require_aware(value, "as_of")
        if value > self.now():
            raise SystemAuditOutboxUnavailable("future outbox cutoff is forbidden")

    @staticmethod
    def _require_aware(value: datetime, field: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise SystemAuditOutboxCorruption(f"outbox {field} is naive")

    @staticmethod
    def _require_text(value: str, field: str, *, max_length: int) -> None:
        if not isinstance(value, str) or not value or len(value) > max_length:
            raise SystemAuditOutboxConflict(f"outbox {field} is invalid")

    @staticmethod
    def _require_claim_owner(worker_id: str, claim_token: str) -> None:
        if not isinstance(worker_id, str) or not worker_id:
            raise SystemAuditOutboxConflict("outbox worker id is invalid")
        if not isinstance(claim_token, str) or not claim_token:
            raise SystemAuditOutboxConflict("outbox claim token is invalid")


@dataclass(frozen=True, slots=True)
class _StateRow:
    record: SystemAuditOutboxRecord
    _row: SystemAuditOutboxModel

    @property
    def outbox_id(self) -> UUID:
        return self.record.outbox_id

    @property
    def event(self) -> SystemAuditEvent:
        return self.record.event

    @property
    def status(self) -> str:
        return self.record.status

    @property
    def attempt_count(self) -> int:
        return self.record.attempt_count

    @property
    def available_at(self) -> datetime:
        return self.record.available_at

    @property
    def claimed_at(self) -> datetime | None:
        return self.record.claimed_at

    @property
    def claimed_by(self) -> str | None:
        return self.record.claimed_by

    @property
    def claim_token(self) -> str | None:
        return self.record.claim_token

    @property
    def delivered_at(self) -> datetime | None:
        return self.record.delivered_at

    @property
    def last_error_code(self) -> str | None:
        return self.record.last_error_code

    @property
    def last_error_at(self) -> datetime | None:
        return self.record.last_error_at

    @property
    def created_at(self) -> datetime:
        return self.record.created_at

    @property
    def updated_at(self) -> datetime:
        return self.record.updated_at


def _validate_closed_world(state: tuple[_StateRow, ...]) -> None:
    """Reject duplicate identities and impossible claim-state combinations."""

    event_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    for item in state:
        if item.event.event_id in event_ids:
            raise SystemAuditOutboxCorruption("outbox event identity is duplicated")
        if item.event.idempotency_key in idempotency_keys:
            raise SystemAuditOutboxCorruption("outbox idempotency key is duplicated")
        event_ids.add(item.event.event_id)
        idempotency_keys.add(item.event.idempotency_key)
        if item.updated_at < item.created_at:
            raise SystemAuditOutboxCorruption("outbox clock order is invalid")


__all__ = [
    "DjangoSystemAuditOutboxClock",
    "DjangoSystemAuditOutboxRepository",
    "SystemAuditOutboxClaim",
    "SystemAuditOutboxClock",
    "SystemAuditOutboxConflict",
    "SystemAuditOutboxCorruption",
    "SystemAuditOutboxRecord",
    "SystemAuditOutboxUnavailable",
]
