"""Append-only forecast ledger models."""

from django.core.exceptions import ValidationError
from django.db import models


class ForecastLedgerEntry(models.Model):
    IMMUTABLE_FIELDS = (
        "signal_id",
        "published_at",
        "direction",
        "asset_code",
        "horizon_end",
        "benchmark_asset",
        "probability",
        "invalidation_rule_version",
        "decision_snapshot_id",
        "pit_manifest_id",
        "strategy_version",
        "model_version",
        "prompt_version",
        "source",
        "regime",
    )
    entry_id = models.CharField(max_length=64, primary_key=True)
    signal = models.OneToOneField(
        "signal.InvestmentSignalModel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="forecast_entry",
    )
    published_at = models.DateTimeField(db_index=True)
    direction = models.CharField(max_length=10)
    asset_code = models.CharField(max_length=32, db_index=True)
    horizon_end = models.DateTimeField(db_index=True)
    benchmark_asset = models.CharField(max_length=32)
    probability = models.FloatField()
    invalidation_rule_version = models.CharField(max_length=64)
    decision_snapshot_id = models.CharField(max_length=64)
    pit_manifest_id = models.CharField(max_length=64)
    strategy_version = models.CharField(max_length=64, blank=True)
    model_version = models.CharField(max_length=64, blank=True)
    prompt_version = models.CharField(max_length=64, blank=True)
    source = models.CharField(max_length=64, db_index=True)
    regime = models.CharField(max_length=32, blank=True, db_index=True)
    status = models.CharField(max_length=24, default="open", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "signal_forecast_ledger_entry"
        indexes = [models.Index(fields=["source", "published_at"])]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk:
            original = type(self)._default_manager.filter(pk=self.pk).first()
            if original and any(
                getattr(original, field) != getattr(self, field)
                for field in self.IMMUTABLE_FIELDS
            ):
                raise ValidationError("Forecast publication evidence is immutable.")
        return super().save(*args, **kwargs)


class ForecastEvaluation(models.Model):
    evaluation_id = models.CharField(max_length=64, primary_key=True)
    entry = models.ForeignKey(ForecastLedgerEntry, on_delete=models.CASCADE, related_name="evaluations")
    checked_at = models.DateTimeField(db_index=True)
    data_version_ids = models.JSONField(default=list)
    conditions = models.JSONField(default=list)
    triggered = models.BooleanField(default=False)
    first_triggered_at = models.DateTimeField(null=True, blank=True)
    status_transition = models.CharField(max_length=32, blank=True)
    missing_reason = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "signal_forecast_evaluation"
        ordering = ["checked_at"]
        indexes = [models.Index(fields=["entry", "checked_at"])]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("ForecastEvaluation is append-only.")
        return super().save(*args, **kwargs)


class ForecastOutcome(models.Model):
    entry = models.OneToOneField(
        ForecastLedgerEntry, primary_key=True, on_delete=models.PROTECT, related_name="outcome"
    )
    outcome_type = models.CharField(max_length=24)
    finalized_at = models.DateTimeField()
    asset_return = models.FloatField(null=True, blank=True)
    benchmark_return = models.FloatField(null=True, blank=True)
    excess_return = models.FloatField(null=True, blank=True)
    hit = models.BooleanField(null=True, blank=True)
    brier_score = models.FloatField(null=True, blank=True)
    evidence = models.JSONField(default=dict)

    class Meta:
        db_table = "signal_forecast_outcome"

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("ForecastOutcome is immutable.")
        return super().save(*args, **kwargs)
