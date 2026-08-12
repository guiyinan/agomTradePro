"""Append-only ORM schema for Regime-owned historical assignments."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)


@dataclass(frozen=True, slots=True)
class _InsertClaim:
    token: object
    model_name: str
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_UOW: ContextVar[object | None] = ContextVar(
    "regime_historical_assignment_uow",
    default=None,
)
_ACTIVE_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "regime_historical_assignment_claim",
    default=None,
)


@contextmanager
def historical_assignment_write_uow() -> Iterator[object]:
    """Activate a private insert UoW for the repository only."""

    token_value = object()
    reset = _ACTIVE_UOW.set(token_value)
    try:
        yield token_value
    finally:
        _ACTIVE_UOW.reset(reset)


@contextmanager
def historical_assignment_insert_claim(
    *,
    token: object,
    model: type[models.Model],
    expected_values: tuple[tuple[str, object], ...],
) -> Iterator[None]:
    """Authorize one exact force-insert inside the active repository UoW."""

    if token is not _ACTIVE_UOW.get():
        raise ValidationError("historical assignment insert claim is outside its UoW")
    reset = _ACTIVE_CLAIM.set(
        _InsertClaim(
            token=token,
            model_name=model._meta.label_lower,
            expected_values=expected_values,
        )
    )
    try:
        yield
    finally:
        _ACTIVE_CLAIM.reset(reset)


class HistoricalAssignmentQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Append-only queryset with no public creation surface."""

    def create(self, **kwargs: object) -> _ModelT:
        raise ValidationError("historical assignment evidence requires repository append")

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("historical assignment evidence cannot be bulk-created")


class HistoricalAssignmentManager(
    AppendOnlyManager[_ModelT],
):
    """Typed manager preserving append-only queryset guards."""

    def get_queryset(self) -> HistoricalAssignmentQuerySet[_ModelT]:
        return HistoricalAssignmentQuerySet(self.model, using=self._db)

    def create(self, **kwargs: object) -> _ModelT:
        raise ValidationError("historical assignment evidence requires repository append")

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("historical assignment evidence cannot be bulk-created")


class HistoricalAssignmentAppendOnlyModel(models.Model):
    """Base model rejecting direct update/delete and unclaimed inserts."""

    objects = HistoricalAssignmentManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow only one exact repository-claimed force insert."""

        if self.pk is not None or not force_insert or force_update or update_fields is not None:
            raise ValidationError("historical assignment evidence is append-only")
        _require_insert_claim(self)
        super().save(
            force_insert=True,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject raw and direct save_base bypasses."""

        if (
            raw
            or self.pk is not None
            or not force_insert
            or force_update
            or update_fields is not None
        ):
            raise ValidationError("historical assignment evidence is append-only")
        _require_insert_claim(self)
        super().save_base(
            raw=False,
            force_insert=True,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("historical assignment evidence cannot be deleted")


class HistoricalRegimeAssignmentDefinitionModel(HistoricalAssignmentAppendOnlyModel):
    """Regime owner definition and trusted registration receipt."""

    definition_id = models.CharField(max_length=192)
    definition_version = models.CharField(max_length=192)
    definition_content_hash = models.CharField(max_length=64, unique=True)
    artifact_id = models.CharField(max_length=64, db_index=True)
    artifact_hash = models.CharField(max_length=64)
    pit_manifest_id = models.CharField(max_length=192)
    pit_manifest_hash = models.CharField(max_length=64)
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    policy_content_hash = models.CharField(max_length=64)
    source_contract_id = models.CharField(max_length=192)
    source_contract_version = models.CharField(max_length=192)
    source_contract_hash = models.CharField(max_length=64)
    registered_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    record_hash = models.CharField(max_length=64, unique=True)
    owner = models.CharField(max_length=32, default="regime")
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(HistoricalAssignmentAppendOnlyModel.Meta):
        db_table = "regime_historical_assignment_definition"
        constraints = [
            models.UniqueConstraint(
                fields=["definition_id", "definition_version"],
                name="reg_hist_def_identity_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="regime")
                    & models.Q(registered_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("valid_until"))
                ),
                name="reg_hist_def_sem_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="reg_hist_def_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["definition_id", "definition_version", "ledger_recorded_at"],
                name="reg_hist_def_pit_idx",
            )
        ]


class HistoricalRegimeAssignmentReceiptModel(HistoricalAssignmentAppendOnlyModel):
    """Exhaustive derived assignments for one exact artifact and cutoff."""

    definition = models.ForeignKey(
        HistoricalRegimeAssignmentDefinitionModel,
        on_delete=models.PROTECT,
        related_name="assignment_receipts",
    )
    receipt_id = models.CharField(max_length=64, db_index=True)
    receipt_version = models.CharField(max_length=96)
    receipt_content_hash = models.CharField(max_length=64, unique=True)
    artifact_id = models.CharField(max_length=64, db_index=True)
    artifact_hash = models.CharField(max_length=64)
    source_result_hash = models.CharField(max_length=64)
    pit_manifest_id = models.CharField(max_length=192)
    pit_manifest_hash = models.CharField(max_length=64)
    pit_as_of = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    assignment_count = models.PositiveIntegerField()
    canonical_payload = models.JSONField()
    owner = models.CharField(max_length=32, default="regime")
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(HistoricalAssignmentAppendOnlyModel.Meta):
        db_table = "regime_historical_assignment_receipt"
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "pit_as_of"],
                name="reg_hist_receipt_cutoff_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="regime")
                    & models.Q(pit_as_of__lte=models.F("recorded_at"))
                    & models.Q(assignment_count__gt=0)
                ),
                name="reg_hist_receipt_sem_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="reg_hist_receipt_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["artifact_id", "artifact_hash", "pit_as_of", "recorded_at"],
                name="reg_hist_receipt_pit_idx",
            )
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
        raise ValidationError("historical assignment evidence requires exact insert claim")


def _reject_delete(**kwargs: object) -> NoReturn:
    raise ValidationError("historical assignment evidence cannot be deleted")


for _model in (
    HistoricalRegimeAssignmentDefinitionModel,
    HistoricalRegimeAssignmentReceiptModel,
):
    pre_delete.connect(
        _reject_delete,
        sender=_model,
        dispatch_uid=f"regime.historical_assignment.reject_delete.{_model.__name__}",
    )


__all__ = [
    "HistoricalRegimeAssignmentDefinitionModel",
    "HistoricalRegimeAssignmentReceiptModel",
    "historical_assignment_insert_claim",
    "historical_assignment_write_uow",
]
