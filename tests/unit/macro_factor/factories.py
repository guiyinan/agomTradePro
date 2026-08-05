"""Typed test builders for complete R3 external research evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from apps.macro_factor.domain.entities import (
    ComparisonOperator,
    EvaluationMetrics,
    ExternalLassoSelectionEvidence,
    ExternalMacroFactorResearchResult,
    FactorLifecycleStatus,
    FactorOutputRole,
    FactorWeight,
    FactorWeightVersion,
    InvalidationRule,
    MacroTargetDefinition,
    MacroTargetFamily,
    ModelEvaluationEvidence,
    PITDatasetSlice,
    PITManifestEvidence,
    ProxyAssetDefinition,
    ProxyAssetKind,
    ReproducibilityEvidence,
    RetirementPolicy,
    SampleSegment,
    SampleWindow,
    TemporalSplitSpec,
    WalkForwardFold,
    calculate_factor_weight_hash,
)

ASSESSED_AT = datetime(2026, 7, 3, 9, tzinfo=UTC)


def complete_manifest() -> PITManifestEvidence:
    """Return complete, verified PIT evidence for one target and two proxies."""

    return PITManifestEvidence(
        manifest_id="pit-r3-growth-v1",
        manifest_hash="a" * 64,
        as_of_time=datetime(2026, 6, 30, 16, tzinfo=UTC),
        knowledge_scope="public",
        calendar_version="cn-trading-calendar-v3",
        slices=(
            PITDatasetSlice("macro.vintage", "CN_GROWTH_TARGET", (101, 102)),
            PITDatasetSlice("market.proxy.etf", "ETF_CREDIT", (201, 202)),
            PITDatasetSlice("market.proxy.future", "FUTURE_COPPER", (301, 302)),
        ),
        coverage_ratio=Decimal("1"),
        missing_count=0,
        estimated_count=0,
        unknown_count=0,
        is_verified=True,
    )


def _split() -> TemporalSplitSpec:
    return TemporalSplitSpec(
        policy_version="macro-factor-split-v1",
        training=SampleWindow(date(2015, 1, 1), date(2019, 12, 31)),
        validation=SampleWindow(date(2020, 1, 6), date(2021, 12, 31)),
        out_of_sample=SampleWindow(date(2022, 1, 6), date(2024, 12, 31)),
        walk_forward_folds=(
            WalkForwardFold(
                fold_id="wf-1",
                training=SampleWindow(date(2015, 1, 1), date(2018, 12, 31)),
                validation=SampleWindow(date(2019, 1, 6), date(2019, 12, 31)),
                out_of_sample=SampleWindow(date(2020, 1, 6), date(2020, 12, 31)),
            ),
            WalkForwardFold(
                fold_id="wf-2",
                training=SampleWindow(date(2015, 1, 1), date(2019, 12, 31)),
                validation=SampleWindow(date(2020, 1, 6), date(2020, 12, 31)),
                out_of_sample=SampleWindow(date(2021, 1, 6), date(2021, 12, 31)),
            ),
        ),
        embargo_days=5,
    )


def _metric(segment: SampleSegment, suffix: str) -> EvaluationMetrics:
    return EvaluationMetrics(
        segment=segment,
        sample_count=240,
        r_squared=Decimal(f"0.{suffix}2"),
        adjusted_r_squared=Decimal(f"0.{suffix}0"),
        information_coefficient=Decimal(f"0.{suffix}"),
        stability_score=Decimal("0.78"),
        turnover=Decimal("0.24"),
        transaction_cost=Decimal("0.003"),
    )


def complete_result() -> ExternalMacroFactorResearchResult:
    """Return structurally complete, externally calculated R3 evidence."""

    weights = (
        FactorWeight(
            asset_code="ETF_CREDIT",
            lasso_coefficient=Decimal("0.62"),
            factor_weight=Decimal("0.60"),
        ),
        FactorWeight(
            asset_code="FUTURE_COPPER",
            lasso_coefficient=Decimal("0.38"),
            factor_weight=Decimal("0.40"),
        ),
    )
    calculated_at = datetime(2026, 7, 2, 10, tzinfo=UTC)
    weight_hash = calculate_factor_weight_hash(
        factor_version="macro-growth-v1",
        calculated_at=calculated_at,
        weights=weights,
    )
    return ExternalMacroFactorResearchResult(
        result_id="macro-factor-result-growth-v1",
        factor_version="macro-growth-v1",
        target=MacroTargetDefinition(
            target_code="growth_nowcast_1m",
            family=MacroTargetFamily.GROWTH,
            output_role=FactorOutputRole.FORWARD_EXPECTATION,
            dataset_key="macro.vintage",
            business_key="CN_GROWTH_TARGET",
            unit="index",
            frequency="monthly",
            transformation_version="yoy-standardization-v2",
            horizon_periods=1,
            horizon_unit="month",
        ),
        candidates=(
            ProxyAssetDefinition(
                asset_code="ETF_CREDIT",
                dataset_key="market.proxy.etf",
                business_key="ETF_CREDIT",
                kind=ProxyAssetKind.ETF,
                frequency="daily",
                transformation_version="close-return-v2",
            ),
            ProxyAssetDefinition(
                asset_code="FUTURE_COPPER",
                dataset_key="market.proxy.future",
                business_key="FUTURE_COPPER",
                kind=ProxyAssetKind.CONTINUOUS_FUTURE,
                frequency="daily",
                transformation_version="excess-return-v1",
                continuous_roll_policy_version="cn-futures-roll-v4",
            ),
        ),
        pit_manifest_id="pit-r3-growth-v1",
        pit_manifest_hash="a" * 64,
        reproducibility=ReproducibilityEvidence(
            code_version="git:0123456789abcdef",
            dependency_lock_hash="b" * 64,
            parameter_version="macro-growth-params-v1",
            parameter_hash="c" * 64,
        ),
        split=_split(),
        selection=ExternalLassoSelectionEvidence(
            evidence_id="external-lasso-selection-v1",
            producer_ref="research-runner:trial-42",
            produced_at=datetime(2026, 7, 1, 10, tzinfo=UTC),
            computation_origin="external_precomputed",
            estimator="lasso",
            validation_method="nested_cv",
            inner_fold_count=3,
            outer_fold_count=2,
            alpha_grid=(Decimal("0.01"), Decimal("0.1"), Decimal("1")),
            selected_alpha=Decimal("0.1"),
            optimization_metric="validation_information_coefficient",
            coefficient_path_hash="d" * 64,
            selection_report_hash="e" * 64,
            selected_asset_codes=("ETF_CREDIT", "FUTURE_COPPER"),
        ),
        evaluation=ModelEvaluationEvidence(
            in_sample=_metric(SampleSegment.IN_SAMPLE, "4"),
            validation=_metric(SampleSegment.VALIDATION, "3"),
            out_of_sample=_metric(SampleSegment.OUT_OF_SAMPLE, "2"),
            benchmark_version="historical-mean-benchmark-v1",
            cost_model_version="portfolio-cost-model-v3",
            bic=Decimal("412.75"),
            statistical_significance_summary=(
                "Selected coefficients remain significant in the external nested-CV report."
            ),
            statistical_significance_evidence_ref="research-runner:trial-42:significance-v1",
            economic_interpretation=(
                "Credit and copper proxies jointly represent forward growth conditions."
            ),
            evidence_hash="f" * 64,
        ),
        weights=FactorWeightVersion(
            factor_version="macro-growth-v1",
            calculated_at=calculated_at,
            weights=weights,
            weight_hash=weight_hash,
        ),
        retirement_policy=RetirementPolicy(
            policy_version="macro-factor-retirement-v1",
            owner_ref="macro-factor-research-owner",
            evaluation_frequency="monthly",
            retire_on_any=True,
            rules=(
                InvalidationRule(
                    rule_id="oos-r2-floor",
                    metric_name="out_of_sample.r_squared",
                    operator=ComparisonOperator.LT,
                    threshold=Decimal("0.05"),
                    consecutive_windows=2,
                    observation_window="rolling-12m",
                    rationale="Retire after persistent OOS explanatory-power loss.",
                ),
            ),
        ),
        lifecycle_status=FactorLifecycleStatus.RESEARCH_ONLY,
        retirement_evidence=None,
        research_only=True,
        must_not_use_for_decision=True,
    )


def with_manifest_hash(
    result: ExternalMacroFactorResearchResult,
    manifest_hash: str,
) -> ExternalMacroFactorResearchResult:
    """Return a result that references another manifest hash."""

    return replace(result, pit_manifest_hash=manifest_hash)
