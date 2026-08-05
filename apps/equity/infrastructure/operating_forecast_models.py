"""Append-only ORM storage for the Equity operating-forecast ledger."""

from __future__ import annotations

from collections.abc import Iterable

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from apps.equity.domain.operating_forecast import (
    OperatingForecastLegacyHashRecipe,
    OperatingForecastLegacyHashStatus,
    OperatingForecastSourceLineageStatus,
    OperatingForecastStage,
)
from shared.infrastructure.django_append_only import AppendOnlyManager


class EquityForecastAppendOnlyModel(models.Model):
    """Reject mutation and deletion of forecast evidence records."""

    objects = AppendOnlyManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Insert a new row while rejecting updates to persisted evidence."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("Operating forecast evidence is immutable.")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject destructive deletion of operating forecast evidence."""

        raise ValidationError("Operating forecast evidence cannot be deleted.")


class OperatingForecastVersionModel(EquityForecastAppendOnlyModel):
    """Immutable header for one base/bull/bear forecast version."""

    forecast_id = models.CharField(max_length=64, primary_key=True)
    forecast_key = models.CharField(max_length=128)
    forecast_version = models.PositiveIntegerField()
    subject_code = models.CharField(max_length=80)
    industry_code = models.CharField(max_length=80)
    as_of_time = models.DateTimeField()
    target_period_end = models.DateField()
    horizon_quarters = models.PositiveSmallIntegerField()
    methodology_ref = models.CharField(max_length=255)
    created_by_ref = models.CharField(max_length=128)
    evidence_schema_version = models.PositiveSmallIntegerField(default=1, editable=False)
    source_lineage_status = models.CharField(
        max_length=24,
        choices=[(status.value, status.value) for status in OperatingForecastSourceLineageStatus],
        default=OperatingForecastSourceLineageStatus.LEGACY_UNBOUND.value,
        editable=False,
    )
    legacy_hash_recipe = models.CharField(
        max_length=24,
        choices=[(item.value, item.value) for item in OperatingForecastLegacyHashRecipe],
        default=OperatingForecastLegacyHashRecipe.UNVERIFIED.value,
        editable=False,
    )
    legacy_hash_status = models.CharField(
        max_length=16,
        choices=[(item.value, item.value) for item in OperatingForecastLegacyHashStatus],
        default=OperatingForecastLegacyHashStatus.UNVERIFIED.value,
        editable=False,
    )
    template_code = models.CharField(max_length=80, blank=True, default="")
    template_version = models.PositiveIntegerField(null=True, blank=True)
    template_content_hash = models.CharField(max_length=64, blank=True, default="")
    template_run_key = models.CharField(max_length=128, blank=True, default="")
    template_run_version = models.PositiveIntegerField(null=True, blank=True)
    template_run_content_hash = models.CharField(max_length=64, blank=True, default="")
    valuation_consumable = models.BooleanField(default=False)
    promotion_decision_id = models.CharField(max_length=64, blank=True, default="")
    content_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "equity_operating_forecast_version"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["forecast_key", "forecast_version"],
                name="equity_operating_forecast_key_version_uniq",
            ),
            models.UniqueConstraint(
                fields=["template_run_key", "template_run_version"],
                condition=models.Q(evidence_schema_version=2),
                name="equity_forecast_template_run_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(valuation_consumable=False) | ~models.Q(promotion_decision_id="")
                ),
                name="equity_forecast_valuation_promotion_required",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        evidence_schema_version=1,
                        source_lineage_status__in=(
                            OperatingForecastSourceLineageStatus.LEGACY_UNBOUND.value,
                            OperatingForecastSourceLineageStatus.LEGACY_UNVERIFIED.value,
                        ),
                        template_code="",
                        template_content_hash="",
                        template_run_content_hash="",
                        template_run_key="",
                        template_run_version__isnull=True,
                        template_version__isnull=True,
                    )
                    & (
                        models.Q(
                            legacy_hash_recipe__in=(
                                OperatingForecastLegacyHashRecipe.V1_0010_UNTYPED.value,
                                OperatingForecastLegacyHashRecipe.V1_0011_TYPED.value,
                            ),
                            legacy_hash_status=(OperatingForecastLegacyHashStatus.VERIFIED.value),
                        )
                        | models.Q(
                            legacy_hash_recipe=(OperatingForecastLegacyHashRecipe.UNVERIFIED.value),
                            legacy_hash_status=(OperatingForecastLegacyHashStatus.UNVERIFIED.value),
                            source_lineage_status=(
                                OperatingForecastSourceLineageStatus.LEGACY_UNVERIFIED.value
                            ),
                        )
                    )
                    | (
                        models.Q(
                            evidence_schema_version=2,
                            source_lineage_status=(
                                OperatingForecastSourceLineageStatus.TEMPLATE_BOUND.value
                            ),
                            template_version__isnull=False,
                            template_run_version__isnull=False,
                            legacy_hash_recipe=(
                                OperatingForecastLegacyHashRecipe.NOT_APPLICABLE.value
                            ),
                            legacy_hash_status=(
                                OperatingForecastLegacyHashStatus.NOT_APPLICABLE.value
                            ),
                            valuation_consumable=False,
                            promotion_decision_id="",
                        )
                        & ~models.Q(template_code="")
                        & ~models.Q(template_content_hash="")
                        & ~models.Q(template_run_key="")
                        & ~models.Q(template_run_content_hash="")
                    )
                ),
                name="equity_forecast_template_binding_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["subject_code", "target_period_end"],
                name="equity_fc_subject_target_idx",
            ),
            models.Index(
                fields=["industry_code", "target_period_end"],
                name="equity_fc_industry_target_idx",
            ),
            models.Index(
                fields=["valuation_consumable", "target_period_end"],
                name="eq_fc_consume_target_ix",
            ),
        ]


