"""Closed-world repository for the canonical system audit event ledger.

Every read restores the complete table before applying a selector, so an
unrelated future or tampered row cannot be hidden by a filtered query. PostgreSQL
empty-stream concurrency still requires a deployment-specific race proof;
SQLite component tests are structural evidence only.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from django.db import IntegrityError, connections, transaction
from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone

from apps.audit.domain.system_audit_event import AuditScopeRef, JSONValue, SystemAuditEvent
from apps.audit.infrastructure.system_audit_event_codec import decode, encode
from apps.audit.infrastructure.system_audit_models import (
    _UOW,
    SystemAuditEventModel,
    _activate_system_audit_uow,
    _claim_system_audit_batch_insert,
    _claim_system_audit_insert,
)


class SystemAuditUnavailable(Exception):
    """The requested audit event is absent or not knowable at the PIT."""


class SystemAuditConflict(Exception):
    """A first-winner or predecessor CAS would overwrite a different event."""


class SystemAuditCorruption(Exception):
    """Persisted audit state cannot be restored as one closed world."""


class SystemAuditClock(Protocol):
    """Authoritative persistence clock used by the repository."""

    def now(self) -> datetime:
        """Return one timezone-aware timestamp."""


class DjangoSystemAuditClock:
    """Django timezone-backed clock for repository composition roots."""

    def now(self) -> datetime:
        """Return the current timezone-aware timestamp."""

        return timezone.now()


@dataclass(frozen=True, slots=True)
class PersistedSystemAuditEvent:
    """Domain event plus its immutable persistence clock."""

    event: SystemAuditEvent
    persisted_at: datetime


@dataclass(frozen=True, slots=True)
class _StateRow:
    event: SystemAuditEvent
    row: SystemAuditEventModel


class DjangoSystemAuditEventRepository:
    """Private append-only ledger with exact, PIT and logical-head reads."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: SystemAuditClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoSystemAuditClock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one non-nested repository unit of work for append operations."""

        with transaction.atomic(using=self._using), _activate_system_audit_uow():
            yield

    @contextmanager
    def caller_owned_atomic(self) -> Iterator[None]:
        """Activate append capability inside an existing outer transaction."""

        connection = connections[self._using]
        if not connection.in_atomic_block or connection.get_autocommit():
            raise SystemAuditConflict("caller-owned audit UOW requires an active transaction")
        atomic_blocks = getattr(connection, "atomic_blocks", None)
        if not isinstance(atomic_blocks, list) or len(atomic_blocks) != 1:
            raise SystemAuditConflict("caller-owned audit UOW requires the outermost transaction")
        with _activate_system_audit_uow():
            yield

    def now(self) -> datetime:
        """Return an aware server clock or fail closed."""

        value = self._clock.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise SystemAuditCorruption("system audit clock is naive")
        return value

    def get_winner(
        self, *, event_id: str, event_version: str, as_of: datetime
    ) -> SystemAuditEvent | None:
        """Return the first exact event identity knowable at ``as_of``."""

        self._require_cutoff(as_of)
        state = self._state()
        matches = tuple(
            item.event
            for item in state
            if item.event.event_id == event_id and item.event.event_version == event_version
        )
        if len(matches) > 1:
            raise SystemAuditCorruption("system audit event identity is ambiguous")
        if not matches or matches[0].recorded_at > as_of:
            return None
        return matches[0]

    def lock_stream(self, stream_id: str) -> None:
        """Serialize one stream without scanning unrelated audit rows."""

        if not stream_id or stream_id.strip() != stream_id:
            raise SystemAuditConflict("audit stream identity is invalid")
        connection = connections[self._using]
        if connection.vendor != "postgresql":
            return
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [stream_id],
            )

    def lock_streams(self, stream_ids: tuple[str, ...]) -> None:
        """Serialize a bounded set of streams in stable order with one query."""

        ordered = tuple(sorted(set(stream_ids)))
        if (
            len(ordered) != len(stream_ids)
            or not ordered
            or any(not stream_id or stream_id.strip() != stream_id for stream_id in ordered)
        ):
            raise SystemAuditConflict("audit stream group identities are invalid")
        connection = connections[self._using]
        if connection.vendor != "postgresql":
            for stream_id in ordered:
                self.lock_stream(stream_id)
            return
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pg_advisory_xact_lock(hashtextextended(stream_id, 0))
                  FROM unnest(%s::text[]) AS stream(stream_id)
                 ORDER BY stream_id
                """,
                [list(ordered)],
            )

    def get_activation_group_state_targeted(
        self,
        *,
        identities: tuple[tuple[str, str], ...],
        stream_ids: tuple[str, ...],
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> tuple[
        dict[tuple[str, str], SystemAuditEvent],
        dict[str, SystemAuditEvent],
    ]:
        """Lock exact identity winners and latest stream heads in one bounded query."""

        self._require_cutoff(as_of)
        if (
            not identities
            or len(set(identities)) != len(identities)
            or not stream_ids
            or len(set(stream_ids)) != len(stream_ids)
        ):
            raise SystemAuditConflict("audit activation group selectors are invalid")
        identity_filter = Q()
        for event_id, event_version in identities:
            identity_filter |= Q(event_id=event_id, event_version=event_version)
        head_id = (
            SystemAuditEventModel._default_manager.using(self._using)
            .filter(stream_id=OuterRef("stream_id"), recorded_at__lte=as_of)
            .order_by("-sequence_no")
            .values("id")[:1]
        )
        rows = tuple(
            SystemAuditEventModel._default_manager.using(self._using)
            .select_for_update()
            .filter(identity_filter | Q(stream_id__in=stream_ids, id=Subquery(head_id)))
            .order_by("stream_id", "sequence_no", "id")
        )
        events = tuple(self._restore(row) for row in rows)
        winners: dict[tuple[str, str], SystemAuditEvent] = {}
        heads: dict[str, SystemAuditEvent] = {}
        identity_set = set(identities)
        stream_set = set(stream_ids)
        for event in events:
            identity = (event.event_id, event.event_version)
            if identity in identity_set and event.recorded_at <= as_of:
                if identity in winners:
                    raise SystemAuditCorruption("system audit event identity is ambiguous")
                winners[identity] = event
            if event.stream_id in stream_set:
                current = heads.get(event.stream_id)
                if current is None or event.sequence_no > current.sequence_no:
                    heads[event.stream_id] = event
        if any(head.scope != scope for head in heads.values()):
            raise SystemAuditUnavailable("audit stream scope differs from activation scope")
        return winners, heads

    def get_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
        lock: bool = False,
    ) -> SystemAuditEvent | None:
        """Read one exact event identity with a bounded indexed query."""

        self._require_cutoff(as_of)
        queryset = SystemAuditEventModel._default_manager.using(self._using).filter(
            event_id=event_id,
            event_version=event_version,
        )
        if lock:
            queryset = queryset.select_for_update()
        row = queryset.first()
        if row is None:
            return None
        event = self._restore(row)
        if event.recorded_at > as_of:
            return None
        return event

    def get_current_head_targeted(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef | None = None,
        lock: bool = False,
    ) -> SystemAuditEvent | None:
        """Read and optionally lock only the latest row of one stream."""

        self._require_cutoff(as_of)
        queryset = (
            SystemAuditEventModel._default_manager.using(self._using)
            .filter(stream_id=stream_id, recorded_at__lte=as_of)
            .order_by("-sequence_no")
        )
        if lock:
            queryset = queryset.select_for_update()
        row = queryset.first()
        if row is None:
            return None
        event = self._restore(row)
        if scope is not None and event.scope != scope:
            raise SystemAuditUnavailable("audit stream scope differs from activation scope")
        return event

    def get_exact_by_hash(
        self,
        *,
        event_id: str,
        event_version: str,
        expected_content_hash: str,
        as_of: datetime,
        scope: AuditScopeRef | None = None,
    ) -> SystemAuditEvent | None:
        """Return one historical event only when identity, hash and PIT match."""

        self._require_cutoff(as_of)
        state = self._state()
        matches = tuple(
            item.event
            for item in state
            if item.event.event_id == event_id
            and item.event.event_version == event_version
            and item.event.content_hash == expected_content_hash
        )
        visible = self._scope_visible(matches, scope=scope)
        if len(visible) > 1:
            raise SystemAuditCorruption("system audit exact selector is ambiguous")
        if not visible or visible[0].recorded_at > as_of:
            return None
        return visible[0]

    def get_current_head(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef | None = None,
    ) -> SystemAuditEvent | None:
        """Return the final visible stream head without expired/future fallback."""

        self._require_cutoff(as_of)
        stream = tuple(item.event for item in self._state() if item.event.stream_id == stream_id)
        visible = tuple(
            event
            for event in self._scope_visible(stream, scope=scope)
            if event.recorded_at <= as_of
        )
        if not visible:
            return None
        return max(visible, key=lambda value: value.sequence_no)

    def list_events(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef | None = None,
    ) -> tuple[SystemAuditEvent, ...]:
        """Return the visible stream prefix in sequence order."""

        self._require_cutoff(as_of)
        stream = tuple(item.event for item in self._state() if item.event.stream_id == stream_id)
        events = tuple(
            event
            for event in self._scope_visible(stream, scope=scope)
            if event.recorded_at <= as_of
        )
        return tuple(sorted(events, key=lambda value: value.sequence_no))

    def list_correlated_events(
        self,
        run_id: str | None,
        publication_id: str | None,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> tuple[SystemAuditEvent, ...]:
        """Return one PIT-bounded run chain selected by run or publication."""

        self._require_cutoff(as_of)
        if (run_id is None) == (publication_id is None):
            raise SystemAuditUnavailable("exactly one audit correlation selector is required")
        visible = tuple(
            event
            for event in self._scope_visible(
                tuple(item.event for item in self._state()),
                scope=scope,
            )
            if event.recorded_at <= as_of
        )
        if run_id is not None:
            selected = tuple(event for event in visible if event.correlations.run_id == run_id)
        else:
            anchors = tuple(event for event in visible if event.publication_id == publication_id)
            resolved_runs = {
                event.correlations.run_id
                for event in anchors
                if event.correlations.run_id is not None
            }
            selected = tuple(
                event
                for event in visible
                if event in anchors or event.correlations.run_id in resolved_runs
            )
        return tuple(
            sorted(
                selected,
                key=lambda event: (
                    event.recorded_at,
                    event.stream_id,
                    event.sequence_no,
                ),
            )
        )

    def list_archive_window(
        self,
        *,
        window_started_at: datetime,
        window_ended_at: datetime,
        as_of: datetime,
        scope: AuditScopeRef,
        limit: int,
    ) -> tuple[SystemAuditEvent, ...]:
        """Return one closed-world, scoped and bounded archive window."""

        self._require_cutoff(as_of)
        for value in (window_started_at, window_ended_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise SystemAuditUnavailable("archive window must be timezone-aware")
        if window_started_at >= window_ended_at:
            raise SystemAuditUnavailable("archive window order is invalid")
        if window_ended_at > as_of:
            raise SystemAuditUnavailable("archive window ends after the PIT cutoff")
        if type(limit) is not int or not 1 <= limit <= 10_001:
            raise SystemAuditUnavailable("archive window limit is invalid")
        if not isinstance(scope, AuditScopeRef):
            raise SystemAuditUnavailable("archive window scope is invalid")
        visible = self._scope_visible(
            tuple(item.event for item in self._state()),
            scope=scope,
        )
        selected = tuple(
            event for event in visible if window_started_at <= event.recorded_at < window_ended_at
        )
        return tuple(
            sorted(
                selected,
                key=lambda event: (
                    event.recorded_at,
                    event.stream_id,
                    event.sequence_no,
                    event.event_id,
                    event.event_version,
                ),
            )[:limit]
        )

    def append(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEvent:
        """Append one event or return its exact first-winner replay."""

        if _UOW.get() is None:
            raise SystemAuditConflict("system audit append requires repository.atomic()")
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise SystemAuditCorruption("system audit recorded_at is naive")
        if recorded_at > self.now():
            raise SystemAuditUnavailable("future system audit recorded_at is forbidden")
        if event.recorded_at != recorded_at:
            raise SystemAuditConflict("event recorded_at must equal repository clock")
        if event.scope is None:
            raise SystemAuditConflict("system audit append requires an explicit scope")
        try:
            event.validate_hashes()
        except (TypeError, ValueError) as error:
            raise SystemAuditCorruption("event candidate hash is invalid") from error

        state = self._state(lock=True)
        existing = tuple(
            item.event
            for item in state
            if item.event.event_id == event.event_id
            and item.event.event_version == event.event_version
        )
        if len(existing) > 1:
            raise SystemAuditCorruption("system audit first-winner identity is ambiguous")
        if existing:
            if existing[0] != event:
                raise SystemAuditConflict("system audit identity already has another winner")
            return existing[0]

        same_content = tuple(
            item.event for item in state if item.event.content_hash == event.content_hash
        )
        if same_content:
            raise SystemAuditConflict("system audit content hash is already bound to another event")

        stream = tuple(item.event for item in state if item.event.stream_id == event.stream_id)
        head = max(stream, key=lambda value: value.sequence_no) if stream else None
        expected = head.content_hash if head is not None else None
        if expected != expected_predecessor_hash:
            raise SystemAuditConflict("system audit predecessor CAS failed")
        expected_sequence = head.sequence_no + 1 if head is not None else 1
        if event.sequence_no != expected_sequence:
            raise SystemAuditConflict("system audit sequence is not adjacent to the head")
        if head is not None and event.recorded_at < head.recorded_at:
            raise SystemAuditConflict("system audit recorded clock moved backwards")

        values = _model_values(event)
        row = SystemAuditEventModel(**values)
        try:
            with transaction.atomic(using=self._using):
                with _claim_system_audit_insert(event.event_id, event.content_hash):
                    row.save(force_insert=True, using=self._using)
        except IntegrityError:
            winner = self.get_winner(
                event_id=event.event_id,
                event_version=event.event_version,
                as_of=recorded_at,
            )
            if winner is not None and winner == event:
                return winner
            raise SystemAuditConflict("system audit append lost its first-winner race") from None
        return self._restore(row)

    def append_targeted(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
        scope: AuditScopeRef | None = None,
        identity_winner: SystemAuditEvent | None = None,
        stream_head: SystemAuditEvent | None = None,
    ) -> SystemAuditEvent:
        """Append after the caller's serialized exact identity/head reads."""

        winner = self._validate_targeted_append(
            event,
            expected_predecessor_hash=expected_predecessor_hash,
            recorded_at=recorded_at,
            scope=scope,
            identity_winner=identity_winner,
            stream_head=stream_head,
        )
        if winner is not None:
            return winner
        values = _model_values(event)
        row = SystemAuditEventModel(**values)
        try:
            with _claim_system_audit_insert(event.event_id, event.content_hash):
                row.save(force_insert=True, using=self._using)
        except IntegrityError as error:
            raise SystemAuditConflict(
                "system audit serialized append collided with another identity"
            ) from error
        return self._restore(row)

    def append_group_targeted(
        self,
        events: tuple[SystemAuditEvent, ...],
        *,
        identity_winners: Mapping[tuple[str, str], SystemAuditEvent],
        stream_heads: Mapping[str, SystemAuditEvent],
    ) -> tuple[SystemAuditEvent, ...]:
        """Append one fully validated stream group with one guarded insert."""

        if not events or len({event.stream_id for event in events}) != len(events):
            raise SystemAuditConflict("system audit append group streams are invalid")
        resolved: list[SystemAuditEvent | None] = []
        new_rows: list[SystemAuditEventModel] = []
        new_events: list[SystemAuditEvent] = []
        for event in events:
            winner = self._validate_targeted_append(
                event,
                expected_predecessor_hash=event.predecessor_hash,
                recorded_at=event.recorded_at,
                scope=event.scope,
                identity_winner=identity_winners.get((event.event_id, event.event_version)),
                stream_head=stream_heads.get(event.stream_id),
            )
            resolved.append(winner)
            if winner is None:
                new_events.append(event)
                new_rows.append(SystemAuditEventModel(**_model_values(event)))
        if new_rows:
            identities = tuple((event.event_id, event.content_hash) for event in new_events)
            try:
                with _claim_system_audit_batch_insert(identities):
                    SystemAuditEventModel._default_manager.db_manager(
                        self._using
                    )._bulk_create_claimed(tuple(new_rows))
            except IntegrityError as error:
                raise SystemAuditConflict(
                    "system audit serialized group append collided with another identity"
                ) from error
        restored_new = iter(self._restore(row) for row in new_rows)
        return tuple(item if item is not None else next(restored_new) for item in resolved)

    def _validate_targeted_append(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
        scope: AuditScopeRef | None,
        identity_winner: SystemAuditEvent | None,
        stream_head: SystemAuditEvent | None,
    ) -> SystemAuditEvent | None:
        """Validate one exact append against its already locked identity and head."""

        if _UOW.get() is None:
            raise SystemAuditConflict("system audit append requires repository.atomic()")
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise SystemAuditCorruption("system audit recorded_at is naive")
        if recorded_at > self.now():
            raise SystemAuditUnavailable("future system audit recorded_at is forbidden")
        if event.recorded_at != recorded_at or event.scope is None:
            raise SystemAuditConflict("targeted audit append clock or scope is invalid")
        if scope is not None and event.scope != scope:
            raise SystemAuditConflict("targeted audit append scope differs")
        try:
            event.validate_hashes()
        except (TypeError, ValueError) as error:
            raise SystemAuditCorruption("event candidate hash is invalid") from error
        if identity_winner is not None:
            if identity_winner != event:
                raise SystemAuditConflict("system audit identity already has another winner")
            return identity_winner
        head = stream_head
        if head is not None and (head.stream_id != event.stream_id or head.scope != event.scope):
            raise SystemAuditConflict("system audit serialized stream head differs")
        expected = head.content_hash if head is not None else None
        if expected != expected_predecessor_hash:
            raise SystemAuditConflict("system audit predecessor CAS failed")
        expected_sequence = head.sequence_no + 1 if head is not None else 1
        if event.sequence_no != expected_sequence:
            raise SystemAuditConflict("system audit sequence is not adjacent to the head")
        if head is not None and event.recorded_at < head.recorded_at:
            raise SystemAuditConflict("system audit recorded clock moved backwards")
        return None

    def _require_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise SystemAuditUnavailable("system audit as_of is naive")
        if as_of > self.now():
            raise SystemAuditUnavailable("future system audit as_of is forbidden")

    def _state(self, *, lock: bool = False) -> tuple[_StateRow, ...]:
        manager = SystemAuditEventModel._default_manager.using(self._using)
        rows = manager.select_for_update() if lock else manager
        restored = tuple(_StateRow(self._restore(row), row) for row in rows.all())
        _validate_closed_world(restored)
        return restored

    def _restore(self, row: SystemAuditEventModel) -> SystemAuditEvent:
        try:
            payload = cast(Mapping[str, JSONValue], row.canonical_payload)
            event = decode(payload)
        except (TypeError, ValueError) as error:
            raise SystemAuditCorruption(
                "system audit canonical payload cannot be restored"
            ) from error
        if encode(event) != row.canonical_payload:
            raise SystemAuditCorruption("system audit canonical payload is not exact")
        if _model_values(event) != _model_values_from_row(row):
            raise SystemAuditCorruption("system audit scalar headers do not match payload")
        if row.persisted_at != event.recorded_at:
            raise SystemAuditCorruption("system audit persisted clock is invalid")
        return event

    def _scope_visible(
        self,
        events: tuple[SystemAuditEvent, ...],
        *,
        scope: AuditScopeRef | None,
    ) -> tuple[SystemAuditEvent, ...]:
        """Apply an explicit scope without treating event ``owner`` as scope."""

        if scope is None:
            return events
        visible: list[SystemAuditEvent] = []
        for event in events:
            if event.scope is None:
                raise SystemAuditUnavailable("scoped audit read encountered a missing scope")
            if event.scope == scope:
                visible.append(event)
        return tuple(visible)


