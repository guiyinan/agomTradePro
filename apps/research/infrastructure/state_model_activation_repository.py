"""Strict append-only persistence and exact PIT reads for R6 activation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.application.state_model_activation import (
    R6ActivationClock,
    R6ActivationConflict,
    R6ActivationCorruption,
    R6ActivationUnavailable,
    R6PersistedActivationEvent,
)
from apps.research.application.state_model_activation_persistence import (
    R6ActivationAuditEntry,
    R6ActivationAuditPage,
    R6ActivationEventRef,
)
from apps.research.domain.state_model_activation import (
    R6ActivationAction,
    R6ActivationApprovalRef,
    R6ActivationAuthorization,
    R6ActivationAuthorizationRef,
    R6ActivationEvent,
    R6ActivationScopeRef,
    create_r6_activation_event,
    derive_r6_activation_state,
)
from apps.research.infrastructure.state_model_activation_audit_codec import (
    _audit_snapshot_values,
    _AuditCursor,
    _AuditSnapshot,
    _create_audit_snapshot,
    _decode_cursor,
    _encode_cursor,
    _restore_audit_snapshot,
)
from apps.research.infrastructure.state_model_activation_codec import (
    R6ActivationCodecError,
    decode_r6_activation_authorization,
    decode_r6_activation_event,
    encode_r6_activation_authorization,
    encode_r6_activation_event,
)
from apps.research.infrastructure.state_model_activation_models import (
    R6ActivationAuditSnapshotModel,
    R6ActivationAuthorizationModel,
    R6ActivationEventModel,
    R6ActivationStreamCommitModel,
    _activate_r6_activation_uow,
    _claim_r6_activation_insert,
    _require_active_r6_activation_uow,
)
from apps.research.infrastructure.state_model_activation_row_seal import (
    authorization_values as _authorization_values,
)
from apps.research.infrastructure.state_model_activation_row_seal import (
    event_values as _event_values,
)
from apps.research.infrastructure.state_model_activation_row_seal import (
    require_exact_values as _require_exact_values,
)
from apps.research.infrastructure.state_model_activation_row_seal import (
    stream_commit_values as _stream_commit_values,
)


class DjangoR6ActivationClock:
    """Django timezone-backed authoritative server clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware timestamp."""

        return timezone.now()


def _aware_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise R6ActivationCorruption(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


class DjangoR6ActivationRepository:
    """Public read-only stream, exact PIT, and audit repository."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R6ActivationClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoR6ActivationClock()

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Enter a read-only transaction without activating write capability."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using):
            yield

    def server_now(self) -> datetime:
        """Return a validated authoritative server timestamp."""

        try:
            return _aware_utc(self._clock.now(), "R6 activation server clock")
        except R6ActivationCorruption:
            raise
        except Exception as error:
            raise R6ActivationUnavailable("R6 activation server clock is unavailable") from error

    def load_stream(
        self,
        *,
        scope_ref: R6ActivationScopeRef,
        as_of: datetime,
    ) -> tuple[R6ActivationEvent, ...]:
        """Return the complete exact known prefix in canonical sequence order."""

        _require_active_r6_activation_uow()
        self._require_pit_cutoff(as_of)
        return self._restore_stream(scope_ref=scope_ref, as_of=as_of)

    def get_by_authorization(
        self,
        *,
        authorization_ref: R6ActivationAuthorizationRef,
    ) -> R6PersistedActivationEvent | None:
        """Return and replay the unique immutable winner for an authorization."""

        _require_active_r6_activation_uow()
        commits = tuple(
            R6ActivationStreamCommitModel._default_manager.using(self._using).filter(
                authorization_id=authorization_ref.authorization_id,
                authorization_version=authorization_ref.authorization_version,
            )
        )
        commit_event_ids = tuple(model.event_row_id for model in commits)
        commit_authorization_ids = tuple(model.authorization_row_id for model in commits)
        event_models = tuple(
            R6ActivationEventModel._default_manager.using(self._using).filter(
                Q(
                    authorization_id=authorization_ref.authorization_id,
                    authorization_version=authorization_ref.authorization_version,
                )
                | Q(pk__in=commit_event_ids)
            )
        )
        event_authorization_ids = tuple(model.authorization_row_id for model in event_models)
        authorization_models = tuple(
            R6ActivationAuthorizationModel._default_manager.using(self._using).filter(
                Q(
                    authorization_id=authorization_ref.authorization_id,
                    authorization_version=authorization_ref.authorization_version,
                )
                | Q(pk__in=commit_authorization_ids + event_authorization_ids)
            )
        )
        if not commits and not event_models and not authorization_models:
            return None
        self._require_commit_sets(
            event_models=event_models,
            authorization_models=authorization_models,
            commit_models=commits,
        )
        if len(commits) != 1:
            raise R6ActivationCorruption("multiple activation events use one authorization")
        candidate, _ = self._restore_commit(commits[0])
        history = self._restore_stream(
            scope_ref=candidate.scope_ref,
            as_of=commits[0].ledger_recorded_at,
        )
        if not history or history[-1] != candidate:
            raise R6ActivationCorruption("activation winner is not its exact PIT stream head")
        return R6PersistedActivationEvent(candidate, commits[0].ledger_recorded_at)

    def get_exact(
        self,
        *,
        authorization_ref: R6ActivationAuthorizationRef,
        scope_ref: R6ActivationScopeRef,
        action: R6ActivationAction,
        subject: R6ActivationApprovalRef,
        rollback_target: R6ActivationApprovalRef | None,
        as_of: datetime,
    ) -> R6ActivationAuthorization | None:
        """Restore a persisted owner authorization by command identity."""

        _require_active_r6_activation_uow()
        self._require_pit_cutoff(as_of)
        commits = tuple(
            R6ActivationStreamCommitModel._default_manager.using(self._using).filter(
                authorization_id=authorization_ref.authorization_id,
                authorization_version=authorization_ref.authorization_version,
                ledger_recorded_at__lte=as_of,
            )
        )
        commit_event_ids = tuple(model.event_row_id for model in commits)
        commit_authorization_ids = tuple(model.authorization_row_id for model in commits)
        event_models = tuple(
            R6ActivationEventModel._default_manager.using(self._using).filter(
                Q(
                    authorization_id=authorization_ref.authorization_id,
                    authorization_version=authorization_ref.authorization_version,
                )
                | Q(pk__in=commit_event_ids),
                ledger_recorded_at__lte=as_of,
            )
        )
        event_authorization_ids = tuple(model.authorization_row_id for model in event_models)
        authorization_models = tuple(
            R6ActivationAuthorizationModel._default_manager.using(self._using).filter(
                Q(
                    authorization_id=authorization_ref.authorization_id,
                    authorization_version=authorization_ref.authorization_version,
                )
                | Q(pk__in=commit_authorization_ids + event_authorization_ids),
                ledger_recorded_at__lte=as_of,
            )
        )
        if not commits and not event_models and not authorization_models:
            return None
        self._require_commit_sets(
            event_models=event_models,
            authorization_models=authorization_models,
            commit_models=commits,
        )
        if len(commits) != 1:
            raise R6ActivationCorruption("multiple rows match one owner authorization")
        _event, authorization = self._restore_commit(commits[0])
        if (
            authorization.scope_ref != scope_ref
            or authorization.action is not action
            or authorization.subject != subject
            or authorization.rollback_target != rollback_target
        ):
            raise R6ActivationConflict("persisted activation authorization was substituted")
        return authorization

    def get_exact_authorization(
        self,
        *,
        authorization_ref: R6ActivationAuthorizationRef,
        expected_hash: str,
        as_of: datetime,
    ) -> R6ActivationAuthorization | None:
        """Return one ID/version/hash exact authorization known at ``as_of``."""

        self._require_pit_cutoff(as_of)
        with self.atomic():
            commit_models = tuple(
                R6ActivationStreamCommitModel._default_manager.using(self._using).filter(
                    Q(
                        authorization_id=authorization_ref.authorization_id,
                        authorization_version=authorization_ref.authorization_version,
                    )
                    | Q(authorization_hash=expected_hash),
                    ledger_recorded_at__lte=as_of,
                )
            )
            commit_event_ids = tuple(model.event_row_id for model in commit_models)
            commit_authorization_ids = tuple(model.authorization_row_id for model in commit_models)
            event_models = tuple(
                R6ActivationEventModel._default_manager.using(self._using).filter(
                    Q(
                        authorization_id=authorization_ref.authorization_id,
                        authorization_version=authorization_ref.authorization_version,
                    )
                    | Q(authorization_hash=expected_hash)
                    | Q(pk__in=commit_event_ids),
                    ledger_recorded_at__lte=as_of,
                )
            )
            event_authorization_ids = tuple(model.authorization_row_id for model in event_models)
            authorization_models = tuple(
                R6ActivationAuthorizationModel._default_manager.using(self._using).filter(
                    Q(
                        authorization_id=authorization_ref.authorization_id,
                        authorization_version=authorization_ref.authorization_version,
                    )
                    | Q(content_hash=expected_hash)
                    | Q(pk__in=commit_authorization_ids + event_authorization_ids),
                    ledger_recorded_at__lte=as_of,
                )
            )
            if not commit_models and not event_models and not authorization_models:
                return None
            self._require_commit_sets(
                event_models=event_models,
                authorization_models=authorization_models,
                commit_models=commit_models,
            )
            matches = tuple(
                item
                for model in commit_models
                for _event, item in (self._restore_commit(model),)
                if item.ref == authorization_ref and item.content_hash == expected_hash
            )
            if len(matches) > 1:
                raise R6ActivationCorruption("multiple rows match one exact authorization")
            return None if not matches else matches[0]

    def get_exact_event(
        self,
        *,
        event_ref: R6ActivationEventRef,
        as_of: datetime,
    ) -> R6ActivationEvent | None:
        """Return one ID/version/hash exact event known at ``as_of``."""

        self._require_pit_cutoff(as_of)
        with self.atomic():
            commit_models = tuple(
                R6ActivationStreamCommitModel._default_manager.using(self._using).filter(
                    Q(event_id=event_ref.event_id, event_version=event_ref.event_version)
                    | Q(event_hash=event_ref.event_hash),
                    ledger_recorded_at__lte=as_of,
                )
            )
            commit_event_ids = tuple(model.event_row_id for model in commit_models)
            commit_authorization_ids = tuple(model.authorization_row_id for model in commit_models)
            event_models = tuple(
                R6ActivationEventModel._default_manager.using(self._using).filter(
                    Q(event_id=event_ref.event_id, event_version=event_ref.event_version)
                    | Q(content_hash=event_ref.event_hash)
                    | Q(pk__in=commit_event_ids),
                    ledger_recorded_at__lte=as_of,
                )
            )
            event_authorization_ids = tuple(model.authorization_row_id for model in event_models)
            authorization_models = tuple(
                R6ActivationAuthorizationModel._default_manager.using(self._using).filter(
                    Q(event_id=event_ref.event_id, event_version=event_ref.event_version)
                    | Q(pk__in=commit_authorization_ids + event_authorization_ids),
                    ledger_recorded_at__lte=as_of,
                )
            )
            if not commit_models and not event_models and not authorization_models:
                return None
            self._require_commit_sets(
                event_models=event_models,
                authorization_models=authorization_models,
                commit_models=commit_models,
            )
            matches = tuple(
                event
                for model in commit_models
                for event, _authorization in (self._restore_commit(model),)
                if (
                    event.event_id == event_ref.event_id
                    and event.event_version == event_ref.event_version
                    and event.content_hash == event_ref.event_hash
                )
            )
            if len(matches) > 1:
                raise R6ActivationCorruption("multiple rows match one exact event")
            if not matches:
                return None
            event = matches[0]
            history = self._restore_stream(scope_ref=event.scope_ref, as_of=as_of)
            if event not in history:
                raise R6ActivationCorruption("exact activation event is outside its stream")
            return event

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R6ActivationAuditPage:
        """Materialize or replay one immutable signed PIT audit manifest."""

        if type(limit) is not int or limit < 1 or limit > 200:
            raise ValueError("R6 activation audit limit must be between 1 and 200")
        self._require_pit_cutoff(as_of)
        cursor_value = _decode_cursor(cursor)
        with self.atomic():
            if cursor_value is None:
                entries = self._materialize_audit_entries(as_of=as_of)
                if len(entries) <= limit:
                    return R6ActivationAuditPage(entries, None, as_of)
                snapshot = _create_audit_snapshot(
                    as_of=as_of,
                    created_at=self.server_now(),
                    entries=entries,
                )
                self._append_audit_snapshot(snapshot)
                return R6ActivationAuditPage(
                    snapshot.entries[:limit],
                    _encode_cursor(snapshot=snapshot, next_offset=limit),
                    as_of,
                )
            if cursor_value.snapshot_as_of != as_of.astimezone(UTC):
                raise R6ActivationUnavailable(
                    "R6 activation audit cursor belongs to another cutoff"
                )
            snapshot = self._get_audit_snapshot(cursor_value)
            if snapshot.as_of != as_of.astimezone(UTC):
                raise R6ActivationCorruption("activation audit snapshot cutoff differs")
            start = cursor_value.next_offset
            if start >= len(snapshot.entries):
                raise R6ActivationCorruption("activation audit cursor exceeds its snapshot")
            entries = snapshot.entries[start : start + limit]
            self._validate_snapshot_entries(snapshot=snapshot, entries=entries)
            next_offset = start + len(entries)
            next_cursor = None
            if next_offset < len(snapshot.entries):
                next_cursor = _encode_cursor(
                    snapshot=snapshot,
                    next_offset=next_offset,
                )
            return R6ActivationAuditPage(entries, next_cursor, snapshot.as_of)

    def _materialize_audit_entries(
        self,
        *,
        as_of: datetime,
    ) -> tuple[R6ActivationAuditEntry, ...]:
        event_models = tuple(
            R6ActivationEventModel._default_manager.using(self._using).filter(
                ledger_recorded_at__lte=as_of
            )
        )
        authorization_models = tuple(
            R6ActivationAuthorizationModel._default_manager.using(self._using).filter(
                ledger_recorded_at__lte=as_of
            )
        )
        commit_models = tuple(
            R6ActivationStreamCommitModel._default_manager.using(self._using)
            .filter(ledger_recorded_at__lte=as_of)
            .order_by(
                "ledger_recorded_at",
                "event_id",
                "event_version",
                "event_hash",
            )
        )
        self._require_commit_sets(
            event_models=event_models,
            authorization_models=authorization_models,
            commit_models=commit_models,
        )
        restored = tuple(self._restore_commit(model) for model in commit_models)
        events_by_pk = {model.pk: model for model in event_models}
        streams: dict[R6ActivationScopeRef, tuple[R6ActivationEvent, ...]] = {}
        for event, _authorization in restored:
            if event.scope_ref not in streams:
                streams[event.scope_ref] = self._restore_stream(
                    scope_ref=event.scope_ref,
                    as_of=as_of,
                )
            if event not in streams[event.scope_ref]:
                raise R6ActivationCorruption("audit event is outside its canonical stream")
        return tuple(
            self._audit_entry(event=event, model=events_by_pk[model.event_row_id])
            for model, (event, _authorization) in zip(commit_models, restored, strict=True)
        )

    @staticmethod
    def _audit_entry(
        *,
        event: R6ActivationEvent,
        model: R6ActivationEventModel,
    ) -> R6ActivationAuditEntry:
        return R6ActivationAuditEntry(
            event_ref=R6ActivationEventRef(
                event.event_id,
                event.event_version,
                event.content_hash,
            ),
            authorization_ref=R6ActivationAuthorizationRef(
                event.authorization_id,
                event.authorization_version,
            ),
            authorization_hash=event.authorization_hash,
            scope_ref=event.scope_ref,
            action=event.action,
            subject=event.subject,
            rollback_target=event.rollback_target,
            sequence=event.sequence,
            occurred_at=event.occurred_at,
            ledger_recorded_at=model.ledger_recorded_at,
        )

    def _append_audit_snapshot(self, snapshot: _AuditSnapshot) -> None:
        raise R6ActivationUnavailable(
            "R6 activation audit snapshot writer is unavailable on the read repository"
        )

    def _get_audit_snapshot(self, cursor: _AuditCursor) -> _AuditSnapshot:
        models = tuple(
            R6ActivationAuditSnapshotModel._default_manager.using(self._using).filter(
                Q(
                    snapshot_id=cursor.snapshot_id,
                    snapshot_version=cursor.snapshot_version,
                )
                | Q(content_hash=cursor.snapshot_hash)
            )
        )
        matches = tuple(
            model
            for model in models
            if (
                model.snapshot_id,
                model.snapshot_version,
                model.content_hash,
            )
            == (
                cursor.snapshot_id,
                cursor.snapshot_version,
                cursor.snapshot_hash,
            )
        )
        if len(models) != 1 or len(matches) != 1:
            raise R6ActivationCorruption("activation audit snapshot is unavailable or substituted")
        return _restore_audit_snapshot(matches[0])

    def _validate_snapshot_entries(
        self,
        *,
        snapshot: _AuditSnapshot,
        entries: tuple[R6ActivationAuditEntry, ...],
    ) -> None:
        streams: dict[R6ActivationScopeRef, tuple[R6ActivationEvent, ...]] = {}
        for entry in entries:
            models = tuple(
                R6ActivationEventModel._default_manager.using(self._using).filter(
                    event_id=entry.event_ref.event_id,
                    event_version=entry.event_ref.event_version,
                    content_hash=entry.event_ref.event_hash,
                    ledger_recorded_at__lte=snapshot.as_of,
                )
            )
            if len(models) != 1:
                raise R6ActivationCorruption("snapshot event is unavailable or substituted")
            event, _authorization = self._restore_pair(models[0])
            if self._audit_entry(event=event, model=models[0]) != entry:
                raise R6ActivationCorruption("snapshot entry differs from its ledger row")
            if entry.scope_ref not in streams:
                streams[entry.scope_ref] = self._restore_stream(
                    scope_ref=entry.scope_ref,
                    as_of=snapshot.as_of,
                )
            if event not in streams[entry.scope_ref]:
                raise R6ActivationCorruption("snapshot event is outside its canonical stream")

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise R6ActivationUnavailable("R6 activation as_of must be timezone-aware")
        if as_of.astimezone(UTC) > self.server_now():
            raise R6ActivationUnavailable("future R6 activation as_of is not permitted")

    def _restore_stream(
        self,
        *,
        scope_ref: R6ActivationScopeRef,
        as_of: datetime,
    ) -> tuple[R6ActivationEvent, ...]:
        scope_ref.__post_init__()
        event_candidates = tuple(
            R6ActivationEventModel._default_manager.using(self._using)
            .filter(
                Q(
                    scope_id=scope_ref.scope_id,
                    scope_version=scope_ref.scope_version,
                )
                | Q(scope_hash=scope_ref.scope_hash),
                ledger_recorded_at__lte=as_of,
            )
            .order_by("sequence", "id")
        )
        authorization_candidates = tuple(
            R6ActivationAuthorizationModel._default_manager.using(self._using)
            .filter(
                Q(
                    scope_id=scope_ref.scope_id,
                    scope_version=scope_ref.scope_version,
                )
                | Q(scope_hash=scope_ref.scope_hash),
                ledger_recorded_at__lte=as_of,
            )
            .order_by("expected_sequence", "id")
        )
        commit_candidates = tuple(
            R6ActivationStreamCommitModel._default_manager.using(self._using)
            .filter(
                Q(
                    scope_id=scope_ref.scope_id,
                    scope_version=scope_ref.scope_version,
                )
                | Q(scope_hash=scope_ref.scope_hash),
                ledger_recorded_at__lte=as_of,
            )
            .order_by("sequence", "id")
        )
        self._require_commit_sets(
            event_models=event_candidates,
            authorization_models=authorization_candidates,
            commit_models=commit_candidates,
        )
        restored: list[R6ActivationEvent] = []
        for model in commit_candidates:
            event, authorization = self._restore_commit(model)
            if event.scope_ref != scope_ref:
                raise R6ActivationCorruption("activation scope identity/hash alias detected")
            try:
                replayed = create_r6_activation_event(
                    authorization=authorization,
                    previous_events=tuple(restored),
                    applied_at=event.occurred_at,
                )
            except Exception as error:
                raise R6ActivationCorruption(
                    "activation event cannot replay from its authorization"
                ) from error
            if replayed != event:
                raise R6ActivationCorruption("activation authorization/event pair differs")
            restored.append(event)
        events = tuple(restored)
        if events:
            try:
                derive_r6_activation_state(events, evaluated_at=as_of)
            except Exception as error:
                raise R6ActivationCorruption("activation stream is not canonical") from error
        return events

    @staticmethod
    def _require_commit_sets(
        *,
        event_models: tuple[R6ActivationEventModel, ...],
        authorization_models: tuple[R6ActivationAuthorizationModel, ...],
        commit_models: tuple[R6ActivationStreamCommitModel, ...],
    ) -> None:
        event_ids = {model.pk for model in event_models}
        authorization_ids = {model.pk for model in authorization_models}
        event_authorization_ids = {model.authorization_row_id for model in event_models}
        commit_event_ids = {model.event_row_id for model in commit_models}
        commit_authorization_ids = {model.authorization_row_id for model in commit_models}
        if (
            len(event_ids) != len(event_models)
            or len(authorization_ids) != len(authorization_models)
            or len(commit_event_ids) != len(commit_models)
            or len(commit_authorization_ids) != len(commit_models)
            or event_ids != commit_event_ids
            or authorization_ids != commit_authorization_ids
            or event_authorization_ids != authorization_ids
        ):
            raise R6ActivationCorruption(
                "activation stream commit/authorization/event ledger is truncated or orphaned"
            )

    def _restore_authorization(
        self,
        model: R6ActivationAuthorizationModel,
    ) -> R6ActivationAuthorization:
        try:
            authorization = decode_r6_activation_authorization(model.canonical_payload)
        except R6ActivationCodecError as error:
            raise R6ActivationCorruption("activation authorization payload is invalid") from error
        _aware_utc(model.ledger_recorded_at, "activation authorization ledger_recorded_at")
        _require_exact_values(
            model=model,
            values=_authorization_values(
                authorization,
                ledger_recorded_at=model.ledger_recorded_at,
            ),
            label="authorization",
        )
        return authorization

    def _restore_authorization_pair(
        self,
        model: R6ActivationAuthorizationModel,
    ) -> tuple[R6ActivationEvent, R6ActivationAuthorization]:
        commit_models = tuple(
            R6ActivationStreamCommitModel._default_manager.using(self._using).filter(
                authorization_row_id=model.pk
            )
        )
        if len(commit_models) != 1:
            raise R6ActivationCorruption(
                "activation authorization is orphaned or has multiple stream commits"
            )
        event, authorization = self._restore_commit(commit_models[0])
        if commit_models[0].authorization_row_id != model.pk:
            raise R6ActivationCorruption("activation authorization/stream commit FK differs")
        return event, authorization

    def _restore_pair(
        self,
        model: R6ActivationEventModel,
    ) -> tuple[R6ActivationEvent, R6ActivationAuthorization]:
        commit_models = tuple(
            R6ActivationStreamCommitModel._default_manager.using(self._using).filter(
                event_row_id=model.pk
            )
        )
        if len(commit_models) != 1:
            raise R6ActivationCorruption(
                "activation event is orphaned or has multiple stream commits"
            )
        event, authorization = self._restore_commit(commit_models[0])
        if commit_models[0].event_row_id != model.pk:
            raise R6ActivationCorruption("activation event/stream commit FK differs")
        return event, authorization

    def _restore_commit(
        self,
        model: R6ActivationStreamCommitModel,
    ) -> tuple[R6ActivationEvent, R6ActivationAuthorization]:
        authorization_models = tuple(
            R6ActivationAuthorizationModel._default_manager.using(self._using).filter(
                pk=model.authorization_row_id
            )
        )
        event_models = tuple(
            R6ActivationEventModel._default_manager.using(self._using).filter(pk=model.event_row_id)
        )
        if len(authorization_models) != 1 or len(event_models) != 1:
            raise R6ActivationCorruption(
                "activation stream commit is orphaned from authorization/event evidence"
            )
        event, authorization = self._restore_uncommitted_pair(
            event_model=event_models[0],
            authorization_model=authorization_models[0],
        )
        _aware_utc(model.ledger_recorded_at, "activation stream commit ledger_recorded_at")
        _require_exact_values(
            model=model,
            values=_stream_commit_values(
                authorization=authorization,
                event=event,
                authorization_row_id=authorization_models[0].pk,
                event_row_id=event_models[0].pk,
                ledger_recorded_at=model.ledger_recorded_at,
            ),
            label="stream commit",
        )
        if (
            model.ledger_recorded_at != authorization_models[0].ledger_recorded_at
            or model.ledger_recorded_at != event_models[0].ledger_recorded_at
        ):
            raise R6ActivationCorruption("activation stream commit ledger clock differs")
        return event, authorization

    def _restore_uncommitted_pair(
        self,
        *,
        event_model: R6ActivationEventModel,
        authorization_model: R6ActivationAuthorizationModel,
    ) -> tuple[R6ActivationEvent, R6ActivationAuthorization]:
        try:
            event = decode_r6_activation_event(event_model.canonical_payload)
        except R6ActivationCodecError as error:
            raise R6ActivationCorruption("activation event payload is invalid") from error
        authorization = self._restore_authorization(authorization_model)
        _aware_utc(event_model.ledger_recorded_at, "activation event ledger_recorded_at")
        _require_exact_values(
            model=event_model,
            values=_event_values(
                event,
                authorization_row_id=event_model.authorization_row_id,
                ledger_recorded_at=event_model.ledger_recorded_at,
            ),
            label="event",
        )
        if (
            event_model.authorization_row_id != authorization_model.pk
            or event_model.ledger_recorded_at != authorization_model.ledger_recorded_at
            or event.authorization_id != authorization.authorization_id
            or event.authorization_version != authorization.authorization_version
            or event.authorization_hash != authorization.content_hash
            or event.event_id != authorization.event_id
            or event.event_version != authorization.event_version
            or event.scope_ref != authorization.scope_ref
            or event.action is not authorization.action
            or event.subject != authorization.subject
            or event.rollback_target != authorization.rollback_target
            or event.sequence != authorization.expected_sequence
            or event.previous_event_hash != authorization.expected_previous_event_hash
            or event.reason_codes != authorization.reason_codes
        ):
            raise R6ActivationCorruption("activation event FK authorization differs")
        return event, authorization