class OperatingForecastFactReferenceModel(EquityForecastAppendOnlyModel):
    """Captured Data Center operating PIT fact identity and payload."""

    forecast = models.ForeignKey(
        OperatingForecastVersionModel,
        on_delete=models.CASCADE,
        related_name="fact_references",
    )
    pit_fact_version_id = models.PositiveBigIntegerField()
    dataset = models.CharField(max_length=64)
    business_key = models.CharField(max_length=255)
    metric_code = models.CharField(max_length=64)
    subject_type = models.CharField(max_length=40)
    subject_code = models.CharField(max_length=80)
    effective_at = models.DateTimeField()
    available_at = models.DateTimeField()
    source_record_id = models.CharField(max_length=255)
    pit_content_hash = models.CharField(max_length=64)
    value = models.DecimalField(max_digits=50, decimal_places=12)
    unit = models.CharField(max_length=40)

    class Meta:
        db_table = "equity_operating_forecast_fact_ref"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["forecast", "pit_fact_version_id"],
                name="equity_forecast_pit_fact_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["dataset", "pit_fact_version_id"],
                name="equity_fc_fact_dataset_id_idx",
            )
        ]


class OperatingForecastAssumptionModel(EquityForecastAppendOnlyModel):
    """One typed and reconstructible input for one scenario."""

    INPUT_KIND_CHOICES = [
        ("observed_fact", "Observed fact"),
        ("human_assumption", "Human assumption"),
        ("model_inference", "Model inference"),
    ]
    SCENARIO_CHOICES = [("base", "Base"), ("bull", "Bull"), ("bear", "Bear")]

    forecast = models.ForeignKey(
        OperatingForecastVersionModel,
        on_delete=models.CASCADE,
        related_name="assumptions",
    )
    scenario = models.CharField(max_length=8, choices=SCENARIO_CHOICES)
    assumption_key = models.CharField(max_length=80)
    value = models.DecimalField(max_digits=50, decimal_places=12)
    unit = models.CharField(max_length=40)
    input_kind = models.CharField(max_length=24, choices=INPUT_KIND_CHOICES)
    rationale = models.CharField(max_length=500)
    observed_fact_version_id = models.PositiveBigIntegerField(null=True, blank=True)
    human_assumption_ref = models.CharField(max_length=255, blank=True, default="")
    model_version = models.CharField(max_length=255, blank=True, default="")
    # Preserved byte-for-byte for evidence-schema-v1 hash verification only.
    legacy_observed_metric_role = models.CharField(max_length=40, blank=True, default="")
    observed_metric_code = models.CharField(max_length=64, blank=True, default="")
    observed_fact_content_hash = models.CharField(max_length=64, blank=True, default="")
    observed_subject_type = models.CharField(max_length=40, blank=True, default="")
    observed_subject_code = models.CharField(max_length=80, blank=True, default="")
    fact_binding_complete = models.BooleanField(default=False, editable=False)

    class Meta:
        db_table = "equity_operating_forecast_assumption"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["forecast", "scenario", "assumption_key"],
                name="equity_forecast_scenario_assumption_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        input_kind="observed_fact",
                        observed_fact_version_id__isnull=False,
                        human_assumption_ref="",
                        model_version="",
                    )
                    | models.Q(
                        input_kind="human_assumption",
                        observed_fact_version_id__isnull=True,
                        model_version="",
                    )
                    & ~models.Q(human_assumption_ref="")
                    | models.Q(
                        input_kind="model_inference",
                        observed_fact_version_id__isnull=True,
                        human_assumption_ref="",
                    )
                    & ~models.Q(model_version="")
                ),
                name="equity_forecast_assumption_lineage_ck",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(fact_binding_complete=True, input_kind="observed_fact")
                        & ~models.Q(observed_metric_code="")
                        & ~models.Q(observed_fact_content_hash="")
                        & ~models.Q(observed_subject_type="")
                        & ~models.Q(observed_subject_code="")
                    )
                    | (
                        models.Q(
                            fact_binding_complete=True,
                            observed_fact_content_hash="",
                            observed_metric_code="",
                            observed_subject_code="",
                            observed_subject_type="",
                        )
                        & ~models.Q(input_kind="observed_fact")
                    )
                    | models.Q(
                        fact_binding_complete=False,
                        observed_fact_content_hash="",
                        observed_metric_code="",
                        observed_subject_code="",
                        observed_subject_type="",
                    )
                ),
                name="equity_forecast_assumption_fact_binding_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["forecast", "scenario", "input_kind"],
                name="equity_fc_assumption_kind_idx",
            )
        ]


