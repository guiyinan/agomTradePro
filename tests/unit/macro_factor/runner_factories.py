"""In-memory fixtures for the no-data R3 reproducible-runner contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from apps.macro_factor.domain.entities import (
    ExternalMacroFactorResearchResult,
    FactorOutputRole,
    ReproducibilityEvidence,
    RetirementEvidence,
)
from apps.macro_factor.domain.reproducible_runner import (
    ExternalAlphaScore,
    ExternalDatedFactorOutput,
    ExternalFoldPrediction,
    ExternalInnerFoldScore,
    ExternalNestedCVArtifact,
    ExternalOuterFoldSelectionEvidence,
    ExternalProxyCoefficient,
    FixedFMPDefinition,
    FixedFMPWeight,
    InnerTemporalFoldPlan,
    MacroFactorRunnerSpec,
    NestedTemporalCVPlan,
    OptimizationDirection,
    OuterTemporalFoldPlan,
    PITResearchDataset,
    PITResearchRow,
    ProxyObservation,
    ReproducibleMacroFactorRunArtifact,
    ResearchOutputValidityPolicy,
    RetirementOwnerAttestation,
    TargetAvailabilityPolicy,
    VersionedResearchContract,
    build_execution_request,
    calculate_temporal_split_hash,
)
from tests.unit.macro_factor.factories import complete_manifest, complete_result


def _row(index: int, observed_on: date) -> PITResearchRow:
    target_end = observed_on + timedelta(days=30)
    manifest = complete_manifest()
    target_fact = manifest.slices[0].selected_versions[index - 1]
    etf_fact = manifest.slices[1].selected_versions[index - 1]
    future_fact = manifest.slices[2].selected_versions[index - 1]
    return PITResearchRow(
        row_id=f"pit-row-{index}",
        observation_date=observed_on,
        target_period_start=observed_on + timedelta(days=1),
        target_period_end=target_end,
        available_at=max(etf_fact.available_at, future_fact.available_at),
        label_available_at=target_fact.available_at,
        target_value=Decimal(index),
        target_fact_version=target_fact,
        proxies=(
            ProxyObservation(
                asset_code="ETF_CREDIT",
                value=Decimal(index) / Decimal("10"),
                fact_version=etf_fact,
            ),
            ProxyObservation(
                asset_code="FUTURE_COPPER",
                value=Decimal(index) / Decimal("20"),
                fact_version=future_fact,
            ),
        ),
    )


def runner_dataset() -> PITResearchDataset:
    """Return sparse, invented in-memory rows that are never persisted as facts."""

    observations = (
        date(2015, 1, 1),
        date(2016, 1, 1),
        date(2017, 1, 1),
        date(2018, 1, 1),
        date(2019, 1, 6),
        date(2020, 1, 6),
        date(2021, 1, 6),
    )
    return PITResearchDataset(
        manifest_id="pit-r3-growth-v1",
        manifest_hash="a" * 64,
        manifest_as_of=datetime(2026, 6, 30, 16, tzinfo=UTC),
        target_code="growth_nowcast_1m",
        candidate_asset_codes=("ETF_CREDIT", "FUTURE_COPPER"),
        rows=tuple(_row(index, observed_on) for index, observed_on in enumerate(observations, 1)),
    )


def runner_plan() -> NestedTemporalCVPlan:
    """Return two outer folds, each with two strictly earlier inner folds."""

    timing = TargetAvailabilityPolicy.create(
        policy_version="target-availability-v1",
        target_code="growth_nowcast_1m",
        output_role=FactorOutputRole.FORWARD_EXPECTATION,
        horizon_periods=1,
        horizon_unit="month",
        normalized_horizon_days=30,
        label_availability_lag_days=5,
        purge_days=30,
        embargo_days=30,
    )
    return NestedTemporalCVPlan(
        policy_version="macro-factor-split-v1",
        timing=timing,
        alpha_grid=(Decimal("0.01"), Decimal("0.1"), Decimal("1")),
        optimization_metric="validation_information_coefficient",
        optimization_direction=OptimizationDirection.MAXIMIZE,
        final_fold_id="wf-2",
        outer_folds=(
            OuterTemporalFoldPlan(
                fold_id="wf-1",
                training_row_ids=("pit-row-1", "pit-row-2", "pit-row-3", "pit-row-4"),
                validation_row_ids=("pit-row-5",),
                out_of_sample_row_ids=("pit-row-6",),
                selection_as_of=datetime(2019, 12, 31, tzinfo=UTC),
                evaluation_as_of=datetime(2020, 3, 1, tzinfo=UTC),
                inner_folds=(
                    InnerTemporalFoldPlan(
                        fold_id="wf-1-inner-1",
                        training_row_ids=("pit-row-1",),
                        validation_row_ids=("pit-row-2",),
                    ),
                    InnerTemporalFoldPlan(
                        fold_id="wf-1-inner-2",
                        training_row_ids=("pit-row-1", "pit-row-2"),
                        validation_row_ids=("pit-row-3",),
                    ),
                ),
            ),
            OuterTemporalFoldPlan(
                fold_id="wf-2",
                training_row_ids=(
                    "pit-row-1",
                    "pit-row-2",
                    "pit-row-3",
                    "pit-row-4",
                    "pit-row-5",
                ),
                validation_row_ids=("pit-row-6",),
                out_of_sample_row_ids=("pit-row-7",),
                selection_as_of=datetime(2020, 12, 31, tzinfo=UTC),
                evaluation_as_of=datetime(2021, 3, 1, tzinfo=UTC),
                inner_folds=(
                    InnerTemporalFoldPlan(
                        fold_id="wf-2-inner-1",
                        training_row_ids=("pit-row-1", "pit-row-2"),
                        validation_row_ids=("pit-row-3",),
                    ),
                    InnerTemporalFoldPlan(
                        fold_id="wf-2-inner-2",
                        training_row_ids=("pit-row-1", "pit-row-2", "pit-row-3"),
                        validation_row_ids=("pit-row-4",),
                    ),
                ),
            ),
        ),
    )


def runner_spec() -> MacroFactorRunnerSpec:
    """Return exact governance identities for one research-only runner invocation."""

    return MacroFactorRunnerSpec(
        run_key="growth-fmp-research",
        run_version=1,
        factor_version="macro-growth-v1",
        target=complete_result().target,
        candidates=complete_result().candidates,
        plan=runner_plan(),
        temporal_split=complete_result().split,
        historical_mean_benchmark=VersionedResearchContract(
            "historical-mean-benchmark-v1", "1" * 64
        ),
        fixed_fmp=FixedFMPDefinition.create(
            benchmark_version="fixed-universe-fmp-v1",
            intercept=Decimal("0"),
            weights=(
                FixedFMPWeight("ETF_CREDIT", Decimal("0.6")),
                FixedFMPWeight("FUTURE_COPPER", Decimal("0.4")),
            ),
        ),
        cost_model=VersionedResearchContract("portfolio-cost-model-v3", "2" * 64),
        split_contract=VersionedResearchContract(
            "macro-factor-split-v1",
            calculate_temporal_split_hash(complete_result().split),
        ),
        selection_protocol=VersionedResearchContract("external-nested-lasso-v1", "4" * 64),
        metrics_protocol=VersionedResearchContract("macro-factor-metrics-v1", "5" * 64),
        output_validity_policy=ResearchOutputValidityPolicy.create(
            policy_version="macro-factor-output-validity-v1",
            valid_for_seconds=8 * 24 * 60 * 60,
            maximum_valid_for_seconds=30 * 24 * 60 * 60,
        ),
        reproducibility=ReproducibilityEvidence(
            code_version="git:0123456789abcdef",
            dependency_lock_hash="b" * 64,
            parameter_version="macro-growth-params-v1",
            parameter_hash="c" * 64,
        ),
        random_seed=1729,
        calculated_at=datetime(2026, 7, 2, 10, tzinfo=UTC),
    )


def external_runner_artifact() -> ExternalNestedCVArtifact:
    """Return canonical bytes from a typed external-runner envelope."""

    spec = runner_spec()
    dataset = runner_dataset()
    request = build_execution_request(spec, dataset, complete_manifest())
    result = replace(
        complete_result(),
        selection=replace(complete_result().selection, inner_fold_count=2),
    )
    coefficients = tuple(
        ExternalProxyCoefficient(
            asset_code=item.asset_code,
            lasso_coefficient=item.lasso_coefficient,
            factor_weight=item.factor_weight,
        )
        for item in result.weights.weights
    )
    fold_selections = tuple(
        ExternalOuterFoldSelectionEvidence.create(
            fold_id=fold.fold_id,
            request_design_hash=fold.design_hash,
            selected_alpha=result.selection.selected_alpha,
            inner_scores=tuple(
                ExternalInnerFoldScore(
                    inner_fold_id=inner.fold_id,
                    alpha_scores=(
                        ExternalAlphaScore(Decimal("0.01"), Decimal("0.10")),
                        ExternalAlphaScore(Decimal("0.1"), Decimal("0.30")),
                        ExternalAlphaScore(Decimal("1"), Decimal("0.20")),
                    ),
                )
                for inner in fold.inner_folds
            ),
            final_fit_row_ids=(
                *fold.outer_training_row_ids,
                *fold.outer_validation_row_ids,
            ),
            final_fit_as_of=fold.selection_as_of,
            coefficients=coefficients,
        )
        for fold in request.folds
    )
    return ExternalNestedCVArtifact.create(
        evidence_id="external-runner-artifact-v1",
        producer_ref="approved-external-runner:trial-42",
        produced_at=spec.calculated_at,
        request_hash=request.content_hash,
        result=result,
        fold_selections=fold_selections,
        predictions=(
            ExternalFoldPrediction("wf-1", "pit-row-6", Decimal("5.5")),
            ExternalFoldPrediction("wf-2", "pit-row-7", Decimal("6.5")),
        ),
        dated_outputs=(
            ExternalDatedFactorOutput(
                output_role=FactorOutputRole.FORWARD_EXPECTATION,
                observation_date=date(2026, 6, 30),
                target_period_start=date(2026, 8, 1),
                target_period_end=date(2026, 8, 31),
                horizon_periods=1,
                horizon_unit="month",
                knowledge_as_of=datetime(2026, 6, 30, 16, tzinfo=UTC),
                valid_until=datetime(2026, 7, 10, 10, tzinfo=UTC),
                value=Decimal("0.42"),
                unit="index",
            ),
        ),
        validity_policy=spec.output_validity_policy,
    )


def retirement_owner_attestation(
    artifact: ReproducibleMacroFactorRunArtifact,
    result: ExternalMacroFactorResearchResult,
    retirement: RetirementEvidence,
) -> RetirementOwnerAttestation:
    """Return exact canonical owner attestation for one test retirement."""

    return RetirementOwnerAttestation.create(
        attestation_id=f"owner-attest-{retirement.event_id}",
        owner_ref=result.retirement_policy.owner_ref,
        artifact_id=artifact.artifact_id,
        artifact_hash=artifact.content_hash,
        retirement_event_id=retirement.event_id,
        policy_version=retirement.policy_version,
        retirement_evidence_hash=retirement.evidence_hash,
        issued_at=retirement.retired_at,
    )
