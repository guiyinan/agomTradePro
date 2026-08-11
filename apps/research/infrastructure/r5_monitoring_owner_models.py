"""Append-only ORM rows for independent R5 monitoring owner registries."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.research.infrastructure.r5_relative_value_monitoring_models import (
    R5MonitoringAppendOnlyModel,
)


class R5MonitoringPolicyRegistryModel(R5MonitoringAppendOnlyModel):
    """Immutable exact R5 monitoring policy plus source receipt."""

    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    policy_hash = models.CharField(max_length=64, unique=True)
    definition_hash = models.CharField(max_length=64, unique=True)
    source_receipt_id = models.CharField(max_length=192)
    source_receipt_version = models.CharField(max_length=192)
    source_receipt_hash = models.CharField(max_length=64, unique=True)
    source_available_at = models.DateTimeField()
    source_valid_until = models.DateTimeField()
    policy_recorded_at = models.DateTimeField()
    policy_valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    policy_payload = models.JSONField()
    source_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta(R5MonitoringAppendOnlyModel.Meta):
        db_table = "research_r5_monitoring_policy_registry"
        constraints = [
            models.UniqueConstraint(
                fields=("policy_id", "policy_version"),
                name="res_r5_mon_pol_reg_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_available_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(policy_recorded_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("source_valid_until"))
                    & models.Q(ledger_recorded_at__lt=models.F("policy_valid_until"))
                ),
                name="res_r5_mon_pol_reg_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r5_mon_pol_reg_safe_ck",
            ),
        ]


class R5MonitoringCalendarRegistryModel(R5MonitoringAppendOnlyModel):
    """Immutable exact R5 monitoring calendar plus source receipt."""

    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=192)
    calendar_hash = models.CharField(max_length=64, unique=True)
    definition_hash = models.CharField(max_length=64, unique=True)
    source_receipt_id = models.CharField(max_length=192)
    source_receipt_version = models.CharField(max_length=192)
    source_receipt_hash = models.CharField(max_length=64, unique=True)
    source_available_at = models.DateTimeField()
    source_valid_until = models.DateTimeField()
    calendar_recorded_at = models.DateTimeField()
    calendar_valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    calendar_payload = models.JSONField()
    source_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta(R5MonitoringAppendOnlyModel.Meta):
        db_table = "research_r5_monitoring_calendar_registry"
        constraints = [
            models.UniqueConstraint(
                fields=("calendar_id", "calendar_version"),
                name="res_r5_mon_cal_reg_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_available_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(calendar_recorded_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("source_valid_until"))
                    & models.Q(ledger_recorded_at__lt=models.F("calendar_valid_until"))
                ),
                name="res_r5_mon_cal_reg_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r5_mon_cal_reg_safe_ck",
            ),
        ]


@receiver(
    pre_delete,
    sender=R5MonitoringPolicyRegistryModel,
    dispatch_uid="reject_research_r5_monitoring_policy_registry_delete",
    weak=False,
)
@receiver(
    pre_delete,
    sender=R5MonitoringCalendarRegistryModel,
    dispatch_uid="reject_research_r5_monitoring_calendar_registry_delete",
    weak=False,
)
def _reject_r5_monitoring_owner_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("R5 monitoring owner registry cannot be deleted.")


__all__ = [
    "R5MonitoringCalendarRegistryModel",
    "R5MonitoringPolicyRegistryModel",
]