def _model_values(event: SystemAuditEvent) -> dict[str, object]:
    """Project one Domain event into every persisted scalar/JSON column."""

    resource = event.resource.to_payload() if event.resource is not None else None
    return {
        "event_id": event.event_id,
        "event_version": event.event_version,
        "schema_version": event.schema_version,
        "category": event.category.value,
        "event_type": event.event_type,
        "owner": event.owner,
        "scope_tenant_id": event.scope.tenant_id if event.scope is not None else None,
        "scope_owner_id": event.scope.owner_id if event.scope is not None else None,
        "write_policy": event.write_policy.value,
        "outcome": event.outcome.value,
        "severity": event.severity.value,
        "reason_codes": list(event.reason_codes),
        "occurred_at": event.occurred_at,
        "recorded_at": event.recorded_at,
        "observed_at": event.observed_at,
        "actor_type": event.actor.actor_type,
        "actor_id": event.actor.actor_id,
        "actor_display": event.actor.actor_display,
        "source_app": event.source_app,
        "source_component": event.source_component,
        "source_surface": event.source_surface,
        "correlations": dict(event.correlations.to_payload()),
        "resource_type": resource["resource_type"] if resource is not None else None,
        "resource_id": resource["resource_id"] if resource is not None else None,
        "resource_version": resource["resource_version"] if resource is not None else None,
        "dataset_key": event.dataset_key,
        "provider_key": event.provider_key,
        "capability": event.capability,
        "publication_id": event.publication_id,
        "evidence_refs": [dict(ref.to_payload()) for ref in event.evidence_refs],
        "detail_schema": event.detail_schema,
        "detail": dict(event.detail),
        "canonical_payload": dict(encode(event)),
        "stream_id": event.stream_id,
        "sequence_no": event.sequence_no,
        "predecessor_hash": event.predecessor_hash,
        "idempotency_key": event.idempotency_key,
        "identity_hash": event.identity_hash,
        "content_hash": event.content_hash,
        "persisted_at": event.recorded_at,
    }


