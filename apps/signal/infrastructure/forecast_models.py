"""Append-only forecast ledger models."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
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
        "scenario_revision_id",
        "scenario_set_revision_id",
        "subjective_probability",
        "subjective_probability_source_version",
        "model_probability",
        "model_probability_source_version",
        "model_promotion_decision_id",
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
    scenario_revision_id = models.UUIDField(null=True, blank=True)
    scenario_set_revision_id = models.UUIDField(null=True, blank=True)
    subjective_probability = models.DecimalField(
        max_digits=18,
        decimal_places=12,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    subjective_probability_source_version = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )
    model_probability = models.DecimalField(
        max_digits=18,
        decimal_places=12,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    model_probability_source_version = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )
    model_promotion_decision_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )
    status = models.CharField(max_length=24, default="open", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "signal_forecast_ledger_entry"
        indexes = [
            models.Index(fields=["source", "published_at"]),
            models.Index(
                fields=["scenario_revision_id", "published_at"],
                name="signal_scn_rev_pub_idx",
            ),
            models.Index(
                fields=["scenario_set_revision_id", "published_at"],
                name="signal_scn_set_pub_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        scenario_revision_id__isnull=True,
                        scenario_set_revision_id__isnull=True,
                        subjective_probability__isnull=True,
                        subjective_probability_source_version="",
                        model_probability__isnull=True,
                        model_probability_source_version="",
                        model_promotion_decision_id="",
                    )
                    | (
                        models.Q(
                            scenario_revision_id__isnull=False,
                            subjective_probability__isnull=False,
                        )
                        & ~models.Q(subjective_probability_source_version="")
                    )
                ),
                name="signal_scn_binding_complete_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        model_probability__isnull=True,
                        model_probability_source_version="",
                        model_promotion_decision_id="",
                    )
                    | (
                        models.Q(model_probability__isnull=False)
                        & ~models.Q(model_probability_source_version="")
                        & ~models.Q(model_promotion_decision_id="")
                    )
                ),
                name="signal_scn_model_complete_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(subjective_probability__isnull=True)
                    | models.Q(
                        subjective_probability__gte=0,
                        subjective_probability__lte=1,
                    )
                ),
                name="signal_scn_subjective_range_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(model_probability__isnull=True)
                    | models.Q(model_probability__gte=0, model_probability__lte=1)
                ),
                name="signal_scn_model_range_ck",
            ),
        ]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk:
            original = type(self)._default_manager.filter(pk=self.pk).first()
            if original and any(
                getattr(original, field) != getattr(self, field) for field in self.IMMUTABLE_FIELDS
            ):
                raise ValidationError("Forecast publication evidence is immutable.")
        return super().save(*args, **kwargs)


class ForecastEvaluation(models.Model):
    evaluation_id = models.CharField(max_length=64, primary_key=True)
    entry = models.ForeignKey(
        ForecastLedgerEntry, on_delete=models.CASCADE, related_name="evaluations"
    )
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
    scenario_realized = models.BooleanField(null=True, blank=True)
    subjective_brier_score = models.FloatField(null=True, blank=True)
    model_brier_score = models.FloatField(null=True, blank=True)
    evidence = models.JSONField(default=dict)

    class Meta:
        db_table = "signal_forecast_outcome"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(subjective_brier_score__isnull=True)
                    | models.Q(
                        subjective_brier_score__gte=0,
                        subjective_brier_score__lte=1,
                    )
                ),
                name="signal_scn_subjective_brier_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(model_brier_score__isnull=True)
                    | models.Q(model_brier_score__gte=0, model_brier_score__lte=1)
                ),
                name="signal_scn_model_brier_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        scenario_realized__isnull=True,
                        subjective_brier_score__isnull=True,
                        model_brier_score__isnull=True,
                    )
                    | models.Q(
                        scenario_realized__isnull=False,
                        subjective_brier_score__isnull=False,
                    )
                ),
                name="signal_scn_outcome_score_ck",
            ),
        ]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("ForecastOutcome is immutable.")
        return super().save(*args, **kwargs)
