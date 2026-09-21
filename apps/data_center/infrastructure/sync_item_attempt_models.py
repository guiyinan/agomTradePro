"""Durable and mutation-guarded sync item-attempt evidence."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

from apps.data_center.domain.control_plane import (
    SyncItemAttempt,
    SyncItemAttemptPhase,
    SyncItemAttemptState,
)

_SYNC_ITEM_ATTEMPT_TRANSITION: ContextVar[object | None] = ContextVar(
    "data_center_sync_item_attempt_transition", default=None
)
_SYNC_ITEM_ATTEMPT_PERSISTENCE: ContextVar[object | None] = ContextVar(
    "data_center_sync_item_attempt_persistence", default=None
)
_TERMINAL_UPDATE_FIELDS = frozenset(
    {
        "state",
        "finished_at",
        "stored_count",
        "error_code",
        "error_message",
        "evidence_hash",
        "updated_at",
    }
)
_MODEL_T = TypeVar("_MODEL_T", bound=models.Model)


@contextmanager
def _activate_sync_item_attempt_transition() -> Iterator[None]:
    """Allow one repository-owned RUNNING-to-terminal update scope."""

    if _SYNC_ITEM_ATTEMPT_TRANSITION.get() is not None:
        raise ValidationError("sync item attempt transitions may not be nested")
    reset = _SYNC_ITEM_ATTEMPT_TRANSITION.set(object())
    try:
        yield
    finally:
        _SYNC_ITEM_ATTEMPT_TRANSITION.reset(reset)


@contextmanager
def _activate_sync_item_attempt_persistence() -> Iterator[None]:
    """Allow one repository-owned validated bulk insert scope."""

    if _SYNC_ITEM_ATTEMPT_PERSISTENCE.get() is not None:
        raise ValidationError("sync item attempt persistence scopes may not be nested")
    reset = _SYNC_ITEM_ATTEMPT_PERSISTENCE.set(object())
    try:
        yield
    finally:
        _SYNC_ITEM_ATTEMPT_PERSISTENCE.reset(reset)


class _SyncItemAttemptQuerySet(models.QuerySet[_MODEL_T]):
    """Read-capable queryset that permits only claimed terminal updates."""

    def update(self, **kwargs: object) -> int:
        if _SYNC_ITEM_ATTEMPT_TRANSITION.get() is None:
            raise ValidationError("sync item attempts require a repository transition")
        if not set(kwargs).issubset(_TERMINAL_UPDATE_FIELDS):
            raise ValidationError("sync item attempt transition fields are restricted")
        return super().update(**kwargs)

    def delete(self) -> NoReturn:
        raise ValidationError("sync item attempts cannot be deleted")

    def _raw_delete(self, using: str | None) -> NoReturn:
        del using
        raise ValidationError("sync item attempts cannot be deleted")

    def bulk_update(
        self,
        objs: Iterable[_MODEL_T],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        if _SYNC_ITEM_ATTEMPT_TRANSITION.get() is None:
            raise ValidationError("sync item attempts require a repository transition")
        field_names = tuple(fields)
        if not set(field_names).issubset(_TERMINAL_UPDATE_FIELDS):
            raise ValidationError("sync item attempt transition fields are restricted")
        return super().bulk_update(objs, field_names, batch_size=batch_size)


class _SyncItemAttemptManager(models.Manager[_MODEL_T]):
    """Expose item-attempt reads and inserts while guarding mutations."""

    def get_queryset(self) -> _SyncItemAttemptQuerySet[_MODEL_T]:
        return _SyncItemAttemptQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_MODEL_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_MODEL_T]:
        if _SYNC_ITEM_ATTEMPT_PERSISTENCE.get() is None:
            raise ValidationError("sync item attempts require repository persistence")
        if (
            ignore_conflicts
            or update_conflicts
            or update_fields is not None
            or unique_fields is not None
        ):
            raise ValidationError("sync item attempt bulk conflicts are forbidden")
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )

    def bulk_update(
        self,
        objs: Iterable[_MODEL_T],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        if _SYNC_ITEM_ATTEMPT_TRANSITION.get() is None:
            raise ValidationError("sync item attempts require a repository transition")
        field_names = tuple(fields)
        if not set(field_names).issubset(_TERMINAL_UPDATE_FIELDS):
            raise ValidationError("sync item attempt transition fields are restricted")
        return super().bulk_update(objs, field_names, batch_size=batch_size)


class SyncItemAttemptModel(models.Model):
    """One durable, single-transition asset attempt in a sync batch."""

    PHASE_CHOICES = [(item.value, item.value) for item in SyncItemAttemptPhase]
    STATE_CHOICES = [(item.value, item.value) for item in SyncItemAttemptState]

    attempt_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run_id = models.UUIDField(db_index=True)
    batch_id = models.UUIDField(db_index=True)
    dataset_key = models.CharField(max_length=160, db_index=True)
    asset_code = models.CharField(max_length=20, db_index=True)
    phase = models.CharField(max_length=24, choices=PHASE_CHOICES)
    attempt_number = models.PositiveIntegerField()
    state = models.CharField(max_length=20, choices=STATE_CHOICES)
    execution_token = models.CharField(max_length=100)
    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    stored_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    universe_hash = models.CharField(max_length=64)
    authority_content_hash = models.CharField(max_length=64)
    evidence_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = _SyncItemAttemptManager["SyncItemAttemptModel"]()

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow inserts while requiring repository ownership for transitions."""

        if not self._state.adding or force_update or update_fields is not None:
            raise ValidationError("sync item attempts require a repository transition")
        self._validate_initial_insert()
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject raw loads and rewrites outside repository transition logic."""

        if not self._state.adding or raw or force_update or update_fields is not None:
            raise ValidationError("sync item attempts require a repository transition")
        self._validate_initial_insert()
        super().save_base(force_insert=force_insert, using=using)

    def _validate_initial_insert(self) -> None:
        """Require a complete domain-valid RUNNING row on initial insertion."""

        try:
            attempt = self.to_domain()
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"invalid sync item attempt insert: {exc}") from exc
        if attempt.state is not SyncItemAttemptState.RUNNING:
            raise ValidationError("sync item attempt inserts must start in RUNNING")

    def delete(self, *args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise ValidationError("sync item attempts cannot be deleted")

    class Meta:
        db_table = "data_center_sync_item_attempt"
        default_manager_name = "objects"
        base_manager_name = "objects"
        ordering = ["batch_id", "asset_code", "phase", "attempt_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch_id", "asset_code", "phase", "attempt_number"],
                name="dc_sync_item_attempt_unique",
            ),
            models.UniqueConstraint(
                fields=["batch_id", "asset_code", "phase"],
                condition=models.Q(state=SyncItemAttemptState.RUNNING.value),
                name="dc_item_one_running",
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_number__gte=1),
                name="dc_sync_item_attempt_number_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(state=SyncItemAttemptState.RUNNING.value, finished_at__isnull=True)
                    | (
                        ~models.Q(state=SyncItemAttemptState.RUNNING.value)
                        & models.Q(finished_at__isnull=False)
                    )
                ),
                name="dc_sync_item_attempt_terminal_time",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(
                        phase=SyncItemAttemptPhase.PUBLICATION.value,
                        state=SyncItemAttemptState.SUCCEEDED.value,
                    )
                    | ~models.Q(evidence_hash="")
                ),
                name="dc_item_pub_evidence",
            ),
        ]
        indexes = [
            models.Index(
                fields=["batch_id", "asset_code", "phase", "attempt_number"],
                name="dc_item_attempt_identity_idx",
            ),
            models.Index(
                fields=["batch_id", "state"],
                name="dc_item_attempt_state_idx",
            ),
            models.Index(
                fields=["run_id", "batch_id", "phase", "state"],
                name="dc_item_attempt_run_idx",
            ),
        ]

    def to_domain(self) -> SyncItemAttempt:
        """Convert the persisted row to immutable domain evidence."""

        return SyncItemAttempt(
            attempt_id=str(self.attempt_id),
            run_id=str(self.run_id),
            batch_id=str(self.batch_id),
            dataset_key=self.dataset_key,
            asset_code=self.asset_code,
            phase=SyncItemAttemptPhase(self.phase),
            attempt_number=self.attempt_number,
            state=SyncItemAttemptState(self.state),
            execution_token=self.execution_token,
            started_at=self.started_at,
            finished_at=self.finished_at,
            stored_count=self.stored_count,
            error_code=self.error_code,
            error_message=self.error_message,
            universe_hash=self.universe_hash,
            authority_content_hash=self.authority_content_hash,
            evidence_hash=self.evidence_hash,
        )


def _reject_sync_item_attempt_delete(sender: type[models.Model], **kwargs: object) -> None:
    """Reject collector and raw deletion of item-attempt evidence."""

    del sender, kwargs
    raise ValidationError("sync item attempts cannot be deleted")


pre_delete.connect(
    _reject_sync_item_attempt_delete,
    sender=SyncItemAttemptModel,
    dispatch_uid="data_center_sync_item_attempt_delete_guard",
)


__all__ = ["SyncItemAttemptModel"]