def _model_values_from_row(row: SystemAuditEventModel) -> dict[str, object]:
    """Project a row without trusting its canonical JSON payload."""

    return {key: getattr(row, key) for key in _model_values_keys() if key != "persisted_at"} | {
        "persisted_at": row.persisted_at
    }


def _model_values_keys() -> tuple[str, ...]:
    """Return the stable projection columns compared during restore."""

    return (
        "event_id",
        "event_version",
        "schema_version",
        "category",
        "event_type",
        "owner",
        "scope_tenant_id",
        "scope_owner_id",
        "write_policy",
        "outcome",
        "severity",
        "reason_codes",
        "occurred_at",
        "recorded_at",
        "observed_at",
        "actor_type",
        "actor_id",
        "actor_display",
        "source_app",
        "source_component",
        "source_surface",
        "correlations",
        "resource_type",
        "resource_id",
        "resource_version",
        "dataset_key",
        "provider_key",
        "capability",
        "publication_id",
        "evidence_refs",
        "detail_schema",
        "detail",
        "canonical_payload",
        "stream_id",
        "sequence_no",
        "predecessor_hash",
        "idempotency_key",
        "identity_hash",
        "content_hash",
        "persisted_at",
    )


def _validate_closed_world(state: tuple[_StateRow, ...]) -> None:
    """Validate every stream as one contiguous, predecessor-bound graph."""

    streams: dict[str, list[SystemAuditEvent]] = {}
    for item in state:
        streams.setdefault(item.event.stream_id, []).append(item.event)
    for stream_id, values in streams.items():
        ordered = sorted(values, key=lambda value: value.sequence_no)
        for expected_sequence, event in enumerate(ordered, start=1):
            if event.sequence_no != expected_sequence:
                raise SystemAuditCorruption(
                    f"system audit stream {stream_id} has a sequence gap or fork"
                )
            if expected_sequence == 1:
                if event.predecessor_hash is not None:
                    raise SystemAuditCorruption("system audit root has a predecessor")
                continue
            previous = ordered[expected_sequence - 2]
            if event.predecessor_hash != previous.content_hash:
                raise SystemAuditCorruption("system audit predecessor hash is disconnected")
            if event.recorded_at < previous.recorded_at:
                raise SystemAuditCorruption("system audit recorded clock moved backwards")


__all__ = [
    "DjangoSystemAuditClock",
    "DjangoSystemAuditEventRepository",
    "PersistedSystemAuditEvent",
    "SystemAuditClock",
    "SystemAuditConflict",
    "SystemAuditCorruption",
    "SystemAuditUnavailable",
]
