"""Append-only journal rows for one G5 historical available-share repair."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, router
from django.db.models import Q

_ACTION_APPLY = "apply"
_ACTION_ROLLBACK = "rollback"


class HistoricalSellableRepairJournalQuerySet(
    models.QuerySet["HistoricalSellableRepairJournalModel"]
):
    """Reject bulk mutation so repair and rollback evidence remains append-only."""

    def update(self, **kwargs: Any) -> int:
        """Disallow rewriting a persisted repair proof."""

        del kwargs
        raise ValidationError("G5 historical sellability repair journal is append-only")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Disallow deleting a persisted repair proof."""

        raise ValidationError("G5 historical sellability repair journal is append-only")

    def bulk_create(
        self,
        objs: Iterable[HistoricalSellableRepairJournalModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Iterable[str] | None = None,
        unique_fields: Iterable[str] | None = None,
    ) -> list[HistoricalSellableRepairJournalModel]:
        """Require the row writer to append one event in its locked transaction."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("G5 repair journal events must be appended individually")


HistoricalSellableRepairJournalManager = models.Manager.from_queryset(
    HistoricalSellableRepairJournalQuerySet
)


class HistoricalSellableRepairJournalModel(models.Model):
    """One immutable apply or rollback event bound to a complete ledger proof."""

    ACTION_APPLY = "apply"
    ACTION_ROLLBACK = "rollback"
    ACTION_CHOICES = ((ACTION_APPLY, "Apply"), (ACTION_ROLLBACK, "Rollback"))

    action = models.CharField(max_length=12, choices=ACTION_CHOICES)
    account_id = models.PositiveBigIntegerField()
    owner_user_id = models.PositiveBigIntegerField()
    actor_user_id = models.PositiveBigIntegerField()
    source_scope = models.CharField(max_length=32)
    source_position_id = models.PositiveBigIntegerField(null=True, blank=True)
    target_position_id = models.PositiveBigIntegerField()
    position_mapping_id = models.PositiveBigIntegerField(null=True, blank=True)
    security_id = models.CharField(max_length=64)
    asset_code = models.CharField(max_length=20)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    apply_event_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_total_quantity = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        null=True,
        blank=True,
    )
    source_record_updated_at = models.DateTimeField(null=True, blank=True)
    target_total_quantity = models.DecimalField(max_digits=20, decimal_places=6)
    evidence_cutoff_at = models.DateTimeField()
    evidence_proof_hash = models.CharField(max_length=64)
    before_available_quantity = models.DecimalField(max_digits=20, decimal_places=6)
    before_available_quantity_known = models.BooleanField()
    after_available_quantity = models.DecimalField(max_digits=20, decimal_places=6)
    after_available_quantity_known = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = HistoricalSellableRepairJournalManager()

    class Meta:
        base_manager_name = "objects"
        db_table = "sim_historical_sellable_repair_journal"
        ordering = ["account_id", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=("account_id", "idempotency_key"),
                name="sim_g5_repair_account_key_uq",
            ),
            models.UniqueConstraint(
                fields=("apply_event_id",),
                condition=Q(action=_ACTION_ROLLBACK, apply_event_id__isnull=False),
                name="sim_g5_repair_one_rollback_uq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(action=_ACTION_APPLY, apply_event_id__isnull=True)
                    | Q(action=_ACTION_ROLLBACK, apply_event_id__gt=0)
                ),
                name="sim_g5_repair_action_link_ck",
            ),
            models.CheckConstraint(
                condition=(
                    Q(account_id__gt=0)
                    & Q(owner_user_id__gt=0)
                    & Q(actor_user_id__gt=0)
                    & Q(target_position_id__gt=0)
                    & Q(idempotency_key__gt="")
                    & Q(request_hash__regex=r"^[0-9a-f]{64}$")
                    & Q(evidence_proof_hash__regex=r"^[0-9a-f]{64}$")
                    & Q(target_total_quantity__gte=0)
                    & Q(before_available_quantity__gte=0)
                    & Q(after_available_quantity__gte=0)
                    & (
                        Q(
                            source_scope="simulated_position",
                            source_position_id__isnull=True,
                            position_mapping_id__isnull=True,
                            source_total_quantity__isnull=True,
                            source_record_updated_at__isnull=True,
                        )
                        | Q(
                            source_scope="account_position_mapping",
                            source_position_id__gt=0,
                            position_mapping_id__gt=0,
                            source_total_quantity__gte=0,
                        )
                    )
                ),
                name="sim_g5_repair_identity_values_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("account_id", "target_position_id", "created_at"),
                name="sim_g5_repair_scope_idx",
            ),
            models.Index(
                fields=("actor_user_id", "created_at"),
                name="sim_g5_repair_actor_idx",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Allow insert only; existing journal events cannot be changed."""

        if self.pk is not None:
            using = kwargs.get("using") or self._state.db or router.db_for_write(type(self))
            if type(self)._base_manager.using(using).filter(pk=self.pk).exists():
                raise ValidationError("G5 historical sellability repair journal is append-only")
            raise ValidationError("G5 journal events cannot be inserted with a preset primary key")
        super().save(*args, **kwargs)

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Keep apply/rollback evidence permanently addressable."""

        del using, keep_parents
        raise ValidationError("G5 historical sellability repair journal is append-only")
