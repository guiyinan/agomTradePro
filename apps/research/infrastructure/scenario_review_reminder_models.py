"""Append-only ORM rows for the internal R7 human-review reminder ledger."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import timedelta
from typing import TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)


class ScenarioReviewAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject Django 5 ``ON CONFLICT DO UPDATE`` through QuerySets."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_ModelT]:
        """Permit inserts while refusing any conflict-update mutation path."""

        if update_conflicts:
            raise ValidationError("Append-only evidence cannot update on conflict.")
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=False,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class ScenarioReviewAppendOnlyManager(AppendOnlyManager[_ModelT]):
    """Expose the stronger reminder-specific guarded QuerySet."""

    def get_queryset(self) -> ScenarioReviewAppendOnlyQuerySet[_ModelT]:
        """Return append-only reminder QuerySets for every manager path."""

        return ScenarioReviewAppendOnlyQuerySet(self.model, using=self._db)

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


class ScenarioReviewAppendOnlyModel(models.Model):
    """Reject instance, default-manager, base-manager, and related mutation paths."""

    objects = ScenarioReviewAppendOnlyManager()

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
        """Allow inserts only."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("Scenario review reminder evidence is append-only.")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject destructive deletion of research evidence."""

        raise ValidationError("Scenario review reminder evidence cannot be deleted.")


class ScenarioReviewReminderModel(ScenarioReviewAppendOnlyModel):
    """Immutable schedule header and exact source binding for one reminder."""

    reminder_id = models.CharField(max_length=64, primary_key=True)
    reminder_version = models.CharField(max_length=128)
    intent_id = models.CharField(max_length=64, unique=True)
    intent_version = models.CharField(max_length=128)
    intent_content_hash = models.CharField(max_length=64)
    forecast_entry_id = models.CharField(max_length=64, db_index=True)
    forecast_group_id = models.CharField(max_length=128)
    forecast_observation_hash = models.CharField(max_length=64)
    probability_policy_version = models.CharField(max_length=128)
    probability_policy_hash = models.CharField(max_length=64)
    scenario_revision_id = models.UUIDField(db_index=True)
    scenario_set_revision_id = models.UUIDField(null=True, blank=True, db_index=True)
    invalidation_evidence_hash = models.CharField(max_length=64)
    intent_reason_code = models.CharField(max_length=128)
    schedule_version = models.CharField(max_length=128)
    schedule_policy_hash = models.CharField(max_length=64)
    expiry_delay = models.DurationField()
    escalation_delay = models.DurationField()
    maximum_escalation_level = models.PositiveSmallIntegerField()
    path_horizon_periods = models.PositiveSmallIntegerField()
    owner_evidence_hash = models.CharField(max_length=64)
    escalation_policy_version = models.CharField(max_length=128)
    escalation_policy_hash = models.CharField(max_length=64)
    path_evidence_hash = models.CharField(max_length=64)
    period_bindings = models.JSONField()
    created_at = models.DateTimeField()
    due_at = models.DateTimeField(db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    delivery_scope = models.CharField(max_length=32, default="internal_review")
    must_not_execute = models.BooleanField(default=True)
    external_dispatch_requested = models.BooleanField(default=False)
    auto_approval_requested = models.BooleanField(default=False)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    content_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_scenario_review_reminder"
        base_manager_name = "objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(
                fields=["due_at", "expires_at"],
                name="research_srr_due_exp_idx",
            ),
            models.Index(
                fields=["scenario_revision_id", "created_at"],
                name="research_srr_rev_created_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(due_at__gte=models.F("created_at")),
                name="research_srr_due_after_created_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("due_at")),
                name="research_srr_exp_after_due_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(maximum_escalation_level__gte=1),
                name="research_srr_max_level_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(path_horizon_periods__gte=1),
                name="research_srr_path_horizon_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(expiry_delay__gt=timedelta(0)),
                name="research_srr_expiry_delay_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(escalation_delay__gt=timedelta(0)),
                name="research_srr_escalation_delay_positive_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        delivery_scope="internal_review",
                        must_not_execute=True,
                        external_dispatch_requested=False,
                        auto_approval_requested=False,
                        research_only=True,
                        must_not_use_for_decision=True,
                    )
                ),
                name="research_srr_internal_only_ck",
            ),
        ]


class ScenarioReviewReminderEventModel(ScenarioReviewAppendOnlyModel):
    """Immutable root/hash-chain occurrence in the internal pull outbox."""

    event_id = models.CharField(max_length=64, primary_key=True)
    event_version = models.CharField(max_length=128)
    reminder = models.ForeignKey(
        ScenarioReviewReminderModel,
        on_delete=models.PROTECT,
        related_name="events",
    )
    event_type = models.CharField(max_length=24, db_index=True)
    sequence = models.PositiveIntegerField()
    escalation_level = models.PositiveSmallIntegerField(default=0)
    occurred_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField()
    actor_evidence_hash = models.CharField(max_length=64)
    reason_code = models.CharField(max_length=128)
    idempotency_key = models.CharField(max_length=255, db_index=True)
    previous_event_hash = models.CharField(max_length=64, null=True, blank=True)
    delivery_scope = models.CharField(max_length=32, default="internal_review")
    must_not_execute = models.BooleanField(default=True)
    external_dispatch_requested = models.BooleanField(default=False)
    auto_approval_requested = models.BooleanField(default=False)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    content_hash = models.CharField(max_length=64, unique=True)
    record_hash = models.CharField(max_length=64, unique=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_scenario_review_reminder_event"
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["reminder_id", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["reminder", "sequence"],
                name="research_srr_event_sequence_uniq",
            ),
            models.UniqueConstraint(
                fields=["reminder", "idempotency_key"],
                name="research_srr_event_idempotency_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        sequence=1,
                        event_type="scheduled",
                        previous_event_hash__isnull=True,
                    )
                    | (
                        models.Q(sequence__gt=1, previous_event_hash__isnull=False)
                        & ~models.Q(event_type="scheduled")
                    )
                ),
                name="research_srr_event_root_chain_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        delivery_scope="internal_review",
                        must_not_execute=True,
                        external_dispatch_requested=False,
                        auto_approval_requested=False,
                        research_only=True,
                        must_not_use_for_decision=True,
                    )
                ),
                name="research_srr_event_internal_only_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(recorded_at__gte=models.F("occurred_at")),
                name="research_srr_event_recorded_after_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["reminder", "occurred_at"],
                name="research_srr_event_time_idx",
            )
        ]


__all__ = ["ScenarioReviewReminderEventModel", "ScenarioReviewReminderModel"]
