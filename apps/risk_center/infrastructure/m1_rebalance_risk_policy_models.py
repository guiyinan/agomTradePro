"""Persistence model for immutable owner-approved M1 risk revisions."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.functions import Length, Trim
from django.db.models.lookups import GreaterThan

_AUDITED_REPOSITORY_CREATE_TOKEN = object()


class AppendOnlyM1RiskPolicyRevisionQuerySet(models.QuerySet["M1RebalanceRiskPolicyRevisionModel"]):
    """Prevent ordinary bulk ORM APIs from rewriting revision history."""

    def update(self, **kwargs: Any) -> int:
        """Reject a bulk update that would bypass the model save guard."""

        raise ValidationError("M1 risk policy revisions are immutable; publish a new version.")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Reject a bulk deletion that would erase policy evidence."""

        raise ValidationError("M1 risk policy revisions are immutable and cannot be deleted.")

    def bulk_create(
        self,
        objs: Iterable[M1RebalanceRiskPolicyRevisionModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[M1RebalanceRiskPolicyRevisionModel]:
        """Require revision creation to use the audited repository write path."""

        raise ValidationError("M1 risk policy revisions require the audited repository write path.")

    def bulk_update(
        self,
        objs: Iterable[M1RebalanceRiskPolicyRevisionModel],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        """Reject bulk updates that would bypass per-instance immutability."""

        raise ValidationError("M1 risk policy revisions are immutable; publish a new version.")


class M1RebalanceRiskPolicyRevisionModel(models.Model):
    """One additive, append-only M1 preview policy version.

    The row owns only a new M1 policy.  The source snapshot is a serialization
    of the exact account/strategy/rule content reviewed by the owner.  It does
    not backfill or version legacy rows.
    """

    APPLICABILITY_CHOICES = (
        ("applicable", "Applicable"),
        ("not_applicable", "Not applicable"),
        ("unknown", "Unknown"),
    )

    risk_policy_version = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account_id = models.PositiveBigIntegerField(db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="m1_rebalance_risk_revisions",
    )
    effective_from = models.DateTimeField()
    effective_until = models.DateTimeField()
    known_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()

    max_single_position_state = models.CharField(max_length=24, choices=APPLICABILITY_CHOICES)
    max_single_position_pct = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    max_single_position_reason = models.TextField(null=True, blank=True)
    max_total_position_state = models.CharField(max_length=24, choices=APPLICABILITY_CHOICES)
    max_total_position_pct = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    max_total_position_reason = models.TextField(null=True, blank=True)
    max_stop_loss_state = models.CharField(max_length=24, choices=APPLICABILITY_CHOICES)
    max_stop_loss_pct = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    max_stop_loss_reason = models.TextField(null=True, blank=True)

    source_snapshot_schema_version = models.CharField(max_length=32)
    source_snapshot = models.JSONField()
    risk_falsification_schema_version = models.CharField(max_length=32)
    risk_falsification_rules = models.JSONField()
    _repository_create_token: object | None = None
    objects = AppendOnlyM1RiskPolicyRevisionQuerySet.as_manager()

    class Meta:
        app_label = "risk_center"
        base_manager_name = "objects"
        db_table = "risk_center_m1_rebalance_policy_revision"
        verbose_name = "M1 Rebalance Risk Policy Revision"
        verbose_name_plural = "M1 Rebalance Risk Policy Revisions"
        indexes = [
            models.Index(
                fields=["account_id", "effective_from", "effective_until"],
                name="risk_m1_account_window_idx",
            ),
            models.Index(fields=["actor", "known_at"], name="risk_m1_actor_known_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(account_id__gt=0),
                name="risk_m1_account_pos_ck",
            ),
            models.CheckConstraint(
                condition=GreaterThan(
                    Length(Trim(models.F("reason"))),
                    models.Value(0),
                ),
                name="risk_m1_reason_nonempty_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_from__lt=models.F("effective_until")),
                name="risk_m1_effective_window_order",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        max_single_position_state="applicable",
                        max_single_position_pct__isnull=False,
                        max_single_position_pct__gte=0,
                        max_single_position_pct__lte=100,
                        max_single_position_reason__isnull=True,
                    )
                    | models.Q(
                        max_single_position_state="not_applicable",
                        max_single_position_pct__isnull=True,
                        max_single_position_reason__isnull=False,
                    )
                    & GreaterThan(
                        Length(Trim(models.F("max_single_position_reason"))),
                        models.Value(0),
                    )
                    | models.Q(
                        max_single_position_state="unknown",
                        max_single_position_pct__isnull=True,
                        max_single_position_reason__isnull=True,
                    )
                ),
                name="risk_m1_single_cond_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        max_total_position_state="applicable",
                        max_total_position_pct__isnull=False,
                        max_total_position_pct__gte=0,
                        max_total_position_pct__lte=100,
                        max_total_position_reason__isnull=True,
                    )
                    | models.Q(
                        max_total_position_state="not_applicable",
                        max_total_position_pct__isnull=True,
                        max_total_position_reason__isnull=False,
                    )
                    & GreaterThan(
                        Length(Trim(models.F("max_total_position_reason"))),
                        models.Value(0),
                    )
                    | models.Q(
                        max_total_position_state="unknown",
                        max_total_position_pct__isnull=True,
                        max_total_position_reason__isnull=True,
                    )
                ),
                name="risk_m1_total_cond_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        max_stop_loss_state="applicable",
                        max_stop_loss_pct__isnull=False,
                        max_stop_loss_pct__gte=0,
                        max_stop_loss_pct__lte=100,
                        max_stop_loss_reason__isnull=True,
                    )
                    | models.Q(
                        max_stop_loss_state="not_applicable",
                        max_stop_loss_pct__isnull=True,
                        max_stop_loss_reason__isnull=False,
                    )
                    & GreaterThan(
                        Length(Trim(models.F("max_stop_loss_reason"))),
                        models.Value(0),
                    )
                    | models.Q(
                        max_stop_loss_state="unknown",
                        max_stop_loss_pct__isnull=True,
                        max_stop_loss_reason__isnull=True,
                    )
                ),
                name="risk_m1_stop_cond_ck",
            ),
        ]

    def save(
        self,
        *args: Any,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject updates so an existing version can never be rewritten."""

        if not self._state.adding:
            raise ValidationError("M1 risk policy revisions are immutable; publish a new version.")
        if getattr(self, "_repository_create_token", None) is not _AUDITED_REPOSITORY_CREATE_TOKEN:
            raise ValidationError(
                "M1 risk policy revisions must be created through the audited repository."
            )
        self.full_clean()
        super().save(
            *args,
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
        """Reject deletion so audit references and effective policy history persist."""

        raise ValidationError("M1 risk policy revisions are immutable and cannot be deleted.")

    def __str__(self) -> str:
        """Return the exact version/account identity for admin and logs."""

        return f"M1RiskPolicyRevision({self.risk_policy_version}, account={self.account_id})"


__all__: tuple[str, ...] = ("M1RebalanceRiskPolicyRevisionModel",)
