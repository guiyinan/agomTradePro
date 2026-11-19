"""Append-only extensions of Research experiment/trial/family, never a second registry."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)


class _StudyQuerySet(AppendOnlyQuerySet[_ModelT]):
    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject conflict/upsert shortcuts that could conceal prior OOS use."""
        raise ValidationError("Event-study evidence requires exact inserts.")


class _StudyManager(AppendOnlyManager[_ModelT]):
    def get_queryset(self) -> _StudyQuerySet[_ModelT]:
        """Use identical guards through both default and base managers."""
        return _StudyQuerySet(self.model, using=self._db)


class _StudyImmutableModel(models.Model):
    objects = _StudyManager()

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
        """Allow only a fresh database-assigned identity."""
        if self.pk is not None or force_update or update_fields is not None:
            raise ValidationError("Event-study evidence is immutable.")
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject raw fixture replacement and direct base-save mutation."""
        if raw or self.pk is not None or force_update or update_fields is not None:
            raise ValidationError("Event-study evidence is immutable.")
        super().save_base(force_insert=force_insert, using=using)

    def delete(self, using: object | None = None, keep_parents: bool = False) -> NoReturn:
        """Never refund an OOS use or remove its preregistration."""
        raise ValidationError("Event-study evidence cannot be deleted.")


class EventStudySpecModel(_StudyImmutableModel):
    """Operator-initialized original bytes and digest of a frozen specification."""

    spec_id = models.CharField(max_length=128, unique=True)
    document = models.TextField()
    document_sha256 = models.CharField(max_length=64, unique=True)
    registered_by_id = models.PositiveBigIntegerField()
    registered_at = models.DateTimeField()

    class Meta(_StudyImmutableModel.Meta):
        abstract = False
        db_table = "research_event_study_spec"


class EventStudyBindingModel(_StudyImmutableModel):
    """One designated final trial per experiment and stable preregistration key."""

    study_key = models.CharField(max_length=128, unique=True)
    spec = models.ForeignKey(EventStudySpecModel, on_delete=models.PROTECT)
    experiment = models.OneToOneField("research.ResearchExperiment", on_delete=models.PROTECT)
    family = models.ForeignKey("research.MultipleTestFamily", on_delete=models.PROTECT)
    trial = models.OneToOneField("research.ExperimentTrial", on_delete=models.PROTECT)
    manifest_id = models.CharField(max_length=64)
    manifest_sha256 = models.CharField(max_length=64)
    snapshot = models.JSONField()
    snapshot_sha256 = models.CharField(max_length=64)
    bound_by_id = models.PositiveBigIntegerField()
    bound_at = models.DateTimeField()

    class Meta(_StudyImmutableModel.Meta):
        abstract = False
        db_table = "research_event_study_binding"
        constraints = [
            models.UniqueConstraint(fields=["spec"], name="revent_study_spec_binding_uq")
        ]


class EventStudyFinalOOSClaimModel(_StudyImmutableModel):
    """Unique, irrevocable final-use receipt, committed before evaluator entry."""

    binding = models.OneToOneField(EventStudyBindingModel, on_delete=models.PROTECT)
    actor_user_id = models.PositiveBigIntegerField()
    cumulative_family_trials = models.PositiveIntegerField()
    claimed_at = models.DateTimeField()

    class Meta(_StudyImmutableModel.Meta):
        abstract = False
        db_table = "research_event_study_final_oos_claim"
