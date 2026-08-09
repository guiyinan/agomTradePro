"""Immutable governance specification for macro-factor runner calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from apps.macro_factor.domain.entities import (
    MacroTargetDefinition,
    ProxyAssetDefinition,
    ReproducibilityEvidence,
    SampleWindow,
    TemporalSplitSpec,
    WalkForwardFold,
)

from ._runner_support import (
    decimal_text,
    hash_payload,
    require_aware,
    require_positive,
    require_sha256,
    require_token,
    utc_text,
)
from .baselines import FixedFMPDefinition, FixedFMPWeight
from .runner_inputs import (
    InferenceTargetCalendarPeriod,
    InputKnowledgeFreshnessPolicy,
    ResearchOutputValidityPolicy,
    VersionedResearchContract,
)
from .temporal_cv_contracts import NestedTemporalCVPlan


def _target_payload(target: MacroTargetDefinition) -> dict[str, object]:
    return {
        "target_code": target.target_code,
        "family": target.family.value,
        "output_role": target.output_role.value,
        "dataset_key": target.dataset_key,
        "business_key": target.business_key,
        "unit": target.unit,
        "frequency": target.frequency,
        "transformation_version": target.transformation_version,
        "horizon_periods": target.horizon_periods,
        "horizon_unit": target.horizon_unit,
    }


def _candidate_payload(candidate: ProxyAssetDefinition) -> dict[str, object]:
    return {
        "asset_code": candidate.asset_code,
        "dataset_key": candidate.dataset_key,
        "business_key": candidate.business_key,
        "kind": candidate.kind.value,
        "frequency": candidate.frequency,
        "transformation_version": candidate.transformation_version,
        "continuous_roll_policy_version": candidate.continuous_roll_policy_version,
    }


def _window_payload(window: SampleWindow) -> dict[str, str]:
    return {"start": window.start.isoformat(), "end": window.end.isoformat()}


def _temporal_split_payload(split: TemporalSplitSpec) -> dict[str, object]:
    return {
        "policy_version": split.policy_version,
        "training": _window_payload(split.training),
        "validation": _window_payload(split.validation),
        "out_of_sample": _window_payload(split.out_of_sample),
        "walk_forward_folds": [
            {
                "fold_id": fold.fold_id,
                "training": _window_payload(fold.training),
                "validation": _window_payload(fold.validation),
                "out_of_sample": _window_payload(fold.out_of_sample),
            }
            for fold in split.walk_forward_folds
        ],
        "embargo_days": split.embargo_days,
    }


def _validated_target(target: MacroTargetDefinition) -> MacroTargetDefinition:
    return MacroTargetDefinition(
        target_code=target.target_code,
        family=target.family,
        output_role=target.output_role,
        dataset_key=target.dataset_key,
        business_key=target.business_key,
        unit=target.unit,
        frequency=target.frequency,
        transformation_version=target.transformation_version,
        horizon_periods=target.horizon_periods,
        horizon_unit=target.horizon_unit,
    )


def _validated_candidate(candidate: ProxyAssetDefinition) -> ProxyAssetDefinition:
    return ProxyAssetDefinition(
        asset_code=candidate.asset_code,
        dataset_key=candidate.dataset_key,
        business_key=candidate.business_key,
        kind=candidate.kind,
        frequency=candidate.frequency,
        transformation_version=candidate.transformation_version,
        continuous_roll_policy_version=candidate.continuous_roll_policy_version,
    )


def _validated_temporal_split(split: TemporalSplitSpec) -> TemporalSplitSpec:
    return TemporalSplitSpec(
        policy_version=split.policy_version,
        training=SampleWindow(split.training.start, split.training.end),
        validation=SampleWindow(split.validation.start, split.validation.end),
        out_of_sample=SampleWindow(split.out_of_sample.start, split.out_of_sample.end),
        walk_forward_folds=tuple(
            WalkForwardFold(
                fold_id=fold.fold_id,
                training=SampleWindow(fold.training.start, fold.training.end),
                validation=SampleWindow(fold.validation.start, fold.validation.end),
                out_of_sample=SampleWindow(
                    fold.out_of_sample.start,
                    fold.out_of_sample.end,
                ),
            )
            for fold in split.walk_forward_folds
        ),
        embargo_days=split.embargo_days,
    )


def _validated_fixed_fmp(fixed_fmp: FixedFMPDefinition) -> FixedFMPDefinition:
    return FixedFMPDefinition(
        benchmark_version=fixed_fmp.benchmark_version,
        intercept=fixed_fmp.intercept,
        weights=tuple(
            FixedFMPWeight(asset_code=item.asset_code, weight=item.weight)
            for item in fixed_fmp.weights
        ),
        content_hash=fixed_fmp.content_hash,
    )


def calculate_temporal_split_hash(split: TemporalSplitSpec) -> str:
    """Seal the existing window-based split contract without changing its semantics."""

    def window_payload(start: date, end: date) -> dict[str, str]:
        return {"start": start.isoformat(), "end": end.isoformat()}

    return hash_payload(
        {
            "policy_version": split.policy_version,
            "training": window_payload(split.training.start, split.training.end),
            "validation": window_payload(split.validation.start, split.validation.end),
            "out_of_sample": window_payload(split.out_of_sample.start, split.out_of_sample.end),
            "walk_forward_folds": [
                {
                    "fold_id": fold.fold_id,
                    "training": window_payload(fold.training.start, fold.training.end),
                    "validation": window_payload(fold.validation.start, fold.validation.end),
                    "out_of_sample": window_payload(
                        fold.out_of_sample.start,
                        fold.out_of_sample.end,
                    ),
                }
                for fold in split.walk_forward_folds
            ],
            "embargo_days": split.embargo_days,
        }
    )


@dataclass(frozen=True)
class MacroFactorRunnerSpec:
    """Complete immutable governance input for one external runner call.

    The required validity policy is an in-memory research contract; introducing
    it does not add or migrate an ORM persistence schema.
    """

    run_key: str
    run_version: int
    factor_version: str
    expected_manifest_content_hash: str
    target: MacroTargetDefinition
    inference_target_period: InferenceTargetCalendarPeriod
    input_knowledge_freshness_policy: InputKnowledgeFreshnessPolicy
    candidates: tuple[ProxyAssetDefinition, ...]
    plan: NestedTemporalCVPlan
    temporal_split: TemporalSplitSpec
    historical_mean_benchmark: VersionedResearchContract
    fixed_fmp: FixedFMPDefinition
    cost_model: VersionedResearchContract
    split_contract: VersionedResearchContract
    selection_protocol: VersionedResearchContract
    metrics_protocol: VersionedResearchContract
    output_validity_policy: ResearchOutputValidityPolicy
    reproducibility: ReproducibilityEvidence
    random_seed: int
    calculated_at: datetime
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        require_token(self.run_key, "MacroFactorRunnerSpec.run_key")
        require_positive(self.run_version, "MacroFactorRunnerSpec.run_version")
        require_token(self.factor_version, "MacroFactorRunnerSpec.factor_version")
        require_sha256(
            self.expected_manifest_content_hash,
            "MacroFactorRunnerSpec.expected_manifest_content_hash",
        )
        require_aware(self.calculated_at, "MacroFactorRunnerSpec.calculated_at")
        _validated_target(self.target)
        tuple(_validated_candidate(item) for item in self.candidates)
        self.inference_target_period.validated_copy()
        self.input_knowledge_freshness_policy.validated_copy()
        self.plan.validated_copy()
        _validated_temporal_split(self.temporal_split)
        VersionedResearchContract(
            self.historical_mean_benchmark.version,
            self.historical_mean_benchmark.content_hash,
        )
        _validated_fixed_fmp(self.fixed_fmp)
        for contract in (
            self.cost_model,
            self.split_contract,
            self.selection_protocol,
            self.metrics_protocol,
        ):
            VersionedResearchContract(contract.version, contract.content_hash)
        self.output_validity_policy.validated_copy()
        ReproducibilityEvidence(
            code_version=self.reproducibility.code_version,
            dependency_lock_hash=self.reproducibility.dependency_lock_hash,
            parameter_version=self.reproducibility.parameter_version,
            parameter_hash=self.reproducibility.parameter_hash,
        )
        if any(
            fold.selection_as_of > self.calculated_at or fold.evaluation_as_of > self.calculated_at
            for fold in self.plan.outer_folds
        ):
            raise ValueError(
                "MacroFactorRunnerSpec.calculated_at cannot precede fold selection or "
                "evaluation evidence"
            )
        if type(self.random_seed) is not int or self.random_seed < 0:
            raise ValueError(
                "MacroFactorRunnerSpec.random_seed must be an integer and cannot be negative"
            )
        if not self.candidates:
            raise ValueError("MacroFactorRunnerSpec.candidates cannot be empty")
        candidate_codes = tuple(item.asset_code for item in self.candidates)
        if len(candidate_codes) != len(set(candidate_codes)):
            raise ValueError("MacroFactorRunnerSpec candidate identities must be unique")
        if frozenset(candidate_codes) != frozenset(
            item.asset_code for item in self.fixed_fmp.weights
        ):
            raise ValueError("fixed FMP must cover the exact candidate universe")
        timing = self.plan.timing
        if (
            timing.target_code != self.target.target_code
            or timing.output_role is not self.target.output_role
            or timing.horizon_periods != self.target.horizon_periods
            or timing.horizon_unit != self.target.horizon_unit
        ):
            raise ValueError("target availability policy does not match target definition")
        if self.plan.policy_version != self.split_contract.version:
            raise ValueError("nested plan and split contract versions must match")
        if (
            self.temporal_split.policy_version != self.split_contract.version
            or calculate_temporal_split_hash(self.temporal_split)
            != self.split_contract.content_hash
        ):
            raise ValueError("typed temporal split does not match split contract identity")
        if frozenset(item.fold_id for item in self.plan.outer_folds) != frozenset(
            item.fold_id for item in self.temporal_split.walk_forward_folds
        ):
            raise ValueError("nested plan must cover every typed walk-forward fold exactly")
        object.__setattr__(self, "content_hash", hash_payload(self.canonical_payload))

    @property
    def canonical_payload(self) -> dict[str, object]:
        """Return the complete preregistered runner specification."""

        return {
            "schema": "macro-factor-runner-spec.v1",
            "run_key": self.run_key,
            "run_version": self.run_version,
            "factor_version": self.factor_version,
            "expected_manifest_content_hash": self.expected_manifest_content_hash.lower(),
            "target": _target_payload(self.target),
            "inference_target_period": self.inference_target_period.canonical_payload(),
            "input_knowledge_freshness_policy": {
                **self.input_knowledge_freshness_policy.canonical_payload(),
                "content_hash": self.input_knowledge_freshness_policy.content_hash.lower(),
            },
            "candidates": [_candidate_payload(item) for item in self.candidates],
            "plan": {
                **self.plan.canonical_payload,
                "content_hash": self.plan.content_hash,
            },
            "temporal_split": {
                **_temporal_split_payload(self.temporal_split),
                "content_hash": calculate_temporal_split_hash(self.temporal_split),
            },
            "historical_mean_benchmark": {
                "version": self.historical_mean_benchmark.version,
                "content_hash": self.historical_mean_benchmark.content_hash.lower(),
            },
            "fixed_fmp": {
                "benchmark_version": self.fixed_fmp.benchmark_version,
                "intercept": decimal_text(self.fixed_fmp.intercept),
                "weights": [
                    {
                        "asset_code": item.asset_code,
                        "weight": decimal_text(item.weight),
                    }
                    for item in sorted(
                        self.fixed_fmp.weights,
                        key=lambda value: value.asset_code,
                    )
                ],
                "content_hash": self.fixed_fmp.content_hash.lower(),
            },
            "cost_model": {
                "version": self.cost_model.version,
                "content_hash": self.cost_model.content_hash.lower(),
            },
            "split_contract": {
                "version": self.split_contract.version,
                "content_hash": self.split_contract.content_hash.lower(),
            },
            "selection_protocol": {
                "version": self.selection_protocol.version,
                "content_hash": self.selection_protocol.content_hash.lower(),
            },
            "metrics_protocol": {
                "version": self.metrics_protocol.version,
                "content_hash": self.metrics_protocol.content_hash.lower(),
            },
            "output_validity_policy": {
                **self.output_validity_policy.canonical_payload(),
                "content_hash": self.output_validity_policy.content_hash.lower(),
            },
            "reproducibility": {
                "code_version": self.reproducibility.code_version,
                "dependency_lock_hash": self.reproducibility.dependency_lock_hash.lower(),
                "parameter_version": self.reproducibility.parameter_version,
                "parameter_hash": self.reproducibility.parameter_hash.lower(),
            },
            "random_seed": self.random_seed,
            "calculated_at": utc_text(self.calculated_at),
        }

    def validated_copy(self) -> MacroFactorRunnerSpec:
        """Reconstruct mutable-at-runtime nested policies before orchestration."""

        require_sha256(self.content_hash, "MacroFactorRunnerSpec.content_hash")
        validated = MacroFactorRunnerSpec(
            run_key=self.run_key,
            run_version=self.run_version,
            factor_version=self.factor_version,
            expected_manifest_content_hash=self.expected_manifest_content_hash,
            target=_validated_target(self.target),
            inference_target_period=self.inference_target_period.validated_copy(),
            input_knowledge_freshness_policy=(
                self.input_knowledge_freshness_policy.validated_copy()
            ),
            candidates=tuple(_validated_candidate(item) for item in self.candidates),
            plan=self.plan.validated_copy(),
            temporal_split=_validated_temporal_split(self.temporal_split),
            historical_mean_benchmark=VersionedResearchContract(
                self.historical_mean_benchmark.version,
                self.historical_mean_benchmark.content_hash,
            ),
            fixed_fmp=_validated_fixed_fmp(self.fixed_fmp),
            cost_model=VersionedResearchContract(
                self.cost_model.version,
                self.cost_model.content_hash,
            ),
            split_contract=VersionedResearchContract(
                self.split_contract.version,
                self.split_contract.content_hash,
            ),
            selection_protocol=VersionedResearchContract(
                self.selection_protocol.version,
                self.selection_protocol.content_hash,
            ),
            metrics_protocol=VersionedResearchContract(
                self.metrics_protocol.version,
                self.metrics_protocol.content_hash,
            ),
            output_validity_policy=self.output_validity_policy.validated_copy(),
            reproducibility=ReproducibilityEvidence(
                code_version=self.reproducibility.code_version,
                dependency_lock_hash=self.reproducibility.dependency_lock_hash,
                parameter_version=self.reproducibility.parameter_version,
                parameter_hash=self.reproducibility.parameter_hash,
            ),
            random_seed=self.random_seed,
            calculated_at=self.calculated_at,
        )
        if self.content_hash.lower() != validated.content_hash.lower():
            raise ValueError("MacroFactorRunnerSpec.content_hash does not match content")
        return validated


__all__ = ["MacroFactorRunnerSpec", "calculate_temporal_split_hash"]