class OperatingForecastProjectionModel(EquityForecastAppendOnlyModel):
    """Revenue, profit and derived margin output for one scenario."""

    SCENARIO_CHOICES = [("base", "Base"), ("bull", "Bull"), ("bear", "Bear")]

    forecast = models.ForeignKey(
        OperatingForecastVersionModel,
        on_delete=models.CASCADE,
        related_name="projections",
    )
    scenario = models.CharField(max_length=8, choices=SCENARIO_CHOICES)
    revenue = models.DecimalField(max_digits=50, decimal_places=12)
    net_profit = models.DecimalField(max_digits=50, decimal_places=12)
    cash_flow = models.DecimalField(max_digits=50, decimal_places=12, null=True, blank=True)
    profit_margin_percent = models.DecimalField(max_digits=50, decimal_places=12)
    currency_unit = models.CharField(max_length=40)

    class Meta:
        db_table = "equity_operating_forecast_projection"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["forecast", "scenario"],
                name="equity_forecast_projection_scenario_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(revenue__gt=0),
                name="equity_forecast_projection_revenue_gt_zero",
            ),
        ]


class OperatingForecastStageValueModel(EquityForecastAppendOnlyModel):
    """One immutable node/value for each required financial stage."""

    projection = models.ForeignKey(
        OperatingForecastProjectionModel,
        on_delete=models.CASCADE,
        related_name="stage_values",
    )
    stage = models.CharField(
        max_length=24,
        choices=[(stage.value, stage.value) for stage in OperatingForecastStage],
    )
    node_key = models.CharField(max_length=80)
    value = models.DecimalField(max_digits=50, decimal_places=12)
    unit = models.CharField(max_length=40)

    class Meta:
        db_table = "equity_operating_forecast_stage_value"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["projection", "stage"],
                name="equity_forecast_projection_stage_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["projection", "stage"],
                name="equity_fc_stage_projection_idx",
            )
        ]


