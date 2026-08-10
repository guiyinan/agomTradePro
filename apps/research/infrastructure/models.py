"""ORM models for immutable experiment evidence."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ResearchExperiment(models.Model):
    experiment_id = models.CharField(max_length=64, primary_key=True)
    question = models.TextField()
    hypothesis = models.TextField()
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=32, default="draft", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "research_experiment"


class MultipleTestFamily(models.Model):
    family_id = models.CharField(max_length=64, primary_key=True)
    experiment = models.ForeignKey(
        ResearchExperiment, on_delete=models.CASCADE, related_name="families"
    )
    planned_trial_count = models.PositiveIntegerField()
    fdr_threshold = models.FloatField(default=0.05)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_multiple_test_family"


class ExperimentTrial(models.Model):
    IMMUTABLE_FIELDS = (
        "experiment_id",
        "family_id",
        "pit_manifest_id",
        "backtest_id",
        "backtest_trust_status",
        "code_commit",
        "dependency_lock_hash",
        "engine_version",
        "parameters",
        "parameter_hash",
        "random_seed",
        "benchmark_spec",
        "cost_spec",
        "slippage_spec",
        "universe_spec",
    )

    trial_id = models.CharField(max_length=64, primary_key=True)
    experiment = models.ForeignKey(
        ResearchExperiment, on_delete=models.CASCADE, related_name="trials"
    )
    family = models.ForeignKey(MultipleTestFamily, on_delete=models.PROTECT, related_name="trials")
    status = models.CharField(max_length=32, default="draft", db_index=True)
    pit_manifest_id = models.CharField(max_length=64, db_index=True)
    backtest_id = models.PositiveBigIntegerField(null=True, blank=True)
    backtest_trust_status = models.CharField(max_length=24, default="exploratory")
    code_commit = models.CharField(max_length=64)
    dependency_lock_hash = models.CharField(max_length=64)
    engine_version = models.CharField(max_length=64)
    parameters = models.JSONField(default=dict)
    parameter_hash = models.CharField(max_length=64)
    random_seed = models.BigIntegerField()
    benchmark_spec = models.JSONField(default=dict)
    cost_spec = models.JSONField(default=dict)
    slippage_spec = models.JSONField(default=dict)
    universe_spec = models.JSONField(default=dict)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_experiment_trial"
        indexes = [models.Index(fields=["family", "status"])]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk:
            original = type(self)._default_manager.filter(pk=self.pk).first()
            if original and original.status != "draft":
                changed = [
                    name
                    for name in self.IMMUTABLE_FIELDS
                    if getattr(original, name) != getattr(self, name)
                ]
                if changed:
                    raise ValidationError(
                        f"Started trial evidence is immutable: {', '.join(changed)}"
                    )
        return super().save(*args, **kwargs)


class DatasetSplitSpec(models.Model):
    trial = models.OneToOneField(
        ExperimentTrial, primary_key=True, on_delete=models.CASCADE, related_name="split_spec"
    )
    training_window = models.JSONField(default=dict)
    validation_window = models.JSONField(default=dict)
    out_of_sample_window = models.JSONField(default=dict)
    walk_forward_windows = models.JSONField(default=list)
    embargo_days = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "research_dataset_split_spec"

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("DatasetSplitSpec is immutable after creation.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValidationError("DatasetSplitSpec cannot be deleted.")


class MetricObservation(models.Model):
    trial = models.ForeignKey(ExperimentTrial, on_delete=models.CASCADE, related_name="metrics")
    metric_name = models.CharField(max_length=64)
    value = models.FloatField()
    sample_count = models.PositiveIntegerField()
    confidence_interval_low = models.FloatField(null=True, blank=True)
    confidence_interval_high = models.FloatField(null=True, blank=True)
    p_value = models.FloatField(null=True, blank=True)
    q_value = models.FloatField(null=True, blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_metric_observation"
        constraints = [
            models.UniqueConstraint(
                fields=["trial", "metric_name"], name="research_trial_metric_uniq"
            )
        ]

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk:
            original = type(self)._default_manager.filter(pk=self.pk).first()
            immutable_fields = (
                "trial_id",
                "metric_name",
                "value",
                "sample_count",
                "confidence_interval_low",
                "confidence_interval_high",
                "p_value",
                "metadata",
            )
            if original and any(
                getattr(original, field) != getattr(self, field) for field in immutable_fields
            ):
                raise ValidationError("MetricObservation evidence is immutable.")
        return super().save(*args, **kwargs)


class PromotionDecision(models.Model):
    decision_id = models.CharField(max_length=64, primary_key=True)
    trial = models.OneToOneField(
        ExperimentTrial, on_delete=models.PROTECT, related_name="promotion_decision"
    )
    decision = models.CharField(max_length=16)
    evidence = models.JSONField(default=dict)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_promotion_decision"

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("PromotionDecision is immutable.")
        return super().save(*args, **kwargs)


from apps.research.infrastructure.r1_forecast_promotion_models import (  # noqa: E402,F401
    R1ForecastPromotionDecisionBundleModel,
    R1ForecastPromotionPolicyModel,
    R1PromotionDecisionReceiptModel,
    R1PromotionLifecycleEventBundleModel,
    R1PromotionLifecycleReceiptModel,
)
from apps.research.infrastructure.r2_market_structure_promotion_models import (  # noqa: E402,F401
    R2MarketStructurePromotionDecisionModel,
    R2MarketStructurePromotionLifecycleEventModel,
    R2MarketStructurePromotionPolicyModel,
)
from apps.research.infrastructure.r2_market_structure_trial_monitoring_models import (  # noqa: E402,F401
    R2ExplanatoryTrialAssessmentLedgerModel,
    R2MonitoringAssessmentLedgerModel,
    R2MonitoringAuditSnapshotModel,
    R2MonitoringObservationLedgerModel,
)
from apps.research.infrastructure.r3_macro_factor_runner_spec_models import (  # noqa: E402,F401
    R3MacroFactorRunnerSpecModel,
)
from apps.research.infrastructure.r4_promotion_models import (  # noqa: E402,F401
    R4PromotionDecisionBundleModel,
    R4PromotionDecisionReceiptModel,
    R4PromotionLifecycleAuthorizationReceiptModel,
    R4PromotionLifecycleEventModel,
    R4PromotionPolicyModel,
)
from apps.research.infrastructure.r4_promotion_monitoring_models import (  # noqa: E402,F401
    R4MonitoringAssessmentLedgerModel,
    R4MonitoringAuditSnapshotModel,
    R4MonitoringObservationLedgerModel,
)
from apps.research.infrastructure.r5_relative_value_monitoring_models import (  # noqa: E402,F401
    R5MonitoringAssessmentLedgerModel,
    R5MonitoringAuditSnapshotModel,
    R5MonitoringObservationLedgerModel,
)
from apps.research.infrastructure.r5_relative_value_promotion_models import (  # noqa: E402,F401
    R5PromotionArtifactModel,
    R5PromotionDecisionAuthorizationModel,
    R5PromotionDecisionBundleModel,
    R5PromotionLifecycleAuthorizationModel,
    R5PromotionLifecycleEventModel,
)
from apps.research.infrastructure.r7_research_result_lifecycle_models import (  # noqa: E402,F401
    R7ResearchResultAuditSnapshotModel,
    R7ResultLifecycleAuthorizationModel,
    R7ResultLifecycleEventModel,
)
from apps.research.infrastructure.r7_research_result_models import (  # noqa: E402,F401
    R7ResearchResultModel,
)
from apps.research.infrastructure.r7_sample_policy_models import (  # noqa: E402,F401
    R7SamplePolicyApprovalReceiptModel,
    R7SamplePolicyModel,
)
from apps.research.infrastructure.scenario_review_reminder_models import (  # noqa: E402,F401
    ScenarioReviewReminderEventModel,
    ScenarioReviewReminderModel,
)
from apps.research.infrastructure.state_model_activation_models import (  # noqa: E402,F401
    R6ActivationAuditSnapshotModel,
    R6ActivationAuthorizationModel,
    R6ActivationEventModel,
    R6ActivationStreamCommitModel,
)
from apps.research.infrastructure.state_model_monitoring_models import (  # noqa: E402,F401
    R6MonitoringAssessmentModel,
    R6MonitoringObservationModel,
)
from apps.research.infrastructure.state_model_qualification_models import (  # noqa: E402,F401
    R6QualificationAssessmentModel,
    R6QualificationLifecycleAuthorizationModel,
    R6QualificationLifecycleEventModel,
)
