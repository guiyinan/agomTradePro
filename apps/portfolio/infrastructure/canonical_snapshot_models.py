"""Portfolio-owned append-only snapshot and execution-feedback tables."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models


class _ImmutablePortfolioRecord(models.Model):
    """Prevent ordinary model mutation or deletion of evidentiary records."""

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Allow the initial append only."""

        if not self._state.adding:
            raise ValidationError("Portfolio evidence records are immutable")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        """Reject instance deletion of append-only evidence."""

        raise ValidationError("Portfolio evidence records are append-only")


class CanonicalPortfolioSnapshotModel(_ImmutablePortfolioRecord):
    """Canonical source-as-of cash and positions owned by Portfolio."""

    snapshot_id = models.CharField(max_length=64, primary_key=True)
    account_ref = models.CharField(max_length=128, db_index=True)
    as_of = models.DateTimeField(db_index=True)
    base_currency = models.CharField(max_length=16)
    cash_balance = models.DecimalField(max_digits=28, decimal_places=8)
    cash_version = models.CharField(max_length=128)
    positions_version = models.CharField(max_length=128)
    cash_observed_at = models.DateTimeField()
    positions_observed_at = models.DateTimeField()
    positions = models.JSONField(default=list)
    source_evidence = models.JSONField(default=list)
    content_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_canonical_snapshot"
        ordering = ["-as_of", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cash_balance__gte=0),
                name="portfolio_snapshot_cash_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["account_ref", "-as_of"],
                name="idx_pf_snap_account_asof",
            ),
            models.Index(
                fields=["cash_version", "positions_version"],
                name="idx_pf_snap_versions",
            ),
        ]


class PortfolioExecutionFeedbackModel(_ImmutablePortfolioRecord):
    """Immutable plan/order-intent/broker reconciliation feedback fact."""

    feedback_id = models.CharField(max_length=80, primary_key=True)
    portfolio_snapshot_ref = models.CharField(max_length=64, db_index=True)
    transition_plan_ref = models.CharField(max_length=64, db_index=True)
    order_intent_ref = models.CharField(max_length=64, db_index=True)
    planning_policy_version = models.CharField(max_length=128)
    asset_code = models.CharField(max_length=32, db_index=True)
    side = models.CharField(max_length=8, choices=[("buy", "Buy"), ("sell", "Sell")])
    planned_quantity = models.DecimalField(max_digits=28, decimal_places=8)
    planned_reference_price = models.DecimalField(max_digits=28, decimal_places=8)
    planned_estimated_fee = models.DecimalField(max_digits=28, decimal_places=8)
    client_order_ref = models.CharField(max_length=128, db_index=True)
    broker_order_ref = models.CharField(max_length=128, blank=True, default="")
    order_events = models.JSONField(default=list)
    fills = models.JSONField(default=list)
    reconciliation_ref = models.CharField(max_length=128, db_index=True)
    reconciliation_observed_at = models.DateTimeField(db_index=True)
    filled_quantity = models.DecimalField(max_digits=28, decimal_places=8)
    average_fill_price = models.DecimalField(
        max_digits=28,
        decimal_places=8,
        null=True,
        blank=True,
    )
    actual_fee = models.DecimalField(max_digits=28, decimal_places=8)
    fee_variance = models.DecimalField(max_digits=28, decimal_places=8)
    realized_slippage = models.DecimalField(max_digits=28, decimal_places=8)
    fill_rate = models.DecimalField(max_digits=18, decimal_places=12)
    rejected = models.BooleanField(default=False, db_index=True)
    rejection_code = models.CharField(max_length=64, blank=True, default="")
    rejection_reason = models.TextField(blank=True, default="")
    constraint_deviations = models.JSONField(default=list)
    source_evidence_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_execution_feedback"
        ordering = ["-reconciliation_observed_at", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(planned_quantity__gt=0),
                name="portfolio_feedback_planned_qty_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(planned_reference_price__gt=0),
                name="portfolio_feedback_planned_price_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(planned_estimated_fee__gte=0),
                name="portfolio_feedback_planned_fee_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(filled_quantity__gte=0),
                name="portfolio_feedback_filled_qty_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(actual_fee__gte=0),
                name="portfolio_feedback_actual_fee_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(fill_rate__gte=0),
                name="portfolio_feedback_fill_rate_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["transition_plan_ref", "order_intent_ref"],
                name="idx_pf_feedback_plan_intent",
            ),
            models.Index(
                fields=["client_order_ref", "reconciliation_ref"],
                name="idx_pf_feedback_broker_refs",
            ),
        ]


__all__ = ["CanonicalPortfolioSnapshotModel", "PortfolioExecutionFeedbackModel"]
