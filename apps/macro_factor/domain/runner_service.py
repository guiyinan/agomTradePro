"""Pure composition service for a complete reproducible R3 run bundle."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.macro_factor.domain.entities import (
    ExternalMacroFactorResearchResult,
    PITManifestEvidence,
    validate_external_macro_factor_result,
)

from ._runner_support import hash_payload
from .baselines import FoldBenchmarkResult, calculate_error_metrics
from .dated_outputs import DatedMacroFactorOutput
from .lifecycle import MacroFactorLifecycleEvent, create_root_lifecycle_event
from .run_artifacts import ExternalNestedCVArtifact, ReproducibleMacroFactorRunArtifact
from .runner_inputs import PITResearchDataset
from .temporal_plan import (
    MacroFactorRunnerSpec,
    NestedCVExecutionRequest,
    OptimizationDirection,
    build_execution_request,
    calculate_temporal_split_hash,
)


@dataclass(frozen=True)
class ReproducibleMacroFactorRunBundle:
    """Atomic persistence payload for source result, run, outputs, and root event."""

    source_result: ExternalMacroFactorResearchResult
    artifact: ReproducibleMacroFactorRunArtifact
    outputs: tuple[DatedMacroFactorOutput, ...]
    lifecycle_events: tuple[MacroFactorLifecycleEvent, ...]


def _validate_external_result_identity(
    spec: MacroFactorRunnerSpec,
    external: ExternalNestedCVArtifact,
) -> None:
    result = external.result
    validity_policy = spec.output_validity_policy.validated_copy()
    if external.validity_policy != validity_policy:
        raise ValueError("external output-validity policy does not match runner spec")
    if result.factor_version != spec.factor_version:
        raise ValueError("external factor version does not match runner spec")
    if result.target != spec.target or result.candidates != spec.candidates:
        raise ValueError("external target/candidates do not match runner spec")
    if result.reproducibility != spec.reproducibility:
        raise ValueError("external reproducibility identity does not match runner spec")
    if result.split.policy_version != spec.split_contract.version or (
        calculate_temporal_split_hash(result.split) != spec.split_contract.content_hash
    ):
        raise ValueError("external split contract does not match runner spec")
    if result.selection.alpha_grid != spec.plan.alpha_grid or (
        result.selection.optimization_metric != spec.plan.optimization_metric
    ):
        raise ValueError("external selection protocol does not match runner plan")
    inner_counts = {len(item.inner_folds) for item in spec.plan.outer_folds}
    if inner_counts != {result.selection.inner_fold_count} or (
        result.selection.outer_fold_count != len(spec.plan.outer_folds)
    ):
        raise ValueError("external nested-CV fold counts do not match runner plan")
    if result.evaluation.benchmark_version != spec.historical_mean_benchmark.version:
        raise ValueError("external benchmark version does not match runner spec")
    if result.evaluation.cost_model_version != spec.cost_model.version:
        raise ValueError("external cost model version does not match runner spec")
    if external.produced_at != spec.calculated_at:
        raise ValueError("external produced_at does not match runner calculated_at")


def _validate_fold_selection_evidence(
    spec: MacroFactorRunnerSpec,
    request: NestedCVExecutionRequest,
    external: ExternalNestedCVArtifact,
) -> None:
    selection_by_fold = {item.fold_id: item for item in external.fold_selections}
    request_by_fold = {item.fold_id: item for item in request.folds}
    if frozenset(selection_by_fold) != frozenset(request_by_fold):
        raise ValueError("external selection evidence must cover every outer fold exactly")
    result_weights = {
        item.asset_code: (item.lasso_coefficient, item.factor_weight)
        for item in external.result.weights.weights
    }
    candidate_codes = {item.asset_code for item in spec.candidates}
    selected_codes = set(external.result.selection.selected_asset_codes)
    for fold_plan in spec.plan.outer_folds:
        evidence = selection_by_fold[fold_plan.fold_id]
        request_fold = request_by_fold[fold_plan.fold_id]
        if evidence.request_design_hash != request_fold.design_hash:
            raise ValueError("external fold selection design hash mismatch")
        score_by_inner = {item.inner_fold_id: item for item in evidence.inner_scores}
        expected_inner_ids = {item.fold_id for item in request_fold.inner_folds}
        if frozenset(score_by_inner) != frozenset(expected_inner_ids):
            raise ValueError("external inner scores must cover every planned inner fold")
        totals = {alpha: Decimal("0") for alpha in spec.plan.alpha_grid}
        for score in evidence.inner_scores:
            values = {item.alpha: item.score for item in score.alpha_scores}
            if frozenset(values) != frozenset(spec.plan.alpha_grid):
                raise ValueError("external inner scores must cover the exact alpha grid")
            for alpha, value in values.items():
                totals[alpha] += value
        if spec.plan.optimization_direction is OptimizationDirection.MAXIMIZE:
            best_score = max(totals.values())
        else:
            best_score = min(totals.values())
        expected_alpha = min(alpha for alpha, score in totals.items() if score == best_score)
        if evidence.selected_alpha != expected_alpha:
            raise ValueError("external selected alpha is not the deterministic inner-CV winner")
        if evidence.final_fit_row_ids != (
            *request_fold.outer_training_row_ids,
            *request_fold.outer_validation_row_ids,
        ):
            raise ValueError("external final fit must use exact train+validation rows")
        if evidence.final_fit_as_of != request_fold.selection_as_of:
            raise ValueError("external final-fit cutoff does not match request")
        coefficient_by_code = {item.asset_code: item for item in evidence.coefficients}
        if frozenset(coefficient_by_code) != frozenset(candidate_codes):
            raise ValueError("external coefficients must cover the exact candidate universe")
        if fold_plan.fold_id == spec.plan.final_fold_id:
            fold_selected_codes = {
                code for code, item in coefficient_by_code.items() if item.lasso_coefficient != 0
            }
            if (
                evidence.selected_alpha != external.result.selection.selected_alpha
                or fold_selected_codes != selected_codes
            ):
                raise ValueError("final-fold selection does not match result selection")
            last_weights = {
                code: (item.lasso_coefficient, item.factor_weight)
                for code, item in coefficient_by_code.items()
                if item.lasso_coefficient != 0
            }
            if last_weights != result_weights:
                raise ValueError("last outer-fold final fit does not match result weights")


def build_reproducible_run(
    spec: MacroFactorRunnerSpec,
    dataset: PITResearchDataset,
    manifest: PITManifestEvidence,
    external: ExternalNestedCVArtifact,
) -> ReproducibleMacroFactorRunBundle:
    """Validate typed external evidence and build an immutable research bundle."""

    spec = spec.validated_copy()
    dataset = dataset.validated_copy()
    manifest = manifest.validated_copy()
    external.__post_init__()
    request = build_execution_request(spec, dataset, manifest)
    if external.request_hash != request.content_hash:
        raise ValueError("external artifact request hash does not match runner request")
    _validate_external_result_identity(spec, external)
    _validate_fold_selection_evidence(spec, request, external)
    if len(external.dated_outputs) != 1:
        raise ValueError("one run must publish exactly one governed inference horizon")
    inference = dataset.inference_row
    if inference is None:
        raise ValueError("one label-free inference row is required")
    freshness_policy = spec.input_knowledge_freshness_policy.validated_copy()
    manifest_fresh_until = freshness_policy.manifest_expires_at(manifest.as_of_time)
    inference_fresh_until = freshness_policy.inference_expires_at(inference.available_at)
    if external.produced_at > manifest_fresh_until:
        raise ValueError("external production time exceeds PIT manifest freshness")
    if external.produced_at > inference_fresh_until:
        raise ValueError("external production time exceeds PIT inference freshness")
    blockers = validate_external_macro_factor_result(
        external.result,
        manifest,
        assessed_at=external.produced_at,
    )
    if blockers:
        raise ValueError(
            "external result failed existing validator: "
            + ",".join(item.value for item in blockers)
        )
    predictions_by_identity = {
        (item.fold_id, item.row_id): item.predicted_value for item in external.predictions
    }
    expected_prediction_ids = {
        (fold.fold_id, row_id)
        for fold in spec.plan.outer_folds
        for row_id in fold.out_of_sample_row_ids
    }
    if frozenset(predictions_by_identity) != frozenset(expected_prediction_ids):
        raise ValueError("external predictions must exactly cover outer OOS rows")
    rows_by_id = dataset.rows_by_id
    fold_benchmarks: list[FoldBenchmarkResult] = []
    for fold in spec.plan.outer_folds:
        training = tuple(rows_by_id[row_id] for row_id in fold.training_row_ids)
        validation = tuple(rows_by_id[row_id] for row_id in fold.validation_row_ids)
        final_fit = (*training, *validation)
        out_of_sample = tuple(rows_by_id[row_id] for row_id in fold.out_of_sample_row_ids)
        historical_mean = sum(
            (item.target_value for item in final_fit), start=Decimal("0")
        ) / Decimal(len(final_fit))
        actuals = tuple(item.target_value for item in out_of_sample)
        fold_benchmarks.append(
            FoldBenchmarkResult(
                fold_id=fold.fold_id,
                historical_mean=calculate_error_metrics(
                    actuals,
                    tuple(historical_mean for _ in out_of_sample),
                ),
                fixed_fmp=calculate_error_metrics(
                    actuals,
                    tuple(spec.fixed_fmp.predict(item) for item in out_of_sample),
                ),
                external_model=calculate_error_metrics(
                    actuals,
                    tuple(
                        predictions_by_identity[(fold.fold_id, item.row_id)]
                        for item in out_of_sample
                    ),
                ),
            )
        )
    artifact = ReproducibleMacroFactorRunArtifact(
        artifact_id=hash_payload({"run_key": spec.run_key, "run_version": spec.run_version}),
        run_key=spec.run_key,
        run_version=spec.run_version,
        factor_version=spec.factor_version,
        target_code=spec.target.target_code,
        output_role=spec.target.output_role,
        produced_at=external.produced_at,
        source_result_id=external.result.result_id,
        source_result_hash=external.result.content_hash,
        external_evidence_id=external.evidence_id,
        external_producer_ref=external.producer_ref,
        external_artifact_hash=external.artifact_hash,
        external_artifact_media_type=external.media_type,
        external_artifact_content_length=len(external.artifact_bytes),
        external_artifact_bytes=external.artifact_bytes,
        request_hash=request.content_hash,
        pit_manifest_id=manifest.manifest_id,
        pit_manifest_hash=manifest.manifest_hash,
        dataset_hash=dataset.content_hash,
        benchmark_version=spec.historical_mean_benchmark.version,
        benchmark_hash=spec.historical_mean_benchmark.content_hash,
        fixed_fmp_version=spec.fixed_fmp.benchmark_version,
        fixed_fmp_hash=spec.fixed_fmp.content_hash,
        cost_model_version=spec.cost_model.version,
        cost_model_hash=spec.cost_model.content_hash,
        split_contract_version=spec.split_contract.version,
        split_contract_hash=spec.split_contract.content_hash,
        plan_hash=spec.plan.content_hash,
        selection_protocol_version=spec.selection_protocol.version,
        selection_protocol_hash=spec.selection_protocol.content_hash,
        metrics_protocol_version=spec.metrics_protocol.version,
        metrics_protocol_hash=spec.metrics_protocol.content_hash,
        timing_policy_version=spec.plan.timing.policy_version,
        timing_policy_hash=spec.plan.timing.content_hash,
        code_version=spec.reproducibility.code_version,
        dependency_lock_hash=spec.reproducibility.dependency_lock_hash,
        parameter_version=spec.reproducibility.parameter_version,
        parameter_hash=spec.reproducibility.parameter_hash,
        random_seed=spec.random_seed,
        fold_benchmarks=tuple(fold_benchmarks),
    )
    outputs: list[DatedMacroFactorOutput] = []
    knowledge_cutoff = dataset.manifest_as_of
    for item in external.dated_outputs:
        if (
            item.output_role is not spec.target.output_role
            or item.horizon_periods != spec.target.horizon_periods
            or item.horizon_unit != spec.target.horizon_unit
            or item.unit != spec.target.unit
        ):
            raise ValueError("external dated output does not match target definition")
        if (
            item.observation_date != inference.observation_date
            or item.target_period_start != inference.target_period.period_start
            or item.target_period_end != inference.target_period.period_end
        ):
            raise ValueError("external dated output does not match the inference calendar row")
        if item.knowledge_as_of > external.produced_at or item.valid_until <= external.produced_at:
            raise ValueError("external dated output publication timeline is invalid")
        if item.knowledge_as_of != knowledge_cutoff:
            raise ValueError("external dated output must use the exact PIT knowledge cutoff")
        if item.valid_until > manifest_fresh_until:
            raise ValueError("external dated output exceeds PIT manifest freshness")
        if item.valid_until > inference_fresh_until:
            raise ValueError("external dated output exceeds PIT inference freshness")
        output_id = hash_payload(
            {
                "artifact_id": artifact.artifact_id,
                "output_role": item.output_role.value,
                "observation_date": item.observation_date.isoformat(),
                "target_period_start": item.target_period_start.isoformat(),
                "target_period_end": item.target_period_end.isoformat(),
            }
        )
        outputs.append(
            DatedMacroFactorOutput(
                output_id=output_id,
                artifact_id=artifact.artifact_id,
                artifact_hash=artifact.content_hash,
                factor_version=artifact.factor_version,
                target_code=artifact.target_code,
                output_role=item.output_role,
                observation_date=item.observation_date,
                target_period_start=item.target_period_start,
                target_period_end=item.target_period_end,
                horizon_periods=item.horizon_periods,
                horizon_unit=item.horizon_unit,
                knowledge_as_of=knowledge_cutoff,
                produced_at=external.produced_at,
                valid_until=item.valid_until,
                value=item.value,
                unit=item.unit,
                pit_manifest_id=artifact.pit_manifest_id,
                pit_manifest_hash=artifact.pit_manifest_hash,
            )
        )
    root_event = create_root_lifecycle_event(artifact, external.result)
    return ReproducibleMacroFactorRunBundle(
        source_result=external.result,
        artifact=artifact,
        outputs=tuple(outputs),
        lifecycle_events=(root_event,),
    )


__all__ = ["ReproducibleMacroFactorRunBundle", "build_reproducible_run"]
