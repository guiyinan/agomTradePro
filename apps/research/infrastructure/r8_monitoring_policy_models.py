"""Append-only Research owner row for the independent R8 monitoring policy."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.research.infrastructure.r5_relative_value_monitoring_models import (
    R5MonitoringAppendOnlyModel,
)


class R8MonitoringPolicyRegistryModel(R5MonitoringAppendOnlyModel):
    """Immutable dedicated policy definition and source receipt."""

    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=128)
    policy_hash = models.CharField(max_length=64, unique=True)
    definition_version = models.CharField(max_length=128)
    definition_hash = models.CharField(max_length=64, unique=True)
    source_receipt_id = models.CharField(max_length=192)
    source_receipt_version = models.CharField(max_length=128)
    source_receipt_hash = models.CharField(max_length=64, unique=True)
    target_result_id = models.CharField(max_length=192)
    target_result_hash = models.CharField(max_length=64)
    target_receipt_id = models.CharField(max_length=192)
    target_receipt_hash = models.CharField(max_length=64)
    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=128)
    calendar_hash = models.CharField(max_length=64)
    source_available_at = models.DateTimeField()
    source_valid_until = models.DateTimeField()
    policy_recorded_at = models.DateTimeField()
    policy_valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    definition_payload = models.JSONField()
    source_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta(R5MonitoringAppendOnlyModel.Meta):
        db_table = "research_r8_monitoring_policy_registry"
        indexes = [
            models.Index(
                fields=("policy_id", "policy_version", "ledger_recorded_at"),
                name="res_r8_policy_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("policy_id", "policy_version"),
                name="res_r8_policy_id_uq",
            ),
            models.UniqueConstraint(
                fields=("source_receipt_id", "source_receipt_version"),
                name="res_r8_policy_source_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_available_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(policy_recorded_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("source_valid_until"))
                    & models.Q(ledger_recorded_at__lt=models.F("policy_valid_until"))
                ),
                name="res_r8_policy_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    definition_version="research-r8-monitoring-policy-definition.v1",
                    source_receipt_version="research-r8-monitoring-policy-source.v1",
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="res_r8_policy_safe_ck",
            ),
        ]


@receiver(
    pre_delete,
    sender=R8MonitoringPolicyRegistryModel,
    dispatch_uid="reject_research_r8_monitoring_policy_registry_delete",
    weak=False,
)
def _reject_r8_monitoring_policy_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("Research R8 monitoring policies cannot be deleted.")


__all__ = ["R8MonitoringPolicyRegistryModel"]
