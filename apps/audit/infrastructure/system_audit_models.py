"""Schema-only append-only models for the canonical system audit event.

The repository/outbox implementation is intentionally a later M1 step.  These
models expose only private claimed-insert capabilities so a direct ORM caller
cannot mutate or seed the ledger accidentally.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

_UOW: ContextVar[object | None] = ContextVar("audit_event_uow", default=None)
_CLAIM: ContextVar[object | None] = ContextVar("audit_event_insert_claim", default=None)
_T = TypeVar("_T", bound=models.Model)


@dataclass(frozen=True, slots=True)
class _InsertClaim:
    event_id: str
    content_hash: str


@contextmanager
def _activate_system_audit_uow() -> Iterator[object]:
    """Activate the private non-nestable capability used by a future repository."""

    if _UOW.get() is not None:
        raise ValidationError("system audit UOWs may not be nested")
    token = object()
    reset = _UOW.set(token)
    try:
        yield token
    finally:
        _UOW.reset(reset)


@contextmanager
def _claim_system_audit_insert(event_id: str, content_hash: str) -> Iterator[None]:
    """Allow one exact new row insert; ordinary callers cannot use this helper."""

    if _UOW.get() is None or _CLAIM.get() is not None:
        raise ValidationError("system audit insert requires a private non-nested UOW")
    token = _CLAIM.set(_InsertClaim(event_id=event_id, content_hash=content_hash))
    try:
        yield
    finally:
        _CLAIM.reset(token)


class _AppendOnlyQuerySet(models.QuerySet[_T]):
    def update(self, **kwargs: object) -> NoReturn:
        raise ValidationError("system audit events are append-only")

    def delete(self) -> NoReturn:
        raise ValidationError("system audit events are append-only")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("system audit events are append-only")

    def bulk_update(
        self, objs: Iterable[_T], fields: Iterable[str], batch_size: int | None = None
    ) -> NoReturn:
        raise ValidationError("system audit events are append-only")


class _AppendOnlyManager(models.Manager[_T]):
    def get_queryset(self) -> _AppendOnlyQuerySet[_T]:
        return _AppendOnlyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("system audit events are append-only")

    def bulk_update(
        self,
        objs: Iterable[_T],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> NoReturn:
        raise ValidationError("system audit events are append-only")


class SystemAuditEventModel(models.Model):
    """Canonical event ledger row; no update/delete path is public."""

    event_id = models.CharField(max_length=128)
    event_version = models.CharField(max_length=64)
    schema_version = models.CharField(max_length=64)
    category = models.CharField(max_length=64)
    event_type = models.CharField(max_length=128)
    owner = models.CharField(max_length=64)
    write_policy = models.CharField(max_length=32)
    outcome = models.CharField(max_length=32)
    severity = models.CharField(max_length=16)
    reason_codes = models.JSONField(encoder=DjangoJSONEncoder)
    occurred_at = models.DateTimeField()
    recorded_at = models.DateTimeField(db_index=True)
    observed_at = models.DateTimeField(null=True, blank=True)
    actor_type = models.CharField(max_length=64)
    actor_id = models.CharField(max_length=256)
    actor_display = models.CharField(max_length=256, null=True, blank=True)
    source_app = models.CharField(max_length=128)
    source_component = models.CharField(max_length=128)
    source_surface = models.CharField(max_length=64)
    correlations = models.JSONField(encoder=DjangoJSONEncoder)
    resource_type = models.CharField(max_length=128, null=True, blank=True)
    resource_id = models.CharField(max_length=256, null=True, blank=True)
    resource_version = models.CharField(max_length=128, null=True, blank=True)
    dataset_key = models.CharField(max_length=256, null=True, blank=True)
    provider_key = models.CharField(max_length=256, null=True, blank=True)
    capability = models.CharField(max_length=256, null=True, blank=True)
    publication_id = models.CharField(max_length=256, null=True, blank=True)
    evidence_refs = models.JSONField(encoder=DjangoJSONEncoder)
    detail_schema = models.CharField(max_length=128)
    detail = models.JSONField(encoder=DjangoJSONEncoder)
    canonical_payload = models.JSONField(encoder=DjangoJSONEncoder)
    stream_id = models.CharField(max_length=256, db_index=True)
    sequence_no = models.PositiveBigIntegerField()
    predecessor_hash = models.CharField(max_length=64, null=True, blank=True)
    idempotency_key = models.CharField(max_length=256)
    identity_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    persisted_at = models.DateTimeField()

    objects = _AppendOnlyManager["SystemAuditEventModel"]()

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if (
            not self._state.adding
            or self.pk is not None
            or force_update
            or update_fields is not None
        ):
            raise ValidationError("system audit events are append-only")
        self._require_insert_claim()
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if (
            not self._state.adding
            or self.pk is not None
            or raw
            or force_update
            or update_fields is not None
        ):
            raise ValidationError("system audit events are append-only")
        self._require_insert_claim()
        super().save_base(
            raw=raw,
            force_insert=force_insert,
            using=using,
            update_fields=update_fields,
        )

    def _require_insert_claim(self) -> None:
        claim = _CLAIM.get()
        if (
            not isinstance(claim, _InsertClaim)
            or claim.event_id != self.event_id
            or claim.content_hash != self.content_hash
        ):
            raise ValidationError("system audit insert requires an exact private claim")

    def delete(self, *args: object, **kwargs: object) -> NoReturn:
        raise ValidationError("system audit events are append-only")

    class Meta:
        app_label = "audit"
        db_table = "audit_system_event"
        ordering = ["stream_id", "sequence_no"]
        default_manager_name = "objects"
        base_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["event_id", "event_version"], name="audit_event_identity_unique"
            ),
            models.UniqueConstraint(
                fields=["identity_hash"], name="audit_event_identity_hash_unique"
            ),
            models.UniqueConstraint(
                fields=["content_hash"], name="audit_event_content_hash_unique"
            ),
            models.UniqueConstraint(
                fields=["stream_id", "sequence_no"], name="audit_event_stream_sequence_unique"
            ),
            models.UniqueConstraint(
                fields=["stream_id", "idempotency_key"],
                name="audit_event_stream_idempotency_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence_no__gte=1), name="audit_event_sequence_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=models.F("occurred_at")),
                name="audit_event_recorded_after_occurred",
            ),
            models.CheckConstraint(
                condition=models.Q(observed_at__isnull=True)
                | models.Q(recorded_at__gte=models.F("observed_at")),
                name="audit_event_recorded_after_observed",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(sequence_no=1, predecessor_hash__isnull=True)
                    | models.Q(sequence_no__gt=1, predecessor_hash__isnull=False)
                ),
                name="audit_event_root_successor_predecessor",
            ),
        ]
        indexes = [
            models.Index(
                fields=["event_type", "recorded_at"], name="audit_event_type_recorded_idx"
            ),
            models.Index(
                fields=["category", "outcome", "recorded_at"],
                name="audit_event_cat_outcome_idx",
            ),
            models.Index(fields=["actor_id", "recorded_at"], name="audit_event_actor_recorded_idx"),
        ]


def _reject_system_audit_delete(sender: type[models.Model], **kwargs: object) -> None:
    raise ValidationError("system audit events are append-only")


pre_delete.connect(
    _reject_system_audit_delete,
    sender=SystemAuditEventModel,
    dispatch_uid="audit_system_event_append_only_delete",
)
