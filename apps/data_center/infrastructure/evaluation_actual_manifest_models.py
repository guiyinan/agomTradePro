"""Append-only ORM ledgers for evaluation actual sources and manifests."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar, cast

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_UOW: ContextVar[object | None] = ContextVar("active_evaluation_actual_uow", default=None)


@dataclass(frozen=True, slots=True)
class _InsertClaim:
    token: object
    model_name: str
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_evaluation_actual_insert_claim", default=None
)


def _require_active_evaluation_actual_uow() -> object:
    """Require a repository-owned UoW around canonical owner reads."""

    token = _ACTIVE_UOW.get()
    if token is None:
        raise ValidationError("evaluation actual owner query requires an active unit of work")
    return token


@contextmanager
def _activate_evaluation_actual_uow(token: object) -> Iterator[None]:
    reset = _ACTIVE_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_UOW.reset(reset)


@contextmanager
def _claim_evaluation_actual_insert(
    *,
    token: object,
    model_name: str,
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    if _ACTIVE_UOW.get() is not token:
        raise ValidationError("evaluation actual insert requires its repository UoW")
    claim = _InsertClaim(
        token=token,
        model_name=model_name,
        expected_values=tuple(sorted(expected_values.items())),
    )
    reset = _ACTIVE_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_CLAIM.reset(reset)


class EvaluationActualQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject mutation and every unclaimed bulk insert path."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("evaluation actual evidence requires repository appends")

    def _update(self, values: object) -> NoReturn:
        raise ValidationError("evaluation actual evidence cannot be updated")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("evaluation actual evidence cannot be deleted")

    def _insert(
        self,
        objs: Iterable[_ModelT],
        fields: Iterable[object],
        returning_fields: Iterable[object] | None = None,
        raw: bool = False,
        using: str | None = None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> list[tuple[object, ...]]:
        items = list(objs)
        if (
            not items
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("evaluation actual private insert is forbidden")
        for item in items:
            _require_insert_claim(item)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 -- typed Django private boundary
        )
        return insert(
            items,
            fields,
            returning_fields=returning_fields,
            raw=False,
            using=using,
            on_conflict=None,
            update_fields=None,
            unique_fields=None,
        )

    def _batched_insert(
        self,
        objs: list[_ModelT],
        fields: list[object],
        batch_size: int | None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> NoReturn:
        raise ValidationError("evaluation actual private bulk insert is forbidden")


class EvaluationActualManager(AppendOnlyManager[_ModelT]):
    """Expose the same append guards through both Django managers."""

    def get_queryset(self) -> EvaluationActualQuerySet[_ModelT]:
        return EvaluationActualQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("evaluation actual evidence requires repository appends")


class EvaluationActualAppendOnlyModel(models.Model):
    """Base model enforcing repository-only inserts and immutable rows."""

    objects = EvaluationActualManager()

    class Meta:
        abstract = True

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("evaluation actual evidence is append-only")
        _require_insert_claim(self)
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("evaluation actual evidence is append-only")
        _require_insert_claim(self)
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("evaluation actual evidence cannot be deleted")


class EvaluationActualSourceDefinitionModel(EvaluationActualAppendOnlyModel):
    """Canonical versioned owner definition and registration receipt."""

    source_id = models.CharField(max_length=192)
    source_version = models.CharField(max_length=192)
    source_content_hash = models.CharField(max_length=64, unique=True)
    owner = models.CharField(max_length=32, default="data_center")
    dataset = models.CharField(max_length=192, db_index=True)
    subject_code = models.CharField(max_length=192, db_index=True)
    industry_code = models.CharField(max_length=192, db_index=True)
    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=192)
    calendar_content_hash = models.CharField(max_length=64)
    knowledge_scope = models.CharField(max_length=32)
    require_verified = models.BooleanField()
    minimum_coverage_ratio = models.DecimalField(max_digits=20, decimal_places=12)
    maximum_missing_count = models.PositiveIntegerField()
    maximum_estimated_count = models.PositiveIntegerField()
    maximum_unknown_count = models.PositiveIntegerField()
    registered_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    record_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_evaluation_actual_source"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["source_id", "source_version"], name="dc_evact_source_identity_uq"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="data_center")
                    & models.Q(registered_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("valid_until"))
                    & models.Q(minimum_coverage_ratio__gte=0)
                    & models.Q(minimum_coverage_ratio__lte=1)
                ),
                name="dc_evact_source_sem_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="dc_evact_source_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["source_id", "source_version", "ledger_recorded_at"],
                name="dc_evact_source_pit_idx",
            )
        ]


class EvaluationActualManifestReceiptModel(EvaluationActualAppendOnlyModel):
    """Complete internally materialized actual-manifest receipt."""

    source_definition = models.ForeignKey(
        EvaluationActualSourceDefinitionModel,
        on_delete=models.PROTECT,
        related_name="evaluation_actual_manifest_receipts",
    )
    manifest_id = models.CharField(max_length=192)
    manifest_version = models.CharField(max_length=192)
    manifest_content_hash = models.CharField(max_length=64, unique=True)
    owner = models.CharField(max_length=32, default="data_center")
    dataset = models.CharField(max_length=192, db_index=True)
    subject_code = models.CharField(max_length=192, db_index=True)
    industry_code = models.CharField(max_length=192, db_index=True)
    as_of_time = models.DateTimeField(db_index=True)
    produced_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField()
    knowledge_scope = models.CharField(max_length=32)
    is_verified = models.BooleanField()
    coverage_ratio = models.DecimalField(max_digits=20, decimal_places=12)
    missing_count = models.PositiveIntegerField()
    estimated_count = models.PositiveIntegerField()
    unknown_count = models.PositiveIntegerField()
    selected_versions_hash = models.CharField(max_length=64)
    canonical_payload = models.JSONField()
    receipt_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_evaluation_actual_manifest"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["manifest_id", "manifest_version"],
                name="dc_evact_manifest_identity_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="data_center")
                    & models.Q(as_of_time__lte=models.F("produced_at"))
                    & models.Q(produced_at__lt=models.F("valid_until"))
                    & models.Q(coverage_ratio__gte=0)
                    & models.Q(coverage_ratio__lte=1)
                ),
                name="dc_evact_manifest_sem_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="dc_evact_manifest_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["manifest_id", "manifest_version", "produced_at"],
                name="dc_evact_manifest_pit_idx",
            ),
            models.Index(
                fields=["source_definition", "as_of_time"],
                name="dc_evact_manifest_src_idx",
            ),
        ]


def _require_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_UOW.get()
        or claim.model_name != model._meta.label_lower
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("evaluation actual evidence requires an exact insert claim")


@receiver(pre_delete, sender=EvaluationActualSourceDefinitionModel, weak=False)
@receiver(pre_delete, sender=EvaluationActualManifestReceiptModel, weak=False)
def _reject_evaluation_actual_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject collector and cascade deletion paths."""

    raise ValidationError("evaluation actual evidence cannot be deleted")


__all__ = [
    "EvaluationActualManifestReceiptModel",
    "EvaluationActualSourceDefinitionModel",
]
