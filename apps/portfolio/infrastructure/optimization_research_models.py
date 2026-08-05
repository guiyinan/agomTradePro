"""Append-only ORM tables for governed optimization results and lifecycle."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)


class OptimizationAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Permit inserts while rejecting ON-CONFLICT update paths."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_ModelT]:
        """Reject conflict-skipping or updating through every manager path."""

        if ignore_conflicts or update_conflicts:
            raise ValidationError(
                "Append-only optimization evidence cannot ignore or update on conflict."
            )
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=False,
            update_conflicts=False,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class OptimizationAppendOnlyManager(AppendOnlyManager[_ModelT]):
    """Expose guarded optimization QuerySets for every manager path."""

    def get_queryset(self) -> OptimizationAppendOnlyQuerySet[_ModelT]:
        """Return a guarded QuerySet for this database alias."""

        return OptimizationAppendOnlyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_ModelT]:
        """Delegate inserts to the guarded QuerySet."""

        return self.get_queryset().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class OptimizationAppendOnlyModel(models.Model):
    """Reject instance and manager mutation of evidentiary rows."""

    objects = OptimizationAppendOnlyManager()

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
        """Allow only the first append."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("Optimization research evidence is append-only.")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(
        self,
        using: Any | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Optimization research evidence is append-only.")


class GovernedOptimizationResearchResultModel(OptimizationAppendOnlyModel):
    """Immutable four-candidate research comparison result."""

    result_id = models.CharField(max_length=80, primary_key=True)
    result_version = models.CharField(max_length=128)
    run_key = models.CharField(max_length=160)
    run_version = models.CharField(max_length=128)
    assembly_hash = models.CharField(max_length=64)
    problem_id = models.CharField(max_length=192, db_index=True)
    problem_hash = models.CharField(max_length=64)
    input_set_id = models.CharField(max_length=192, db_index=True)
    input_set_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=[("blocked", "Blocked"), ("completed", "Completed")],
        db_index=True,
    )
    selected_candidate = models.CharField(max_length=32, blank=True, default="")
    candidates = models.JSONField(default=list, blank=True)
    problem_blockers = models.JSONField(default=list, blank=True)
    evaluated_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField(db_index=True)
    content_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    research_only = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_governed_optimization_result"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["run_key", "run_version"],
                name="pf_opt_result_run_ver_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_until__gt=models.F("evaluated_at")),
                name="pf_opt_result_valid_eval_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_execute=True,
                    must_not_use_for_decision=True,
                ),
                name="pf_opt_result_research_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "-evaluated_at"],
                name="pf_opt_result_status_eval_idx",
            ),
        ]


class OptimizationResearchLifecycleEventModel(OptimizationAppendOnlyModel):
    """Immutable hash-chain event for one governed result."""

    event_id = models.CharField(max_length=80, primary_key=True)
    result = models.ForeignKey(
        GovernedOptimizationResearchResultModel,
        on_delete=models.PROTECT,
        related_name="lifecycle_events",
    )
    result_hash = models.CharField(max_length=64)
    event_type = models.CharField(
        max_length=24,
        choices=[
            ("recorded", "Recorded"),
            ("promotion_attested", "Promotion attested"),
            ("retired", "Retired"),
            ("rolled_back", "Rolled back"),
        ],
        db_index=True,
    )
    sequence = models.PositiveIntegerField()
    occurred_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField()
    reason_codes = models.JSONField(default=list, blank=True)
    previous_event_hash = models.CharField(max_length=64, null=True, blank=True)
    promotion_attestation = models.JSONField(null=True, blank=True)
    owner_attestation = models.JSONField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, unique=True)
    canonical_payload = models.JSONField()
    research_only = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_optimization_lifecycle_event"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["result", "sequence"],
                name="pf_opt_lc_result_seq_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1),
                name="pf_opt_lc_seq_pos_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=models.F("occurred_at")),
                name="pf_opt_lc_record_time_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        event_type="recorded",
                        sequence=1,
                        previous_event_hash__isnull=True,
                        promotion_attestation__isnull=True,
                        owner_attestation__isnull=True,
                    )
                    | models.Q(
                        event_type="promotion_attested",
                        sequence__gt=1,
                        previous_event_hash__isnull=False,
                        promotion_attestation__isnull=False,
                        owner_attestation__isnull=True,
                    )
                    | models.Q(
                        event_type__in=["retired", "rolled_back"],
                        sequence__gt=1,
                        previous_event_hash__isnull=False,
                        promotion_attestation__isnull=True,
                        owner_attestation__isnull=False,
                    )
                ),
                name="pf_opt_lc_shape_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_execute=True,
                    must_not_use_for_decision=True,
                ),
                name="pf_opt_lc_research_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["result", "sequence"],
                name="pf_opt_lc_result_seq_idx",
            ),
        ]


__all__ = [
    "GovernedOptimizationResearchResultModel",
    "OptimizationResearchLifecycleEventModel",
]
