"""Append-only Portfolio owner row for raw R8 monitoring feedback."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.portfolio.infrastructure.optimization_research_models import (
    OptimizationAppendOnlyModel,
)


class PortfolioR8MonitoringFeedbackReceiptModel(OptimizationAppendOnlyModel):
    """Immutable complete raw feedback definition and source receipt."""

    feedback_id = models.CharField(max_length=192)
    feedback_version = models.CharField(max_length=128)
    feedback_hash = models.CharField(max_length=64, unique=True)
    definition_version = models.CharField(max_length=128)
    definition_hash = models.CharField(max_length=64, unique=True)
    source_receipt_id = models.CharField(max_length=192)
    source_receipt_version = models.CharField(max_length=128)
    source_receipt_hash = models.CharField(max_length=64, unique=True)
    source_owner = models.CharField(max_length=32)
    result_id = models.CharField(max_length=192)
    result_version = models.CharField(max_length=128)
    result_hash = models.CharField(max_length=64)
    receipt_id = models.CharField(max_length=192)
    receipt_version = models.CharField(max_length=128)
    receipt_hash = models.CharField(max_length=64)
    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=128)
    calendar_hash = models.CharField(max_length=64)
    period_id = models.CharField(max_length=192)
    period_start_at = models.DateTimeField()
    period_end_at = models.DateTimeField()
    source_observed_at = models.DateTimeField()
    source_available_at = models.DateTimeField()
    source_valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    net_realized_pnl_after_flows = models.DecimalField(max_digits=38, decimal_places=12)
    opening_portfolio_value = models.DecimalField(max_digits=38, decimal_places=12)
    maximum_peak_to_trough_loss = models.DecimalField(max_digits=38, decimal_places=12)
    peak_portfolio_value = models.DecimalField(max_digits=38, decimal_places=12)
    absolute_traded_notional = models.DecimalField(max_digits=38, decimal_places=12)
    average_portfolio_value = models.DecimalField(max_digits=38, decimal_places=12)
    liquidity_consumed_notional = models.DecimalField(max_digits=38, decimal_places=12)
    liquidity_budget_notional = models.DecimalField(max_digits=38, decimal_places=12)
    position_exposure_notional = models.DecimalField(max_digits=38, decimal_places=12)
    capacity_limit_notional = models.DecimalField(max_digits=38, decimal_places=12)
    constraint_breach_count = models.PositiveBigIntegerField()
    constraint_evaluation_count = models.PositiveBigIntegerField()
    changed_label_count = models.PositiveBigIntegerField()
    comparable_label_count = models.PositiveBigIntegerField()
    aggregate_drift_distance = models.DecimalField(max_digits=38, decimal_places=12)
    drift_normalization_bound = models.DecimalField(max_digits=38, decimal_places=12)
    member_manifest_hash = models.CharField(max_length=64)
    raw_fact_manifest_hash = models.CharField(max_length=64)
    definition_payload = models.JSONField()
    source_payload = models.JSONField()
    ledger_header_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)

    class Meta(OptimizationAppendOnlyModel.Meta):
        db_table = "portfolio_r8_monitoring_feedback_receipt"
        indexes = [
            models.Index(
                fields=("result_id", "calendar_id", "period_id", "ledger_recorded_at"),
                name="port_r8_feed_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("feedback_id", "feedback_version"),
                name="port_r8_feed_id_uq",
            ),
            models.UniqueConstraint(
                fields=("source_receipt_id", "source_receipt_version"),
                name="port_r8_feed_source_uq",
            ),
            models.UniqueConstraint(
                fields=("result_id", "calendar_id", "period_id"),
                name="port_r8_feed_period_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(period_start_at__lt=models.F("period_end_at"))
                    & models.Q(source_observed_at__gte=models.F("period_start_at"))
                    & models.Q(source_observed_at__lte=models.F("period_end_at"))
                    & models.Q(source_available_at__gte=models.F("source_observed_at"))
                    & models.Q(source_available_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("source_valid_until"))
                ),
                name="port_r8_feed_clock_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(opening_portfolio_value__gt=0)
                    & models.Q(
                        net_realized_pnl_after_flows__gte=-models.F("opening_portfolio_value")
                    )
                    & models.Q(maximum_peak_to_trough_loss__gte=0)
                    & models.Q(peak_portfolio_value__gt=0)
                    & models.Q(maximum_peak_to_trough_loss__lte=models.F("peak_portfolio_value"))
                    & models.Q(absolute_traded_notional__gte=0)
                    & models.Q(average_portfolio_value__gt=0)
                    & models.Q(liquidity_consumed_notional__gte=0)
                    & models.Q(liquidity_budget_notional__gt=0)
                    & models.Q(position_exposure_notional__gte=0)
                    & models.Q(capacity_limit_notional__gt=0)
                    & models.Q(constraint_evaluation_count__gt=0)
                    & models.Q(constraint_breach_count__lte=models.F("constraint_evaluation_count"))
                    & models.Q(comparable_label_count__gt=0)
                    & models.Q(changed_label_count__lte=models.F("comparable_label_count"))
                    & models.Q(aggregate_drift_distance__gte=0)
                    & models.Q(drift_normalization_bound__gt=0)
                    & models.Q(aggregate_drift_distance__lte=models.F("drift_normalization_bound"))
                ),
                name="port_r8_feed_raw_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    feedback_version="portfolio-r8-monitoring-feedback.v1",
                    definition_version="portfolio-r8-monitoring-feedback-definition.v1",
                    source_receipt_version="portfolio-r8-monitoring-feedback-source.v1",
                    source_owner="portfolio",
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="port_r8_feed_safe_ck",
            ),
        ]


@receiver(
    pre_delete,
    sender=PortfolioR8MonitoringFeedbackReceiptModel,
    dispatch_uid="reject_portfolio_r8_monitoring_feedback_delete",
    weak=False,
)
def _reject_portfolio_r8_monitoring_feedback_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    del sender, instance, using, origin, kwargs
    raise ValidationError("Portfolio R8 monitoring feedback cannot be deleted.")


__all__ = ["PortfolioR8MonitoringFeedbackReceiptModel"]
