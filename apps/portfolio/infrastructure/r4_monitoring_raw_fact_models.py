"""Append-only Portfolio owner ledger for R4 monitoring raw facts."""

from __future__ import annotations

from typing import NoReturn

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.portfolio.infrastructure.optimization_research_models import (
    OptimizationAppendOnlyModel,
)


class PortfolioR4MonitoringRawFactReceiptModel(OptimizationAppendOnlyModel):
    """One immutable Portfolio-owned observation receipt."""

    observation_id = models.CharField(max_length=192)
    observation_version = models.CharField(max_length=192)
    active_decision_id = models.CharField(max_length=192)
    active_decision_version = models.CharField(max_length=192)
    active_decision_hash = models.CharField(max_length=64)
    policy_id = models.CharField(max_length=192)
    policy_version = models.CharField(max_length=192)
    policy_hash = models.CharField(max_length=64)
    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=192)
    calendar_hash = models.CharField(max_length=64)
    period_id = models.CharField(max_length=64)
    source_owner = models.CharField(max_length=192, default="portfolio")
    definition_hash = models.CharField(max_length=64)
    source_receipt_id = models.CharField(max_length=192)
    source_receipt_version = models.CharField(max_length=192)
    source_receipt_hash = models.CharField(max_length=64)
    source_receipt_payload = models.JSONField()
    observed_at = models.DateTimeField()
    available_at = models.DateTimeField()
    owner_recorded_at = models.DateTimeField(db_index=True)
    valid_until = models.DateTimeField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64)
    research_only = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta(OptimizationAppendOnlyModel.Meta):
        db_table = "portfolio_r4_monitoring_raw_fact_receipt"
        constraints = [
            models.UniqueConstraint(
                fields=("observation_id", "observation_version"),
                name="pf_r4_mon_fact_ident_uq",
            ),
            models.UniqueConstraint(
                fields=(
                    "active_decision_id",
                    "active_decision_version",
                    "policy_id",
                    "policy_version",
                    "calendar_id",
                    "calendar_version",
                    "period_id",
                ),
                name="pf_r4_mon_fact_period_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    observed_at__lte=models.F("available_at"),
                    available_at__lte=models.F("owner_recorded_at"),
                    owner_recorded_at__lt=models.F("valid_until"),
                ),
                name="pf_r4_mon_fact_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    source_owner="portfolio",
                    research_only=True,
                    must_not_use_for_decision=True,
                    must_not_publish_current=True,
                    must_not_execute=True,
                ),
                name="pf_r4_mon_fact_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("policy_id", "calendar_id", "owner_recorded_at"),
                name="pf_r4_mon_fact_pit_ix",
            )
        ]


@receiver(pre_delete, sender=PortfolioR4MonitoringRawFactReceiptModel, weak=False)
def _reject_portfolio_r4_monitoring_fact_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject all ORM deletion paths for Portfolio owner receipts."""

    raise ValidationError("Portfolio R4 monitoring raw facts cannot be deleted.")


__all__ = ["PortfolioR4MonitoringRawFactReceiptModel"]
