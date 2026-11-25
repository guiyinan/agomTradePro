"""Financial statement fact ORM definitions for exact and legacy values."""

from django.db import models

from .financial_numeric_storage import IsFinancialNumericJSONObject as _IsFinancialNumericJSONObject


class LegacyFinancialFactManager(models.Manager["FinancialFactModel"]):
    """Keep exact-only facts out of callers using the four-place legacy schema."""

    def get_queryset(self) -> models.QuerySet["FinancialFactModel"]:
        """Select only revisions readable on both the old and expanded schemas."""
        return super().get_queryset().filter(value__isnull=False)


class FinancialFactModel(models.Model):
    """Financial statement fact (single line-item per row).

    Natural key: (asset_code, period_end, period_type, metric_code, source).
    """

    objects = LegacyFinancialFactManager()

    PERIOD_TYPE_CHOICES = [
        ("annual", "Annual"),
        ("semi_annual", "Semi-Annual"),
        ("quarterly", "Quarterly"),
        ("ttm", "TTM"),
    ]

    asset_code = models.CharField(max_length=20, db_index=True)
    period_end = models.DateField(db_index=True, help_text="Period end date (e.g. 2024-12-31)")
    period_type = models.CharField(max_length=15, choices=PERIOD_TYPE_CHOICES)
    metric_code = models.CharField(
        max_length=60,
        db_index=True,
        help_text="Metric identifier (e.g. revenue, net_profit, total_assets)",
    )
    value = models.DecimalField(max_digits=28, decimal_places=4, null=True, blank=True)
    numeric_schema = models.CharField(
        max_length=40, default="legacy-decimal-v1", db_default="legacy-decimal-v1"
    )
    exact_value_text = models.CharField(max_length=128, null=True, blank=True)
    numeric_evidence = models.JSONField(null=True, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    source = models.CharField(max_length=50)
    report_date = models.DateField(null=True, blank=True, help_text="Date report was published")
    fetched_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(default=dict, blank=True)
    decision_evidence = models.JSONField(default=dict, blank=True)
    contract_version = models.CharField(max_length=40, default="1.0")
    schema_version = models.CharField(max_length=40, default="1.0")
    source_record_id = models.CharField(max_length=200, blank=True)
    raw_payload_hash = models.CharField(max_length=128, blank=True, db_index=True)
    quality_status = models.CharField(max_length=40, default="accepted", db_index=True)
    revision_number = models.PositiveSmallIntegerField(default=1)
    ingested_run_id = models.UUIDField(null=True, blank=True, db_index=True)
    announced_at = models.DateTimeField(null=True, blank=True, db_index=True)
    available_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "data_center_financial_fact"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        numeric_schema="legacy-decimal-v1",
                        value__isnull=False,
                        exact_value_text__isnull=True,
                        numeric_evidence__isnull=True,
                    )
                    | (
                        models.Q(
                            numeric_schema="native-decimal-v2",
                            value__isnull=True,
                            exact_value_text__isnull=False,
                            numeric_evidence__isnull=False,
                        )
                        & ~models.Q(exact_value_text="")
                        & ~models.Q(numeric_evidence={})
                        & models.Q(_IsFinancialNumericJSONObject(models.F("numeric_evidence")))
                    )
                ),
                name="dc_financial_numeric_state_valid",
            )
        ]
        unique_together = [
            ("asset_code", "period_end", "period_type", "metric_code", "source", "revision_number")
        ]
        indexes = [
            models.Index(fields=["asset_code", "period_end"]),
            models.Index(fields=["metric_code"]),
        ]
        ordering = ["-period_end"]
        verbose_name = "Financial Fact"
        verbose_name_plural = "Financial Facts"

    def __str__(self) -> str:
        """Show the active numeric representation without a rounded shadow value."""

        rendered = (
            self.exact_value_text if self.numeric_schema == "native-decimal-v2" else self.value
        )
        return f"{self.asset_code} {self.period_end} {self.metric_code}={rendered}"
