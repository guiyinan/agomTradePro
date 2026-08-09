"""Pure-domain tests for the R3 reproducible runner and research ledger."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.macro_factor.domain.entities import FactorOutputRole, RetirementEvidence
from apps.macro_factor.domain.reproducible_runner import (
    ExternalAlphaScore,
    ExternalInnerFoldScore,
    ExternalNestedCVArtifact,
    ExternalOuterFoldSelectionEvidence,
    ExternalProxyCoefficient,
    MacroFactorLifecycleEventType,
    MacroFactorOutputResearchStatus,
    TargetAvailabilityPolicy,
    VersionedResearchContract,
    append_retirement_event,
    assess_output_research_status,
    build_execution_request,
    build_reproducible_run,
    calculate_temporal_split_hash,
)
from tests.unit.macro_factor.factories import complete_manifest
from tests.unit.macro_factor.runner_factories import (
    external_runner_artifact,
    retirement_owner_attestation,
    runner_dataset,
    runner_plan,
    runner_spec,
)


def test_runner_seals_baselines_nested_cv_and_all_governance_identities() -> None:
    spec = runner_spec()
    bundle = build_reproducible_run(
        spec,
        runner_dataset(),
        complete_manifest(),
        external_runner_artifact(),
    )

    artifact = bundle.artifact
    assert artifact.source_result_hash == external_runner_artifact().result.content_hash
    assert artifact.pit_manifest_hash == "a" * 64
    assert artifact.benchmark_hash == "1" * 64
    assert artifact.cost_model_hash == "2" * 64
    assert artifact.split_contract_hash == spec.split_contract.content_hash
    assert artifact.code_version == spec.reproducibility.code_version
    assert artifact.dependency_lock_hash == spec.reproducibility.dependency_lock_hash
    assert artifact.random_seed == 1729
    assert len(artifact.fold_benchmarks) == 2
    assert all(item.historical_mean.sample_count == 1 for item in artifact.fold_benchmarks)
    assert all(item.fixed_fmp.sample_count == 1 for item in artifact.fold_benchmarks)
    assert all(item.external_model.sample_count == 1 for item in artifact.fold_benchmarks)
    assert len(artifact.content_hash) == 64
    assert bundle.outputs[0].artifact_hash == artifact.content_hash
    assert bundle.outputs[0].research_only is True
    assert bundle.outputs[0].must_not_use_for_decision is True
    assert bundle.outputs[0].must_not_execute is True
    assert bundle.lifecycle_events[0].event_type is MacroFactorLifecycleEventType.RECORDED
    assert artifact.fold_benchmarks[0].historical_mean.mean_absolute_error == Decimal("3")


def test_outer_folds_select_independently_and_only_explicit_final_fold_binds_result() -> None:
    artifact = external_runner_artifact()
    first = artifact.fold_selections[0]
    independent_scores = tuple(
        ExternalInnerFoldScore(
            inner_fold_id=item.inner_fold_id,
            alpha_scores=(
                ExternalAlphaScore(Decimal("0.01"), Decimal("0.50")),
                ExternalAlphaScore(Decimal("0.1"), Decimal("0.30")),
                ExternalAlphaScore(Decimal("1"), Decimal("0.20")),
            ),
        )
        for item in first.inner_scores
    )
    independent_first = ExternalOuterFoldSelectionEvidence.create(
        fold_id=first.fold_id,
        request_design_hash=first.request_design_hash,
        selected_alpha=Decimal("0.01"),
        inner_scores=independent_scores,
        final_fit_row_ids=first.final_fit_row_ids,
        final_fit_as_of=first.final_fit_as_of,
        coefficients=(
            first.coefficients[0],
            ExternalProxyCoefficient(
                asset_code=first.coefficients[1].asset_code,
                lasso_coefficient=Decimal("0"),
                factor_weight=Decimal("0"),
            ),
        ),
    )
    independent_artifact = ExternalNestedCVArtifact.create(
        evidence_id=artifact.evidence_id,
        producer_ref=artifact.producer_ref,
        produced_at=artifact.produced_at,
        request_hash=artifact.request_hash,
        result=artifact.result,
        fold_selections=(independent_first, *artifact.fold_selections[1:]),
        predictions=artifact.predictions,
        dated_outputs=artifact.dated_outputs,
        validity_policy=artifact.validity_policy,
    )

    bundle = build_reproducible_run(
        runner_spec(), runner_dataset(), complete_manifest(), independent_artifact
    )

    assert bundle.artifact.external_artifact_hash == independent_artifact.artifact_hash
    with pytest.raises(ValueError, match="final fold"):
        replace(runner_plan(), final_fold_id="missing-fold")


def test_outer_oos_rows_cannot_enter_inner_or_outer_selection() -> None:
    plan = runner_plan()
    first = plan.outer_folds[0]

    with pytest.raises(ValueError, match="out-of-sample"):
        replace(
            first,
            inner_folds=(
                replace(
                    first.inner_folds[0],
                    validation_row_ids=(first.out_of_sample_row_ids[0],),
                ),
                first.inner_folds[1],
            ),
        )


def test_purge_and_embargo_must_cover_horizon_and_label_availability() -> None:
    with pytest.raises(ValueError, match="purge_days"):
        TargetAvailabilityPolicy.create(
            policy_version="timing-v1",
            target_code="growth_nowcast_1m",
            output_role=FactorOutputRole.FORWARD_EXPECTATION,
            horizon_periods=1,
            horizon_unit="month",
            normalized_horizon_days=30,
            label_availability_lag_days=35,
            purge_days=30,
            embargo_days=35,
        )
    with pytest.raises(ValueError, match="embargo_days"):
        TargetAvailabilityPolicy.create(
            policy_version="timing-v1",
            target_code="growth_nowcast_1m",
            output_role=FactorOutputRole.FORWARD_EXPECTATION,
            horizon_periods=1,
            horizon_unit="month",
            normalized_horizon_days=30,
            label_availability_lag_days=5,
            purge_days=30,
            embargo_days=29,
        )


def test_request_uses_available_at_cutoffs_and_hashes_every_fold_design() -> None:
    dataset = runner_dataset()
    request = build_execution_request(runner_spec(), dataset, complete_manifest())
    assert all(binding.manifest_hash == dataset.manifest_hash for binding in request.folds)
    assert all(len(binding.design_hash) == 64 for binding in request.folds)
    assert all(binding.outer_oos_row_ids for binding in request.folds)

    spec = runner_spec()
    first_fold = replace(
        spec.plan.outer_folds[0],
        selection_as_of=datetime(2018, 6, 1, tzinfo=UTC),
    )
    cutoff_spec = replace(
        spec,
        plan=replace(
            spec.plan,
            outer_folds=(first_fold, spec.plan.outer_folds[1]),
        ),
    )
    with pytest.raises(ValueError, match="selection cutoff"):
        build_execution_request(
            cutoff_spec,
            dataset,
            complete_manifest(),
        )

    changed = replace(
        dataset.rows[-1],
        target_value=dataset.rows[-1].target_value + Decimal("0.01"),
    )
    changed_request = build_execution_request(
        runner_spec(),
        replace(dataset, rows=(*dataset.rows[:-1], changed)),
        complete_manifest(),
    )
    assert changed_request.content_hash != request.content_hash
    assert changed_request.folds[-1].design_hash != request.folds[-1].design_hash


def test_request_rejects_tampered_manifest_fact_content_hash() -> None:
    manifest = complete_manifest()
    target_slice = manifest.slices[0]
    tampered_version = replace(
        target_slice.selected_versions[0],
        content_hash="f" * 64,
    )
    tampered_manifest = replace(
        manifest,
        slices=(
            replace(
                target_slice,
                selected_versions=(
                    tampered_version,
                    *target_slice.selected_versions[1:],
                ),
            ),
            *manifest.slices[1:],
        ),
    )

    with pytest.raises(ValueError, match="exact manifest-selected version"):
        build_execution_request(runner_spec(), runner_dataset(), tampered_manifest)


def test_request_rejects_rows_outside_the_exact_typed_split_window() -> None:
    spec = runner_spec()
    first_split_fold = spec.temporal_split.walk_forward_folds[0]
    contradictory_split = replace(
        spec.temporal_split,
        walk_forward_folds=(
            replace(
                first_split_fold,
                training=replace(
                    first_split_fold.training,
                    start=first_split_fold.training.start.replace(year=2016),
                ),
            ),
            *spec.temporal_split.walk_forward_folds[1:],
        ),
    )
    contradictory_spec = replace(
        spec,
        temporal_split=contradictory_split,
        split_contract=VersionedResearchContract(
            spec.split_contract.version,
            calculate_temporal_split_hash(contradictory_split),
        ),
    )

    with pytest.raises(ValueError, match="outside typed temporal split window"):
        build_execution_request(contradictory_spec, runner_dataset(), complete_manifest())


def test_external_selection_requires_complete_alpha_grid_and_exact_final_fit() -> None:
    artifact = external_runner_artifact()
    first = artifact.fold_selections[0]
    incomplete_scores = tuple(
        ExternalInnerFoldScore(
            inner_fold_id=item.inner_fold_id,
            alpha_scores=item.alpha_scores[:-1],
        )
        for item in first.inner_scores
    )
    incomplete_first = ExternalOuterFoldSelectionEvidence.create(
        fold_id=first.fold_id,
        request_design_hash=first.request_design_hash,
        selected_alpha=first.selected_alpha,
        inner_scores=incomplete_scores,
        final_fit_row_ids=first.final_fit_row_ids,
        final_fit_as_of=first.final_fit_as_of,
        coefficients=first.coefficients,
    )
    incomplete_artifact = ExternalNestedCVArtifact.create(
        evidence_id=artifact.evidence_id,
        producer_ref=artifact.producer_ref,
        produced_at=artifact.produced_at,
        request_hash=artifact.request_hash,
        result=artifact.result,
        fold_selections=(incomplete_first, *artifact.fold_selections[1:]),
        predictions=artifact.predictions,
        dated_outputs=artifact.dated_outputs,
        validity_policy=artifact.validity_policy,
    )
    with pytest.raises(ValueError, match="exact alpha grid"):
        build_reproducible_run(
            runner_spec(), runner_dataset(), complete_manifest(), incomplete_artifact
        )

    wrong_fit_first = ExternalOuterFoldSelectionEvidence.create(
        fold_id=first.fold_id,
        request_design_hash=first.request_design_hash,
        selected_alpha=first.selected_alpha,
        inner_scores=first.inner_scores,
        final_fit_row_ids=(*first.final_fit_row_ids[:-1], "pit-row-6"),
        final_fit_as_of=first.final_fit_as_of,
        coefficients=first.coefficients,
    )
    wrong_fit_artifact = ExternalNestedCVArtifact.create(
        evidence_id=artifact.evidence_id,
        producer_ref=artifact.producer_ref,
        produced_at=artifact.produced_at,
        request_hash=artifact.request_hash,
        result=artifact.result,
        fold_selections=(wrong_fit_first, *artifact.fold_selections[1:]),
        predictions=artifact.predictions,
        dated_outputs=artifact.dated_outputs,
        validity_policy=artifact.validity_policy,
    )
    with pytest.raises(ValueError, match=r"exact train\+validation rows"):
        build_reproducible_run(
            runner_spec(), runner_dataset(), complete_manifest(), wrong_fit_artifact
        )


def test_external_artifact_requires_exact_canonical_bytes_and_request_hash() -> None:
    artifact = external_runner_artifact()
    with pytest.raises(ValueError, match="canonical bytes"):
        ExternalNestedCVArtifact(
            evidence_id=artifact.evidence_id,
            producer_ref=artifact.producer_ref,
            produced_at=artifact.produced_at,
            request_hash=artifact.request_hash,
            result=artifact.result,
            fold_selections=artifact.fold_selections,
            predictions=artifact.predictions,
            dated_outputs=artifact.dated_outputs,
            validity_policy=artifact.validity_policy,
            artifact_bytes=artifact.artifact_bytes + b" ",
            artifact_hash=artifact.artifact_hash,
        )

    with pytest.raises(ValueError, match="request hash"):
        mismatched = ExternalNestedCVArtifact.create(
            evidence_id=artifact.evidence_id,
            producer_ref=artifact.producer_ref,
            produced_at=artifact.produced_at,
            request_hash="9" * 64,
            result=artifact.result,
            fold_selections=artifact.fold_selections,
            predictions=artifact.predictions,
            dated_outputs=artifact.dated_outputs,
        )
        build_reproducible_run(
            runner_spec(),
            runner_dataset(),
            complete_manifest(),
            mismatched,
        )


def test_output_exact_expiry_and_append_only_retirement_block_research_use() -> None:
    bundle = build_reproducible_run(
        runner_spec(),
        runner_dataset(),
        complete_manifest(),
        external_runner_artifact(),
    )
    output = bundle.outputs[0]
    root_event = bundle.lifecycle_events[0]
    before_expiry = output.valid_until - timedelta(microseconds=1)

    assert (
        assess_output_research_status(output, bundle.lifecycle_events, assessed_at=before_expiry)
        is MacroFactorOutputResearchStatus.AVAILABLE_FOR_RESEARCH
    )
    assert (
        assess_output_research_status(
            output, bundle.lifecycle_events, assessed_at=output.valid_until
        )
        is MacroFactorOutputResearchStatus.STALE
    )

    result = external_runner_artifact().result
    retirement = RetirementEvidence(
        event_id="retire-growth-run-v1",
        retired_at=output.produced_at + timedelta(days=1),
        policy_version=result.retirement_policy.policy_version,
        reason_codes=(result.retirement_policy.rules[0].rule_id,),
        evidence_hash="9" * 64,
    )
    retired_event = append_retirement_event(
        artifact=bundle.artifact,
        source_result=result,
        retirement=retirement,
        owner_attestation=retirement_owner_attestation(
            bundle.artifact,
            result,
            retirement,
        ),
        previous_event=root_event,
        recorded_at=retirement.retired_at,
    )

    assert retired_event.sequence == 2
    assert retired_event.previous_event_hash == root_event.content_hash
    assert retired_event.event_type is MacroFactorLifecycleEventType.RETIRED
    assert (
        assess_output_research_status(
            output,
            (root_event, retired_event),
            assessed_at=retirement.retired_at,
        )
        is MacroFactorOutputResearchStatus.RETIRED
    )


def test_artifact_hash_changes_with_benchmark_cost_or_dependency_identity() -> None:
    base = runner_spec()
    baseline_bundle = build_reproducible_run(
        base, runner_dataset(), complete_manifest(), external_runner_artifact()
    )
    changed_cost = replace(
        base,
        cost_model=VersionedResearchContract(base.cost_model.version, "8" * 64),
    )
    changed_dependency = replace(
        base,
        reproducibility=replace(base.reproducibility, dependency_lock_hash="7" * 64),
    )

    with pytest.raises(ValueError, match="request hash"):
        build_reproducible_run(
            changed_cost,
            runner_dataset(),
            complete_manifest(),
            external_runner_artifact(),
        )
    with pytest.raises(ValueError, match="request hash"):
        build_reproducible_run(
            changed_dependency,
            runner_dataset(),
            complete_manifest(),
            external_runner_artifact(),
        )

    assert baseline_bundle.artifact.content_hash
