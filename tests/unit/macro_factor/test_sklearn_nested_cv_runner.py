"""Synthetic PIT coverage for the concrete R3 nested-CV Lasso adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib.metadata import version as package_version
from inspect import signature

import pytest

from apps.macro_factor.application.reproducible_runner import (
    MacroFactorRunnerBlockerCode,
    MacroFactorRunnerStatus,
    RunReproducibleMacroFactorCommand,
)
from apps.macro_factor.composition import (
    _build_concrete_lasso_runner_runtime_for_test,
    build_concrete_lasso_runner_runtime,
)
from apps.macro_factor.domain.entities import (
    FactorOutputRole,
    MacroTargetDefinition,
    MacroTargetFamily,
    PITDatasetSlice,
    PITInferenceCalendarPeriodEvidence,
    PITManifestEvidence,
    PITSelectedFactVersion,
    ProxyAssetDefinition,
    ProxyAssetKind,
    ReproducibilityEvidence,
    SampleWindow,
    TemporalSplitSpec,
    WalkForwardFold,
)
from apps.macro_factor.domain.reproducible_runner import (
    FixedFMPDefinition,
    FixedFMPWeight,
    InferenceTargetCalendarPeriod,
    InnerTemporalFoldPlan,
    InputKnowledgeFreshnessPolicy,
    MacroFactorLifecycleEvent,
    MacroFactorRunnerSpec,
    NestedTemporalCVPlan,
    OptimizationDirection,
    OuterTemporalFoldPlan,
    PITInferenceRow,
    PITResearchDataset,
    PITResearchRow,
    ProxyObservation,
    ReproducibleMacroFactorRunArtifact,
    ReproducibleMacroFactorRunBundle,
    ResearchOutputValidityPolicy,
    TargetAvailabilityPolicy,
    VersionedResearchContract,
    build_execution_request,
    calculate_temporal_split_hash,
)
from apps.macro_factor.infrastructure.sklearn_nested_cv_runner import (
    IMPLEMENTATION_ID,
    SklearnNestedCVFittingConfig,
    SklearnNestedCVLassoRunner,
)
from tests.unit.macro_factor.factories import complete_result


def _at(value: date, *, days: int = 0) -> datetime:
    return datetime.combine(value + timedelta(days=days), datetime.min.time(), tzinfo=UTC)


def _synthetic_case() -> tuple[
    PITManifestEvidence,
    PITResearchDataset,
    MacroFactorRunnerSpec,
    SklearnNestedCVFittingConfig,
]:
    observations = tuple(date(2010, 1, 1) + timedelta(days=70 * index) for index in range(30))
    target_versions = tuple(
        PITSelectedFactVersion(
            version_id=1_000 + index,
            content_hash=f"{index + 1:064x}",
            effective_at=_at(observed_on, days=5),
            available_at=_at(observed_on, days=6),
        )
        for index, observed_on in enumerate(observations)
    )
    first_proxy_versions = tuple(
        PITSelectedFactVersion(
            version_id=2_000 + index,
            content_hash=f"{index + 101:064x}",
            effective_at=_at(observed_on),
            available_at=_at(observed_on, days=1),
        )
        for index, observed_on in enumerate(observations)
    )
    second_proxy_versions = tuple(
        PITSelectedFactVersion(
            version_id=3_000 + index,
            content_hash=f"{index + 201:064x}",
            effective_at=_at(observed_on),
            available_at=_at(observed_on, days=1),
        )
        for index, observed_on in enumerate(observations)
    )
    target = MacroTargetDefinition(
        target_code="growth_nowcast_1p",
        family=MacroTargetFamily.GROWTH,
        output_role=FactorOutputRole.FORWARD_EXPECTATION,
        dataset_key="macro.synthetic.vintage",
        business_key="SYNTHETIC_GROWTH",
        unit="index",
        frequency="synthetic",
        transformation_version="identity-v1",
        horizon_periods=1,
        horizon_unit="period",
    )
    candidates = (
        ProxyAssetDefinition(
            asset_code="PROXY_A",
            dataset_key="market.synthetic.proxy",
            business_key="PROXY_A",
            kind=ProxyAssetKind.ETF,
            frequency="synthetic",
            transformation_version="identity-v1",
        ),
        ProxyAssetDefinition(
            asset_code="PROXY_B",
            dataset_key="market.synthetic.proxy",
            business_key="PROXY_B",
            kind=ProxyAssetKind.ETF,
            frequency="synthetic",
            transformation_version="identity-v1",
        ),
    )
    manifest_as_of = _at(observations[-1], days=10)
    calendar_id = "synthetic-calendar"
    calendar_version = "synthetic-calendar-v1"
    calendar_hash = "d" * 64
    target_period = InferenceTargetCalendarPeriod.create(
        calendar_id=calendar_id,
        period_id="synthetic-forward-period-v1",
        calendar_version=calendar_version,
        calendar_hash=calendar_hash,
        period_start=manifest_as_of.date() + timedelta(days=2),
        period_end=manifest_as_of.date() + timedelta(days=6),
    )
    manifest_period = PITInferenceCalendarPeriodEvidence.create(
        calendar_id=calendar_id,
        calendar_version=calendar_version,
        calendar_hash=calendar_hash,
        period_id=target_period.period_id,
        period_start=target_period.period_start,
        period_end=target_period.period_end,
    )
    manifest = PITManifestEvidence.create(
        manifest_id="pit-synthetic-r3-v1",
        manifest_hash="a" * 64,
        as_of_time=manifest_as_of,
        knowledge_scope="public",
        calendar_id=calendar_id,
        calendar_version=calendar_version,
        calendar_hash=calendar_hash,
        inference_periods=(manifest_period,),
        slices=(
            PITDatasetSlice(
                target.dataset_key,
                target.business_key,
                tuple(item.version_id for item in target_versions),
                target_versions,
            ),
            PITDatasetSlice(
                candidates[0].dataset_key,
                candidates[0].business_key,
                tuple(item.version_id for item in first_proxy_versions),
                first_proxy_versions,
            ),
            PITDatasetSlice(
                candidates[1].dataset_key,
                candidates[1].business_key,
                tuple(item.version_id for item in second_proxy_versions),
                second_proxy_versions,
            ),
        ),
        coverage_ratio=Decimal("1"),
        missing_count=0,
        estimated_count=0,
        unknown_count=0,
        is_verified=True,
    )
    rows: list[PITResearchRow] = []
    for index, observed_on in enumerate(observations[:-1]):
        first = Decimal(index) / Decimal("10")
        second = Decimal((index % 7) - 3) / Decimal("5") + Decimal(index) / Decimal("100")
        noise = Decimal((index % 3) - 1) / Decimal("100")
        target_value = Decimal("1.5") + Decimal("2.2") * first - Decimal("0.8") * second + noise
        rows.append(
            PITResearchRow(
                row_id=f"synthetic-row-{index:02d}",
                observation_date=observed_on,
                target_period_start=observed_on + timedelta(days=2),
                target_period_end=observed_on + timedelta(days=5),
                available_at=_at(observed_on, days=1),
                label_available_at=_at(observed_on, days=6),
                target_value=target_value,
                target_fact_version=target_versions[index],
                proxies=(
                    ProxyObservation("PROXY_A", first, first_proxy_versions[index]),
                    ProxyObservation("PROXY_B", second, second_proxy_versions[index]),
                ),
            )
        )
    dataset = PITResearchDataset(
        manifest_id=manifest.manifest_id,
        manifest_hash=manifest.manifest_hash,
        manifest_content_hash=manifest.content_hash,
        manifest_as_of=manifest.as_of_time,
        target_code=target.target_code,
        candidate_asset_codes=tuple(item.asset_code for item in candidates),
        rows=tuple(rows),
        inference_row=PITInferenceRow(
            row_id="synthetic-inference-row",
            observation_date=observations[-1],
            available_at=max(
                first_proxy_versions[-1].available_at,
                second_proxy_versions[-1].available_at,
            ),
            target_period=target_period,
            proxies=(
                ProxyObservation(
                    "PROXY_A",
                    Decimal(len(observations) - 1) / Decimal("10"),
                    first_proxy_versions[-1],
                ),
                ProxyObservation(
                    "PROXY_B",
                    Decimal(((len(observations) - 1) % 7) - 3) / Decimal("5")
                    + Decimal(len(observations) - 1) / Decimal("100"),
                    second_proxy_versions[-1],
                ),
            ),
        ),
    )

    def row_ids(start: int, stop: int) -> tuple[str, ...]:
        return tuple(item.row_id for item in rows[start:stop])

    timing = TargetAvailabilityPolicy.create(
        policy_version="synthetic-split-v1",
        target_code=target.target_code,
        output_role=target.output_role,
        horizon_periods=target.horizon_periods,
        horizon_unit=target.horizon_unit,
        normalized_horizon_days=5,
        label_availability_lag_days=1,
        purge_days=5,
        embargo_days=5,
    )
    plan = NestedTemporalCVPlan(
        policy_version="synthetic-split-v1",
        timing=timing,
        alpha_grid=(Decimal("0.0001"), Decimal("0.01"), Decimal("0.2")),
        optimization_metric="validation_mean_squared_error",
        optimization_direction=OptimizationDirection.MINIMIZE,
        final_fold_id="wf-2",
        outer_folds=(
            OuterTemporalFoldPlan(
                fold_id="wf-1",
                training_row_ids=row_ids(0, 10),
                validation_row_ids=row_ids(10, 14),
                out_of_sample_row_ids=row_ids(14, 18),
                selection_as_of=_at(observations[13], days=10),
                evaluation_as_of=_at(observations[17], days=10),
                inner_folds=(
                    InnerTemporalFoldPlan("wf-1-inner-1", row_ids(0, 4), row_ids(4, 6)),
                    InnerTemporalFoldPlan("wf-1-inner-2", row_ids(0, 6), row_ids(6, 8)),
                ),
            ),
            OuterTemporalFoldPlan(
                fold_id="wf-2",
                training_row_ids=row_ids(0, 18),
                validation_row_ids=row_ids(18, 22),
                out_of_sample_row_ids=row_ids(22, 26),
                selection_as_of=_at(observations[21], days=10),
                evaluation_as_of=_at(observations[25], days=10),
                inner_folds=(
                    InnerTemporalFoldPlan("wf-2-inner-1", row_ids(0, 8), row_ids(8, 11)),
                    InnerTemporalFoldPlan("wf-2-inner-2", row_ids(0, 11), row_ids(11, 14)),
                ),
            ),
        ),
    )
    split = TemporalSplitSpec(
        policy_version=plan.policy_version,
        training=SampleWindow(observations[0], observations[9]),
        validation=SampleWindow(observations[10], observations[13]),
        out_of_sample=SampleWindow(observations[14], observations[25]),
        walk_forward_folds=tuple(
            WalkForwardFold(
                fold_id=fold.fold_id,
                training=SampleWindow(
                    dataset.rows_by_id[fold.training_row_ids[0]].observation_date,
                    dataset.rows_by_id[fold.training_row_ids[-1]].observation_date,
                ),
                validation=SampleWindow(
                    dataset.rows_by_id[fold.validation_row_ids[0]].observation_date,
                    dataset.rows_by_id[fold.validation_row_ids[-1]].observation_date,
                ),
                out_of_sample=SampleWindow(
                    dataset.rows_by_id[fold.out_of_sample_row_ids[0]].observation_date,
                    dataset.rows_by_id[fold.out_of_sample_row_ids[-1]].observation_date,
                ),
            )
            for fold in plan.outer_folds
        ),
        embargo_days=5,
    )
    split_contract = VersionedResearchContract(
        plan.policy_version,
        calculate_temporal_split_hash(split),
    )
    inference_row = dataset.inference_row
    assert inference_row is not None
    spec = MacroFactorRunnerSpec(
        run_key="synthetic-concrete-lasso",
        run_version=1,
        factor_version="synthetic-growth-factor-v1",
        expected_manifest_content_hash=manifest.content_hash,
        target=target,
        inference_target_period=inference_row.target_period,
        input_knowledge_freshness_policy=InputKnowledgeFreshnessPolicy.create(
            policy_version="synthetic-input-freshness-v1",
            max_manifest_age_seconds=60 * 24 * 60 * 60,
            max_inference_age_seconds=60 * 24 * 60 * 60,
            maximum_allowed_age_seconds=90 * 24 * 60 * 60,
        ),
        candidates=candidates,
        plan=plan,
        temporal_split=split,
        historical_mean_benchmark=VersionedResearchContract("historical-mean-v1", "1" * 64),
        fixed_fmp=FixedFMPDefinition.create(
            benchmark_version="fixed-fmp-v1",
            intercept=Decimal("0"),
            weights=(
                FixedFMPWeight("PROXY_A", Decimal("0.5")),
                FixedFMPWeight("PROXY_B", Decimal("0.5")),
            ),
        ),
        cost_model=VersionedResearchContract("synthetic-cost-v1", "2" * 64),
        split_contract=split_contract,
        selection_protocol=VersionedResearchContract("sklearn-nested-lasso-v1", "3" * 64),
        metrics_protocol=VersionedResearchContract("synthetic-metrics-v1", "4" * 64),
        output_validity_policy=ResearchOutputValidityPolicy.create(
            policy_version="synthetic-output-validity-v1",
            valid_for_seconds=30 * 24 * 60 * 60,
            maximum_valid_for_seconds=90 * 24 * 60 * 60,
        ),
        reproducibility=ReproducibilityEvidence(
            code_version="git:synthetic-test",
            dependency_lock_hash="5" * 64,
            parameter_version="synthetic-lasso-parameters-v1",
            parameter_hash="6" * 64,
        ),
        random_seed=1729,
        registered_at=_at(observations[0], days=-1),
        calculated_at=manifest_as_of + timedelta(days=1),
    )
    config = SklearnNestedCVFittingConfig(
        selection_protocol=spec.selection_protocol,
        metrics_protocol=spec.metrics_protocol,
        parameter_contract=VersionedResearchContract(
            spec.reproducibility.parameter_version,
            spec.reproducibility.parameter_hash,
        ),
        benchmark_contract=spec.historical_mean_benchmark,
        cost_model_contract=spec.cost_model,
        retirement_policy=complete_result().retirement_policy,
        transaction_cost_rate=Decimal("0.001"),
        max_iterations=100_000,
        tolerance=Decimal("0.0000000001"),
        zero_tolerance=Decimal("0.000000000001"),
        economic_interpretation=(
            "Synthetic proxy coefficients are retained only as a reproducible research test."
        ),
    )
    return manifest, dataset, spec, config


class _ManifestProvider:
    def __init__(self, manifest: PITManifestEvidence | None) -> None:
        self.manifest = manifest

    def get_manifest(self, manifest_id: str) -> PITManifestEvidence | None:
        if self.manifest is None or self.manifest.manifest_id != manifest_id:
            return None
        return self.manifest


class _SpecProvider:
    def __init__(self, spec: MacroFactorRunnerSpec | None) -> None:
        self.spec = spec

    def get_spec(
        self,
        *,
        spec_id: str,
        spec_version: int,
    ) -> MacroFactorRunnerSpec | None:
        value = self.spec
        if value is None or value.run_key != spec_id or value.run_version != spec_version:
            return None
        return value


class _DatasetProvider:
    def __init__(self, dataset: PITResearchDataset | None) -> None:
        self.dataset = dataset

    def get_dataset(
        self,
        *,
        manifest_id: str,
        manifest_hash: str,
        target_code: str,
        candidate_asset_codes: tuple[str, ...],
    ) -> PITResearchDataset | None:
        value = self.dataset
        if value is None:
            return None
        if (
            value.manifest_id != manifest_id
            or value.manifest_hash != manifest_hash
            or value.target_code != target_code
            or value.candidate_asset_codes != candidate_asset_codes
        ):
            return None
        return value


class _Repository:
    def __init__(self) -> None:
        self.bundle: ReproducibleMacroFactorRunBundle | None = None
        self.events: list[MacroFactorLifecycleEvent] = []

    def append_bundle(
        self,
        bundle: ReproducibleMacroFactorRunBundle,
    ) -> ReproducibleMacroFactorRunBundle:
        self.bundle = bundle
        self.events = list(bundle.lifecycle_events)
        return bundle

    def get_artifact(self, artifact_id: str) -> ReproducibleMacroFactorRunArtifact | None:
        if self.bundle is None or self.bundle.artifact.artifact_id != artifact_id:
            return None
        return self.bundle.artifact

    def list_lifecycle_events(self, artifact_id: str) -> tuple[MacroFactorLifecycleEvent, ...]:
        if self.bundle is None or self.bundle.artifact.artifact_id != artifact_id:
            return ()
        return tuple(self.events)

    def append_lifecycle_event(
        self,
        event: MacroFactorLifecycleEvent,
    ) -> MacroFactorLifecycleEvent:
        self.events.append(event)
        return event


def test_concrete_lasso_is_deterministic_and_seals_fit_diagnostics() -> None:
    manifest, dataset, spec, config = _synthetic_case()
    request = build_execution_request(spec, dataset, manifest)
    runner = SklearnNestedCVLassoRunner(config)

    first = runner.execute(request=request, dataset=dataset, spec=spec)
    second = runner.execute(request=request, dataset=dataset, spec=spec)

    assert first is not None
    assert second == first
    assert second.artifact_bytes == first.artifact_bytes
    assert second.artifact_hash == first.artifact_hash
    assert first.result.selection.computation_origin == "infrastructure_concrete_fit"
    assert all(item.concrete_fit is not None for item in first.fold_selections)
    final = next(item for item in first.fold_selections if item.fold_id == spec.plan.final_fold_id)
    assert final.concrete_fit is not None
    assert final.concrete_fit.estimator_version == (
        f"scikit-learn/{package_version('scikit-learn')}:Lasso"
    )
    assert tuple(item.asset_code for item in final.concrete_fit.standardization) == (
        "PROXY_A",
        "PROXY_B",
    )
    assert final.concrete_fit.ols_sample_count == 22
    assert b'"concrete_fit"' in first.artifact_bytes
    assert first.validity_policy == spec.output_validity_policy
    assert spec.output_validity_policy.content_hash.encode() in first.artifact_bytes
    assert all(item.knowledge_as_of == dataset.manifest_as_of for item in first.dated_outputs)
    assert dataset.inference_row is not None
    assert first.dated_outputs[0].observation_date == dataset.inference_row.observation_date
    assert first.dated_outputs[0].target_period_start == (
        dataset.inference_row.target_period.period_start
    )
    final_oos_ids = next(
        fold.out_of_sample_row_ids
        for fold in spec.plan.outer_folds
        if fold.fold_id == spec.plan.final_fold_id
    )
    assert dataset.inference_row.row_id not in final_oos_ids
    assert first.result.research_only is True
    assert first.result.must_not_use_for_decision is True


@pytest.mark.parametrize("replacement_kind", ("target", "candidate"))
def test_concrete_runner_rejects_same_code_spec_semantic_substitution(
    replacement_kind: str,
) -> None:
    manifest, dataset, spec, config = _synthetic_case()
    request = build_execution_request(spec, dataset, manifest)
    if replacement_kind == "target":
        substituted = replace(
            spec,
            target=replace(
                spec.target,
                unit="percent",
                frequency="quarterly",
                transformation_version="qoq-standardization-v3",
            ),
        )
    else:
        substituted = replace(
            spec,
            candidates=(
                replace(
                    spec.candidates[0],
                    frequency="weekly",
                    transformation_version="weekly-return-v3",
                ),
                spec.candidates[1],
            ),
        )

    assert substituted.target.target_code == spec.target.target_code
    assert tuple(item.asset_code for item in substituted.candidates) == tuple(
        item.asset_code for item in spec.candidates
    )
    assert (
        SklearnNestedCVLassoRunner(config).execute(
            request=request,
            dataset=dataset,
            spec=substituted,
        )
        is None
    )


def test_runtime_identity_and_output_validity_cannot_be_spoofed_by_caller() -> None:
    manifest, dataset, spec, config = _synthetic_case()
    object.__setattr__(config, "producer_ref", "vendor://spoofed")
    object.__setattr__(config, "estimator_version", "sklearn-99.99")
    object.__setattr__(
        config,
        "output_valid_until",
        spec.calculated_at + timedelta(days=3_650),
    )
    object.__setattr__(
        config,
        "output_validity_policy",
        ResearchOutputValidityPolicy.create(
            policy_version="spoofed-validity-v1",
            valid_for_seconds=100 * 365 * 24 * 60 * 60,
            maximum_valid_for_seconds=100 * 365 * 24 * 60 * 60,
        ),
    )

    artifact = SklearnNestedCVLassoRunner(config).execute(
        request=build_execution_request(spec, dataset, manifest),
        dataset=dataset,
        spec=spec,
    )

    assert artifact is not None
    assert artifact.producer_ref.startswith(f"{IMPLEMENTATION_ID};")
    assert "vendor" not in artifact.producer_ref
    assert "99.99" not in artifact.artifact_bytes.decode("utf-8")
    assert artifact.validity_policy == spec.output_validity_policy
    assert all(
        output.valid_until == spec.output_validity_policy.valid_until(spec.calculated_at)
        for output in artifact.dated_outputs
    )


def test_hundred_year_validity_exceeds_preregistered_governance_maximum() -> None:
    with pytest.raises(
        ValueError,
        match="exceeds its preregistered governance maximum",
    ):
        ResearchOutputValidityPolicy.create(
            policy_version="bounded-validity-v1",
            valid_for_seconds=100 * 365 * 24 * 60 * 60,
            maximum_valid_for_seconds=90 * 24 * 60 * 60,
        )


@pytest.mark.parametrize(
    "spoofed_seconds",
    (60 * 24 * 60 * 60, 200 * 365 * 24 * 60 * 60),
)
def test_mutated_spec_validity_policy_is_resealed_before_execution(
    spoofed_seconds: int,
) -> None:
    manifest, dataset, spec, config = _synthetic_case()
    request = build_execution_request(spec, dataset, manifest)
    object.__setattr__(
        spec.output_validity_policy,
        "valid_for_seconds",
        spoofed_seconds,
    )

    assert (
        SklearnNestedCVLassoRunner(config).execute(
            request=request,
            dataset=dataset,
            spec=spec,
        )
        is None
    )


def test_spoofed_request_validity_identity_is_rejected() -> None:
    manifest, dataset, spec, config = _synthetic_case()
    request = build_execution_request(spec, dataset, manifest)
    object.__setattr__(request, "output_validity_policy_hash", "f" * 64)

    assert (
        SklearnNestedCVLassoRunner(config).execute(
            request=request,
            dataset=dataset,
            spec=spec,
        )
        is None
    )


def test_non_converged_lasso_cannot_publish_an_artifact() -> None:
    manifest, dataset, spec, config = _synthetic_case()
    hostile = replace(
        config,
        max_iterations=1,
        tolerance=Decimal("1e-30"),
    )

    assert (
        SklearnNestedCVLassoRunner(hostile).execute(
            request=build_execution_request(spec, dataset, manifest),
            dataset=dataset,
            spec=spec,
        )
        is None
    )


class _ComparisonOverridingInt(int):
    """Integer subtype that must not cross an exact built-in-int boundary."""

    def __le__(self, other: object) -> bool:
        return False

    def __lt__(self, other: object) -> bool:
        return False


@pytest.mark.parametrize("invalid_value", (1.5, _ComparisonOverridingInt(1)))
@pytest.mark.parametrize(
    "field_name",
    (
        "run_version",
        "output_valid_for_seconds",
        "output_maximum_valid_for_seconds",
        "max_manifest_age_seconds",
        "max_inference_age_seconds",
        "maximum_allowed_input_age_seconds",
        "random_seed",
    ),
)
def test_execution_request_rejects_non_exact_integer_fields(
    field_name: str,
    invalid_value: object,
) -> None:
    manifest, dataset, spec, _config = _synthetic_case()
    request = build_execution_request(spec, dataset, manifest)

    with pytest.raises(ValueError, match="integer"):
        replace(request, **{field_name: invalid_value})


@pytest.mark.parametrize("invalid_value", (1.5, _ComparisonOverridingInt(1)))
def test_nested_domain_integer_fields_reject_float_and_int_subclass(
    invalid_value: object,
) -> None:
    manifest, _dataset, spec, _config = _synthetic_case()

    with pytest.raises(ValueError, match="integer"):
        replace(spec, run_version=invalid_value)
    with pytest.raises(ValueError, match="integer"):
        replace(spec, random_seed=invalid_value)
    with pytest.raises(ValueError, match="integer"):
        replace(spec.target, horizon_periods=invalid_value)
    with pytest.raises(ValueError, match="integer"):
        replace(spec.plan.timing, normalized_horizon_days=invalid_value)
    with pytest.raises(ValueError, match="integer"):
        replace(spec.temporal_split, embargo_days=invalid_value)
    with pytest.raises(ValueError, match="integer"):
        replace(manifest, missing_count=invalid_value)


def test_concrete_runner_live_revalidates_request_integer_after_object_setattr() -> None:
    manifest, dataset, spec, config = _synthetic_case()
    request = build_execution_request(spec, dataset, manifest)
    object.__setattr__(request, "max_manifest_age_seconds", _ComparisonOverridingInt(1))

    assert (
        SklearnNestedCVLassoRunner(config).execute(
            request=request,
            dataset=dataset,
            spec=spec,
        )
        is None
    )


def test_outer_oos_target_change_cannot_affect_inner_selection_or_final_fit() -> None:
    manifest, dataset, spec, config = _synthetic_case()
    runner = SklearnNestedCVLassoRunner(config)
    first_request = build_execution_request(spec, dataset, manifest)
    first = runner.execute(request=first_request, dataset=dataset, spec=spec)
    assert first is not None

    oos_ids = set(
        next(
            fold for fold in spec.plan.outer_folds if fold.fold_id == spec.plan.final_fold_id
        ).out_of_sample_row_ids
    )
    changed_rows = tuple(
        (
            replace(row, target_value=row.target_value + Decimal("1000"))
            if row.row_id in oos_ids
            else row
        )
        for row in dataset.rows
    )
    changed_dataset = replace(dataset, rows=changed_rows)
    changed_request = build_execution_request(spec, changed_dataset, manifest)
    changed = runner.execute(request=changed_request, dataset=changed_dataset, spec=spec)

    assert changed is not None
    assert tuple(
        (
            item.fold_id,
            item.selected_alpha,
            item.coefficients,
            item.concrete_fit,
        )
        for item in changed.fold_selections
    ) == tuple(
        (
            item.fold_id,
            item.selected_alpha,
            item.coefficients,
            item.concrete_fit,
        )
        for item in first.fold_selections
    )
    assert changed.result.evaluation.out_of_sample != first.result.evaluation.out_of_sample


def test_invalid_alpha_nan_and_constant_feature_fail_closed() -> None:
    manifest, dataset, spec, config = _synthetic_case()
    runner = SklearnNestedCVLassoRunner(config)
    request = build_execution_request(spec, dataset, manifest)

    object.__setattr__(request, "alpha_grid", (Decimal("0"), Decimal("0.1")))
    assert runner.execute(request=request, dataset=dataset, spec=spec) is None

    request = build_execution_request(spec, dataset, manifest)
    poisoned = dataset.rows[0].proxies[0]
    object.__setattr__(poisoned, "value", Decimal("NaN"))
    assert runner.execute(request=request, dataset=dataset, spec=spec) is None

    manifest, dataset, spec, config = _synthetic_case()
    constant_rows = tuple(
        replace(
            row,
            proxies=tuple(
                replace(proxy, value=Decimal("1")) if proxy.asset_code == "PROXY_B" else proxy
                for proxy in row.proxies
            ),
        )
        for row in dataset.rows
    )
    constant_dataset = replace(dataset, rows=constant_rows)
    constant_request = build_execution_request(spec, constant_dataset, manifest)
    assert (
        SklearnNestedCVLassoRunner(config).execute(
            request=constant_request,
            dataset=constant_dataset,
            spec=spec,
        )
        is None
    )


@pytest.mark.parametrize("field", ["benchmark_contract", "cost_model_contract"])
def test_benchmark_and_cost_identity_must_match_exact_governed_contract(field: str) -> None:
    manifest, dataset, spec, config = _synthetic_case()
    request = build_execution_request(spec, dataset, manifest)
    mismatched = replace(
        config,
        **{field: VersionedResearchContract("wrong-contract-v1", "9" * 64)},
    )

    assert (
        SklearnNestedCVLassoRunner(mismatched).execute(
            request=request,
            dataset=dataset,
            spec=spec,
        )
        is None
    )


def test_concrete_composition_records_only_with_complete_providers() -> None:
    manifest, dataset, spec, config = _synthetic_case()
    repository = _Repository()
    runtime = _build_concrete_lasso_runner_runtime_for_test(
        config=config,
        spec_provider=_SpecProvider(spec),
        manifest_provider=_ManifestProvider(manifest),
        dataset_provider=_DatasetProvider(dataset),
        repository=repository,
    )
    command = RunReproducibleMacroFactorCommand(
        expected_spec_id=spec.run_key,
        expected_spec_version=spec.run_version,
        expected_spec_hash=spec.content_hash,
        expected_manifest_id=manifest.manifest_id,
        expected_manifest_hash=manifest.manifest_hash,
        expected_manifest_content_hash=manifest.content_hash,
        expected_input_freshness_policy_version=(
            spec.input_knowledge_freshness_policy.policy_version
        ),
        expected_input_freshness_policy_hash=(spec.input_knowledge_freshness_policy.content_hash),
        expected_max_manifest_age_seconds=(
            spec.input_knowledge_freshness_policy.max_manifest_age_seconds
        ),
        expected_max_inference_age_seconds=(
            spec.input_knowledge_freshness_policy.max_inference_age_seconds
        ),
        expected_maximum_allowed_age_seconds=(
            spec.input_knowledge_freshness_policy.maximum_allowed_age_seconds
        ),
    )

    assessment = runtime.run.execute(command)

    assert assessment.status is MacroFactorRunnerStatus.RECORDED
    assert assessment.bundle is repository.bundle
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_execute is True

    unavailable_repository = _Repository()
    unavailable_runtime = build_concrete_lasso_runner_runtime()
    unavailable = unavailable_runtime.run.execute(command)
    assert unavailable.status is MacroFactorRunnerStatus.BLOCKED
    assert unavailable_repository.bundle is None
    assert tuple(signature(build_concrete_lasso_runner_runtime).parameters) == ("using",)
    assert not hasattr(unavailable_runtime.run, "__dict__")
    assert type(unavailable_runtime.run).__slots__ == ()
    assert unavailable_runtime.run.execute.__func__.__closure__ is None
    assert not hasattr(unavailable_runtime.ledger, "append_bundle")
    assert not hasattr(unavailable_runtime.ledger, "append_lifecycle_event")

    missing_spec_owner = _build_concrete_lasso_runner_runtime_for_test(
        config=config,
        spec_provider=None,
        manifest_provider=_ManifestProvider(manifest),
        dataset_provider=_DatasetProvider(dataset),
        repository=unavailable_repository,
    ).run.execute(command)
    assert missing_spec_owner.status is MacroFactorRunnerStatus.BLOCKED
    assert missing_spec_owner.blocked_reasons == (MacroFactorRunnerBlockerCode.RUN_INPUT_INVALID,)
    assert unavailable_repository.bundle is None

    malformed = unavailable_runtime.run.execute(object())  # type: ignore[arg-type]
    assert malformed.status is MacroFactorRunnerStatus.BLOCKED
    assert malformed.blocked_reasons == (MacroFactorRunnerBlockerCode.RUN_INPUT_INVALID,)