class OperatingForecastSensitivityModel(EquityForecastAppendOnlyModel):
    """Externally calculated sensitivity point for one projection."""

    projection = models.ForeignKey(
        OperatingForecastProjectionModel,
        on_delete=models.CASCADE,
        related_name="sensitivities",
    )
    sensitivity_key = models.CharField(max_length=80)
    input_value = models.DecimalField(max_digits=50, decimal_places=12)
    input_unit = models.CharField(max_length=40)
    output_value = models.DecimalField(max_digits=50, decimal_places=12)
    output_unit = models.CharField(max_length=40)
    method_version = models.CharField(max_length=128)
    source_artifact_ref = models.CharField(max_length=255, blank=True, default="")
    source_artifact_hash = models.CharField(max_length=64, blank=True, default="")
    source_binding_complete = models.BooleanField(default=False, editable=False)

    class Meta:
        db_table = "equity_operating_forecast_sensitivity"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["projection", "sensitivity_key"],
                name="equity_forecast_sensitivity_key_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(source_binding_complete=True)
                        & ~models.Q(source_artifact_ref="")
                        & ~models.Q(source_artifact_hash="")
                    )
                    | models.Q(
                        source_binding_complete=False,
                        source_artifact_ref="",
                        source_artifact_hash="",
                    )
                ),
                name="equity_forecast_sensitivity_source_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["method_version"],
                name="eq_fc_sens_method_ix",
            )
        ]


class OperatingForecastEvaluationModel(EquityForecastAppendOnlyModel):
    """Quarterly actual comparison and immutable error metrics."""

    SCENARIO_CHOICES = [("base", "Base"), ("bull", "Bull"), ("bear", "Bear")]

    forecast = models.ForeignKey(
        OperatingForecastVersionModel,
        on_delete=models.PROTECT,
        related_name="evaluations",
    )
    subject_code = models.CharField(max_length=80)
    scenario = models.CharField(max_length=8, choices=SCENARIO_CHOICES)
    actual_period_end = models.DateField()
    recorded_at = models.DateTimeField()
    actual_fact_evidence = models.JSONField(default=list)
    forecast_revenue = models.DecimalField(max_digits=50, decimal_places=12)
    forecast_net_profit = models.DecimalField(max_digits=50, decimal_places=12)
    forecast_profit_margin_percent = models.DecimalField(max_digits=50, decimal_places=12)
    actual_revenue = models.DecimalField(max_digits=50, decimal_places=12)
    actual_net_profit = models.DecimalField(max_digits=50, decimal_places=12)
    actual_profit_margin_percent = models.DecimalField(max_digits=50, decimal_places=12)
    currency_unit = models.CharField(max_length=40)
    revenue_error = models.DecimalField(max_digits=50, decimal_places=12)
    revenue_absolute_error = models.DecimalField(max_digits=50, decimal_places=12)
    revenue_absolute_percentage_error = models.DecimalField(
        max_digits=50,
        decimal_places=12,
        null=True,
        blank=True,
    )
    net_profit_error = models.DecimalField(max_digits=50, decimal_places=12)
    net_profit_absolute_error = models.DecimalField(max_digits=50, decimal_places=12)
    net_profit_absolute_percentage_error = models.DecimalField(
        max_digits=50,
        decimal_places=12,
        null=True,
        blank=True,
    )
    profit_margin_error = models.DecimalField(max_digits=50, decimal_places=12)
    profit_margin_absolute_error = models.DecimalField(max_digits=50, decimal_places=12)
    content_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "equity_operating_forecast_evaluation"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["forecast", "actual_period_end", "scenario"],
                name="equity_forecast_actual_scenario_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(forecast_revenue__gt=0),
                name="equity_forecast_eval_forecast_revenue_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(actual_revenue__gt=0),
                name="equity_forecast_eval_actual_revenue_gt_zero",
            ),
        ]
        indexes = [
            models.Index(
                fields=["actual_period_end", "scenario"],
                name="eq_fc_eval_period_scen_ix",
            )
        ]


__all__ = [
    "OperatingForecastAssumptionModel",
    "OperatingForecastEvaluationModel",
    "OperatingForecastFactReferenceModel",
    "OperatingForecastProjectionModel",
    "OperatingForecastStageValueModel",
    "OperatingForecastSensitivityModel",
    "OperatingForecastVersionModel",
]
