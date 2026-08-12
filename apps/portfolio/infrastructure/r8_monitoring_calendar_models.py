"""Append-only Portfolio owner registry for the R8 monitoring calendar."""

from __future__ import annotations

from typing import NoReturn

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.portfolio.infrastructure.optimization_research_models import (
    OptimizationAppendOnlyModel,
)


class R8MonitoringCalendarRegistryModel(OptimizationAppendOnlyModel):
    """One immutable complete calendar and its canonical source authorization."""

    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=192)
    definition_hash = models.CharField(max_length=64)
    definition_payload = models.JSONField()
    source_receipt_id = models.CharField(max_length=192)
    source_receipt_version = models.CharField(max_length=192)
    source_receipt_hash = models.CharField(max_length=64)
    source_receipt_payload = models.JSONField()
    source_available_at = models.DateTimeField()
    source_valid_until = models.DateTimeField()
    source_evidence_ref = models.CharField(max_length=192)
    recorded_at = models.DateTimeField(db_index=True)
    first_period_start = models.DateTimeField()
    last_period_end = models.DateTimeField()
    valid_until = models.DateTimeField(db_index=True)
    period_count = models.PositiveIntegerField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(OptimizationAppendOnlyModel.Meta):
        db_table = "portfolio_r8_monitoring_calendar_registry"
        constraints = [
            models.UniqueConstraint(
                fields=("calendar_id", "calendar_version"),
                name="pf_r8_mon_cal_ident_uq",
            ),
            models.UniqueConstraint(
                fields=("source_receipt_id", "source_receipt_version"),
                name="pf_r8_mon_cal_source_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_available_at__lte=models.F("recorded_at"))
                    & models.Q(recorded_at__lte=models.F("first_period_start"))
                    & models.Q(first_period_start__lt=models.F("last_period_end"))
                    & models.Q(last_period_end__lt=models.F("valid_until"))
                    & models.Q(recorded_at__lt=models.F("source_valid_until"))
                    & models.Q(valid_until__lte=models.F("source_valid_until"))
                ),
                name="pf_r8_mon_cal_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(period_count__gte=1, period_count__lte=64),
                name="pf_r8_mon_cal_count_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="pf_r8_mon_cal_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("calendar_id", "calendar_version", "recorded_at"),
                name="pf_r8_mon_cal_pit_ix",
            )
        ]


@receiver(
    pre_delete,
    sender=R8MonitoringCalendarRegistryModel,
    weak=False,
)
def _reject_r8_monitoring_calendar_registry_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject Collector, cascade, and direct deletion paths."""

    raise ValidationError("R8 monitoring calendar owner records cannot be deleted.")


__all__ = ["R8MonitoringCalendarRegistryModel"]
