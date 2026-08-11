"""Append-only canonical owner ledgers for R4 monitoring policy and calendar."""

from __future__ import annotations

from typing import NoReturn

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.research.infrastructure.r4_promotion_monitoring_models import (
    R4MonitoringAppendOnlyModel,
)


class R4MonitoringPolicyLedgerModel(R4MonitoringAppendOnlyModel):
    """One immutable Research-owned monitoring policy."""

    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    active_decision_id = models.CharField(max_length=192)
    active_decision_version = models.CharField(max_length=192)
    active_decision_hash = models.CharField(max_length=64)
    definition_hash = models.CharField(max_length=64)
    source_receipt_id = models.CharField(max_length=192)
    source_receipt_version = models.CharField(max_length=192)
    source_receipt_hash = models.CharField(max_length=64)
    source_receipt_payload = models.JSONField()
    recorded_at = models.DateTimeField(db_index=True)
    active_from = models.DateTimeField()
    active_until = models.DateTimeField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R4MonitoringAppendOnlyModel.Meta):
        db_table = "research_r4_monitoring_policy"
        constraints = [
            models.UniqueConstraint(
                fields=("policy_id", "policy_version"),
                name="res_r4_mon_pol_ident_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    recorded_at__lte=models.F("active_from"),
                    active_from__lt=models.F("active_until"),
                ),
                name="res_r4_mon_pol_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r4_mon_pol_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("policy_id", "policy_version", "recorded_at"),
                name="res_r4_mon_pol_pit_ix",
            )
        ]


class R4MonitoringCalendarLedgerModel(R4MonitoringAppendOnlyModel):
    """One immutable Research-owned canonical monitoring calendar."""

    source_owner = models.CharField(max_length=192)
    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=192)
    definition_hash = models.CharField(max_length=64)
    source_receipt_id = models.CharField(max_length=192)
    source_receipt_version = models.CharField(max_length=192)
    source_receipt_hash = models.CharField(max_length=64)
    source_receipt_payload = models.JSONField()
    recorded_at = models.DateTimeField(db_index=True)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    entry_count = models.PositiveIntegerField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(R4MonitoringAppendOnlyModel.Meta):
        db_table = "research_r4_monitoring_period_calendar"
        constraints = [
            models.UniqueConstraint(
                fields=("source_owner", "calendar_id", "calendar_version"),
                name="res_r4_mon_cal_ident_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    recorded_at__lte=models.F("valid_from"),
                    valid_from__lt=models.F("valid_until"),
                ),
                name="res_r4_mon_cal_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="res_r4_mon_cal_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("calendar_id", "calendar_version", "recorded_at"),
                name="res_r4_mon_cal_pit_ix",
            )
        ]


@receiver(pre_delete, sender=R4MonitoringPolicyLedgerModel, weak=False)
@receiver(pre_delete, sender=R4MonitoringCalendarLedgerModel, weak=False)
def _reject_r4_monitoring_owner_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject all ORM deletion paths for canonical owner records."""

    raise ValidationError("R4 monitoring owner records cannot be deleted.")


__all__ = ["R4MonitoringCalendarLedgerModel", "R4MonitoringPolicyLedgerModel"]