class _DjangoR6ActivationStore(DjangoR6ActivationRepository):
    """Private append capability retained only by the composition root."""

    __slots__ = ("_token",)

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R6ActivationClock | None = None,
    ) -> None:
        super().__init__(using=using, clock=clock)
        self._token = object()

    def atomic(self) -> AbstractContextManager[None]:
        """Enter the private activation write capability scope."""

        return self._write_atomic()

    @contextmanager
    def _write_atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using), _activate_r6_activation_uow(self._token):
            yield

    def _append_audit_snapshot(self, snapshot: _AuditSnapshot) -> None:
        _require_active_r6_activation_uow()
        values = _audit_snapshot_values(snapshot)
        try:
            with _claim_r6_activation_insert(
                token=self._token,
                model_type=R6ActivationAuditSnapshotModel,
                expected_values=values,
            ):
                R6ActivationAuditSnapshotModel._default_manager.using(self._using).create(**values)
        except IntegrityError as error:
            raise R6ActivationConflict(
                "activation audit snapshot identity already exists"
            ) from error

    def append_event(
        self,
        *,
        authorization: R6ActivationAuthorization,
        event: R6ActivationEvent,
    ) -> R6ActivationEvent:
        """Replay and atomically append one exact three-way stream commit."""

        _require_active_r6_activation_uow()
        try:
            canonical_authorization = decode_r6_activation_authorization(
                encode_r6_activation_authorization(authorization)
            )
            canonical_event = decode_r6_activation_event(encode_r6_activation_event(event))
        except (R6ActivationCodecError, TypeError, ValueError) as error:
            raise R6ActivationCorruption("activation append payload is malformed") from error
        now = self.server_now()
        if canonical_event.recorded_at > now:
            raise R6ActivationUnavailable("future activation event cannot be persisted")
        if canonical_event.recorded_at != canonical_event.occurred_at:
            raise R6ActivationCorruption("activation event must use one server clock instant")
        existing = self._winner_for_authorization(canonical_authorization.ref)
        if existing is not None:
            if existing == canonical_event:
                return existing
            raise R6ActivationConflict("activation authorization already has another winner")
        history = self._restore_stream(
            scope_ref=canonical_event.scope_ref,
            as_of=now,
        )
        try:
            replayed = create_r6_activation_event(
                authorization=canonical_authorization,
                previous_events=history,
                applied_at=canonical_event.occurred_at,
            )
        except Exception as error:
            raise R6ActivationConflict(
                "activation append does not extend the exact head"
            ) from error
        if replayed != canonical_event:
            raise R6ActivationCorruption("activation append differs from authoritative replay")
        ledger_recorded_at = now
        try:
            with transaction.atomic(using=self._using):
                authorization_model = self._append_authorization(
                    canonical_authorization,
                    ledger_recorded_at=ledger_recorded_at,
                )
                event_model = self._append_event_row(
                    authorization_model=authorization_model,
                    event=canonical_event,
                    ledger_recorded_at=ledger_recorded_at,
                )
                self._append_stream_commit(
                    authorization_model=authorization_model,
                    event_model=event_model,
                    authorization=canonical_authorization,
                    event=canonical_event,
                    ledger_recorded_at=ledger_recorded_at,
                )
        except IntegrityError as error:
            winner = self._winner_for_authorization(canonical_authorization.ref)
            if winner == canonical_event:
                return winner
            raise R6ActivationConflict("activation append lost an identity/head race") from error
        winner = self._winner_for_authorization(canonical_authorization.ref)
        if winner != canonical_event:
            raise R6ActivationCorruption("activation append winner failed exact replay")
        return winner

    def _append_authorization(
        self,
        authorization: R6ActivationAuthorization,
        *,
        ledger_recorded_at: datetime,
    ) -> R6ActivationAuthorizationModel:
        collisions = self._authorization_collisions(authorization)
        if collisions:
            for model in collisions:
                self._restore_authorization(model)
            raise R6ActivationConflict("activation authorization identity is already sealed")
        values = _authorization_values(
            authorization,
            ledger_recorded_at=ledger_recorded_at,
        )
        with _claim_r6_activation_insert(
            token=self._token,
            model_type=R6ActivationAuthorizationModel,
            expected_values=values,
        ):
            return R6ActivationAuthorizationModel._default_manager.using(self._using).create(
                **values
            )

    def _append_event_row(
        self,
        *,
        authorization_model: R6ActivationAuthorizationModel,
        event: R6ActivationEvent,
        ledger_recorded_at: datetime,
    ) -> R6ActivationEventModel:
        values = _event_values(
            event,
            authorization_row_id=authorization_model.pk,
            ledger_recorded_at=ledger_recorded_at,
        )
        with _claim_r6_activation_insert(
            token=self._token,
            model_type=R6ActivationEventModel,
            expected_values=values,
        ):
            return R6ActivationEventModel._default_manager.using(self._using).create(**values)

    def _append_stream_commit(
        self,
        *,
        authorization_model: R6ActivationAuthorizationModel,
        event_model: R6ActivationEventModel,
        authorization: R6ActivationAuthorization,
        event: R6ActivationEvent,
        ledger_recorded_at: datetime,
    ) -> R6ActivationStreamCommitModel:
        values = _stream_commit_values(
            authorization=authorization,
            event=event,
            authorization_row_id=authorization_model.pk,
            event_row_id=event_model.pk,
            ledger_recorded_at=ledger_recorded_at,
        )
        with _claim_r6_activation_insert(
            token=self._token,
            model_type=R6ActivationStreamCommitModel,
            expected_values=values,
        ):
            return R6ActivationStreamCommitModel._default_manager.using(self._using).create(
                **values
            )

    def _authorization_collisions(
        self,
        authorization: R6ActivationAuthorization,
    ) -> tuple[R6ActivationAuthorizationModel, ...]:
        return tuple(
            R6ActivationAuthorizationModel._default_manager.using(self._using).filter(
                Q(
                    authorization_id=authorization.authorization_id,
                    authorization_version=authorization.authorization_version,
                )
                | Q(event_id=authorization.event_id, event_version=authorization.event_version)
                | Q(content_hash=authorization.content_hash)
            )
        )

    def _winner_for_authorization(
        self,
        authorization_ref: R6ActivationAuthorizationRef,
    ) -> R6ActivationEvent | None:
        persisted = self.get_by_authorization(
            authorization_ref=authorization_ref,
        )
        return None if persisted is None else persisted.event


__all__ = [
    "DjangoR6ActivationClock",
    "DjangoR6ActivationRepository",
]
