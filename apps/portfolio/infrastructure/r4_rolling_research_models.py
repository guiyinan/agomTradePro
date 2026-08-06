"""Append-only ORM ledger for Portfolio-owned R4 rolling research records."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_R4_REPOSITORY_CLOCK: ContextVar[datetime | None] = ContextVar(
    "portfolio_r4_repository_clock",
    default=None,
)


@contextmanager
def _r4_repository_append_unit(server_recorded_at: datetime) -> Iterator[None]:
    """Bind one private repository clock claim to an atomic append unit."""

    token = _R4_REPOSITORY_CLOCK.set(server_recorded_at)
    try:
        yield
    finally:
        _R4_REPOSITORY_CLOCK.reset(token)


class R4RollingAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every bulk insertion path for evidentiary rows."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_ModelT]:
        """Reject plain and conflict-aware bulk inserts."""

        raise ValidationError("Append-only R4 rolling evidence cannot be bulk created.")


class R4RollingAppendOnlyManager(AppendOnlyManager[_ModelT]):
    """Expose the guarded R4 QuerySet through default, base, and related paths."""

    def get_queryset(self) -> R4RollingAppendOnlyQuerySet[_ModelT]:
        """Return a guarded QuerySet for this database alias."""

        return R4RollingAppendOnlyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_ModelT]:
        """Reject plain and conflict-aware bulk inserts."""

        return self.get_queryset().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class R4RollingAppendOnlyModel(models.Model):
    """Reject instance updates and deletions for every R4 ledger row."""

    objects = R4RollingAppendOnlyManager()

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
        """Allow only the initial append."""

        self._validate_repository_append_authority()
        if (
            force_update
            or update_fields is not None
            or not self._state.adding
            or (self.pk is not None and type(self)._default_manager.filter(pk=self.pk).exists())
        ):
            raise ValidationError("R4 rolling research evidence is append-only.")
        super().save(
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(
        self,
        using: Any | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("R4 rolling research evidence is append-only.")

    def _validate_repository_append_authority(self) -> None:
        """Require Portfolio ownership, valid clocks, and a repository UoW claim."""

        server_recorded_at = _R4_REPOSITORY_CLOCK.get()
        if isinstance(self, R4RollingResearchReceiptModel):
            if self.owner != "portfolio":
                raise ValidationError("R4 rolling receipt owner must be portfolio.")
            if not self.evaluated_at <= self.recorded_at < self.valid_until:
                raise ValidationError("R4 rolling receipt clock bounds are invalid.")
            if server_recorded_at is None:
                raise ValidationError(
                    "R4 rolling evidence must be saved by the repository unit of work."
                )
            if self.recorded_at != server_recorded_at:
                raise ValidationError("R4 rolling receipt must use the repository server clock.")
            return
        if server_recorded_at is None:
            raise ValidationError(
                "R4 rolling evidence must be saved by the repository unit of work."
            )
        if isinstance(self, R4RollingResearchResultModel):
            if self.receipt_id is None or self.receipt.recorded_at != server_recorded_at:
                raise ValidationError(
                    "R4 rolling result must share the repository server clock receipt."
                )


class R4RollingResearchReceiptModel(R4RollingAppendOnlyModel):
    """Immutable input/provenance receipt stamped by the Portfolio repository."""

    receipt_id = models.CharField(max_length=80, primary_key=True)
    record_version = models.CharField(max_length=80)
    study_id = models.CharField(max_length=200)
    study_version = models.CharField(max_length=128)
    study_content_hash = models.CharField(max_length=64)
    r3_promotion_attestation_hash = models.CharField(max_length=64)
    split_contract_hash = models.CharField(max_length=64)
    evaluated_at = models.DateTimeField(db_index=True)
    owner = models.CharField(max_length=32, default="portfolio")
    recorded_at = models.DateTimeField(db_index=True)
    producer_code_version = models.CharField(max_length=200)
    dependency_lock_hash = models.CharField(max_length=64)
    valid_until = models.DateTimeField(db_index=True)
    study_payload = models.JSONField()
    promotion_attestation_payload = models.JSONField()
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_r4_rolling_research_receipt"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "study_id",
                    "study_version",
                    "evaluated_at",
                    "producer_code_version",
                    "dependency_lock_hash",
                ],
                name="pf_r4_receipt_identity_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=models.F("evaluated_at")),
                name="pf_r4_receipt_eval_record_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_until__gt=models.F("recorded_at")),
                name="pf_r4_receipt_record_valid_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(owner="portfolio"),
                name="pf_r4_receipt_owner_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["study_id", "-evaluated_at"],
                name="pf_r4_receipt_study_eval_idx",
            ),
        ]


class R4RollingResearchResultModel(R4RollingAppendOnlyModel):
    """Immutable factory-recomputed R4 rolling result and complete subhash ledger."""

    record_id = models.CharField(max_length=80, primary_key=True)
    receipt = models.ForeignKey(
        R4RollingResearchReceiptModel,
        on_delete=models.PROTECT,
        related_name="results",
    )
    artifact_hash = models.CharField(max_length=64, db_index=True)
    evidence_complete = models.BooleanField()
    eligible_for_research_comparison = models.BooleanField()
    subhashes = models.JSONField(default=list)
    artifact_payload = models.JSONField()
    record_hash = models.CharField(max_length=64, unique=True)
    usage_scope = models.CharField(max_length=32, default="research_only")
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_r4_rolling_research_result"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["receipt"],
                name="pf_r4_result_receipt_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(eligible_for_research_comparison=False)
                    | models.Q(evidence_complete=True)
                ),
                name="pf_r4_result_eligible_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    usage_scope="research_only",
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="pf_r4_result_research_ck",
            ),
        ]


__all__ = ["R4RollingResearchReceiptModel", "R4RollingResearchResultModel"]
