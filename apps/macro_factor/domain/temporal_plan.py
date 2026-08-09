"""Nested temporal-CV plan and exact external-runner request manifest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum

from apps.macro_factor.domain.entities import (
    FactorOutputRole,
    MacroTargetDefinition,
    PITManifestEvidence,
    ProxyAssetDefinition,
    ReproducibilityEvidence,
    TemporalSplitSpec,
)

from ._runner_support import (
    decimal_text,
    hash_payload,
    require_aware,
    require_finite,
    require_positive,
    require_sha256,
    require_token,
    utc_text,
)
from .baselines import FixedFMPDefinition
from .runner_inputs import (
    InferenceTargetCalendarPeriod,
    InputKnowledgeFreshnessPolicy,
    PITResearchDataset,
    PITResearchRow,
    ResearchOutputValidityPolicy,
    VersionedResearchContract,
)


@dataclass(frozen=True)
class TargetAvailabilityPolicy:
    """Versioned conversion from target horizon to purge/embargo days."""

    policy_version: str
    target_code: str
    output_role: FactorOutputRole
    horizon_periods: int
    horizon_unit: str
    normalized_horizon_days: int
    label_availability_lag_days: int
    purge_days: int
    embargo_days: int
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        policy_version: str,
        target_code: str,
        output_role: FactorOutputRole,
        horizon_periods: int,
        horizon_unit: str,
        normalized_horizon_days: int,
        label_availability_lag_days: int,
        purge_days: int,
        embargo_days: int,
    ) -> TargetAvailabilityPolicy:
        """Build a policy with a canonical content hash."""

        payload = cls._payload(
            policy_version=policy_version,
            target_code=target_code,
            output_role=output_role,
            horizon_periods=horizon_periods,
            horizon_unit=horizon_unit,
            normalized_horizon_days=normalized_horizon_days,
            label_availability_lag_days=label_availability_lag_days,
            purge_days=purge_days,
            embargo_days=embargo_days,
        )
        return cls(
            policy_version=policy_version,
            target_code=target_code,
            output_role=output_role,
            horizon_periods=horizon_periods,
            horizon_unit=horizon_unit,
            normalized_horizon_days=normalized_horizon_days,
            label_availability_lag_days=label_availability_lag_days,
            purge_days=purge_days,
            embargo_days=embargo_days,
            content_hash=hash_payload(payload),
        )

    @staticmethod
    def _payload(
        *,
        policy_version: str,
        target_code: str,
        output_role: FactorOutputRole,
        horizon_periods: int,
        horizon_unit: str,
        normalized_horizon_days: int,
        label_availability_lag_days: int,
        purge_days: int,
        embargo_days: int,
    ) -> dict[str, object]:
        return {
            "policy_version": policy_version,
            "target_code": target_code,
            "output_role": output_role.value,
            "horizon_periods": horizon_periods,
            "horizon_unit": horizon_unit,
            "normalized_horizon_days": normalized_horizon_days,
            "label_availability_lag_days": label_availability_lag_days,
            "purge_days": purge_days,
            "embargo_days": embargo_days,
        }

    def __post_init__(self) -> None:
        require_token(self.policy_version, "TargetAvailabilityPolicy.policy_version")
        require_token(self.target_code, "TargetAvailabilityPolicy.target_code")
        if not isinstance(self.output_role, FactorOutputRole):
            raise ValueError("TargetAvailabilityPolicy.output_role is invalid")
        require_token(self.horizon_unit, "TargetAvailabilityPolicy.horizon_unit")
        if isinstance(self.horizon_periods, bool) or self.horizon_periods < 0:
            raise ValueError("TargetAvailabilityPolicy.horizon_periods cannot be negative")
        if self.output_role is FactorOutputRole.CURRENT_STATE and self.horizon_periods != 0:
            raise ValueError("current-state availability requires horizon_periods=0")
        if self.output_role is FactorOutputRole.FORWARD_EXPECTATION and self.horizon_periods == 0:
            raise ValueError("forward availability requires a positive horizon")
        if self.output_role is FactorOutputRole.CURRENT_STATE:
            if self.normalized_horizon_days != 0:
                raise ValueError("current-state normalized horizon must be zero")
        else:
            require_positive(
                self.normalized_horizon_days,
                "TargetAvailabilityPolicy.normalized_horizon_days",
            )
        if (
            isinstance(self.label_availability_lag_days, bool)
            or self.label_availability_lag_days < 0
        ):
            raise ValueError("label_availability_lag_days cannot be negative")
        required_gap = max(self.normalized_horizon_days, self.label_availability_lag_days)
        if self.purge_days < required_gap:
            raise ValueError("purge_days must cover target horizon and label availability")
        if self.embargo_days < required_gap:
            raise ValueError("embargo_days must cover target horizon and label availability")
        require_sha256(self.content_hash, "TargetAvailabilityPolicy.content_hash")
        expected = hash_payload(
            self._payload(
                policy_version=self.policy_version,
                target_code=self.target_code,
                output_role=self.output_role,
                horizon_periods=self.horizon_periods,
                horizon_unit=self.horizon_unit,
                normalized_horizon_days=self.normalized_horizon_days,
                label_availability_lag_days=self.label_availability_lag_days,
                purge_days=self.purge_days,
                embargo_days=self.embargo_days,
            )
        )
        if self.content_hash.lower() != expected:
            raise ValueError("TargetAvailabilityPolicy.content_hash does not match content")

    def validated_copy(self) -> TargetAvailabilityPolicy:
        """Reconstruct the policy so its horizon, gaps, and seal are checked live."""

        return TargetAvailabilityPolicy(
            policy_version=self.policy_version,
            target_code=self.target_code,
            output_role=self.output_role,
            horizon_periods=self.horizon_periods,
            horizon_unit=self.horizon_unit,
            normalized_horizon_days=self.normalized_horizon_days,
            label_availability_lag_days=self.label_availability_lag_days,
            purge_days=self.purge_days,
            embargo_days=self.embargo_days,
            content_hash=self.content_hash,
        )


def _validate_row_ids(values: tuple[str, ...], label: str) -> None:
    if not values:
        raise ValueError(f"{label} row IDs cannot be empty")
    for row_id in values:
        require_token(row_id, f"{label} row_id")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} row IDs must be unique")


@dataclass(frozen=True)
class InnerTemporalFoldPlan:
    """Planned inner selection fold; it is not selection evidence."""

    fold_id: str
    training_row_ids: tuple[str, ...]
    validation_row_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        require_token(self.fold_id, "InnerTemporalFoldPlan.fold_id")
        _validate_row_ids(self.training_row_ids, "inner training")
        _validate_row_ids(self.validation_row_ids, "inner validation")
        if set(self.training_row_ids) & set(self.validation_row_ids):
            raise ValueError("inner training and validation rows must be disjoint")

    def validated_copy(self) -> InnerTemporalFoldPlan:
        """Reconstruct an inner fold before numerical selection."""

        return InnerTemporalFoldPlan(
            fold_id=self.fold_id,
            training_row_ids=self.training_row_ids,
            validation_row_ids=self.validation_row_ids,
        )


@dataclass(frozen=True)
class OuterTemporalFoldPlan:
    """Planned outer OOS evaluation with strictly internal inner selection."""

    fold_id: str
    training_row_ids: tuple[str, ...]
    validation_row_ids: tuple[str, ...]
    out_of_sample_row_ids: tuple[str, ...]
    selection_as_of: datetime
    evaluation_as_of: datetime
    inner_folds: tuple[InnerTemporalFoldPlan, ...]

    def __post_init__(self) -> None:
        require_token(self.fold_id, "OuterTemporalFoldPlan.fold_id")
        _validate_row_ids(self.training_row_ids, "outer training")
        _validate_row_ids(self.validation_row_ids, "outer validation")
        _validate_row_ids(self.out_of_sample_row_ids, "outer out-of-sample")
        require_aware(self.selection_as_of, "OuterTemporalFoldPlan.selection_as_of")
        require_aware(self.evaluation_as_of, "OuterTemporalFoldPlan.evaluation_as_of")
        if self.evaluation_as_of <= self.selection_as_of:
            raise ValueError("outer evaluation must follow selection")
        oos = set(self.out_of_sample_row_ids)
        training = set(self.training_row_ids)
        validation = set(self.validation_row_ids)
        if training & validation or training & oos or validation & oos:
            raise ValueError("outer training, validation, and out-of-sample rows must be disjoint")
        if len(self.inner_folds) < 2:
            raise ValueError("nested CV requires at least two inner folds")
        inner_ids = tuple(item.fold_id for item in self.inner_folds)
        if len(inner_ids) != len(set(inner_ids)):
            raise ValueError("inner fold identities must be unique")
        for inner in self.inner_folds:
            used = set(inner.training_row_ids) | set(inner.validation_row_ids)
            if not used.issubset(training):
                if used & oos:
                    raise ValueError("outer out-of-sample rows cannot enter inner selection")
                raise ValueError("inner folds must be contained in outer training rows")

    def validated_copy(self) -> OuterTemporalFoldPlan:
        """Reconstruct membership and chronology for one complete outer fold."""

        return OuterTemporalFoldPlan(
            fold_id=self.fold_id,
            training_row_ids=self.training_row_ids,
            validation_row_ids=self.validation_row_ids,
            out_of_sample_row_ids=self.out_of_sample_row_ids,
            selection_as_of=self.selection_as_of,
            evaluation_as_of=self.evaluation_as_of,
            inner_folds=tuple(item.validated_copy() for item in self.inner_folds),
        )


class OptimizationDirection(str, Enum):  # noqa: UP042 -- preserve legacy string semantics
    """Governed direction for deterministic inner-score selection."""

    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


@dataclass(frozen=True)
class NestedTemporalCVPlan:
    """Predeclared nested temporal-CV plan, never claimed as observed evidence."""

    policy_version: str
    timing: TargetAvailabilityPolicy
    alpha_grid: tuple[Decimal, ...]
    optimization_metric: str
    optimization_direction: OptimizationDirection
    outer_folds: tuple[OuterTemporalFoldPlan, ...]
    final_fold_id: str

    def __post_init__(self) -> None:
        require_token(self.policy_version, "NestedTemporalCVPlan.policy_version")
        if len(self.outer_folds) < 2:
            raise ValueError("nested CV requires at least two outer folds")
        fold_ids = tuple(item.fold_id for item in self.outer_folds)
        if len(fold_ids) != len(set(fold_ids)):
            raise ValueError("outer fold identities must be unique")
        require_token(self.final_fold_id, "NestedTemporalCVPlan.final_fold_id")
        if self.final_fold_id not in fold_ids:
            raise ValueError("nested CV final fold must reference one exact outer fold")
        all_oos_ids = tuple(
            row_id for fold in self.outer_folds for row_id in fold.out_of_sample_row_ids
        )
        if len(all_oos_ids) != len(set(all_oos_ids)):
            raise ValueError("outer out-of-sample row identities must be globally unique")
        if not self.alpha_grid:
            raise ValueError("NestedTemporalCVPlan.alpha_grid cannot be empty")
        for alpha in self.alpha_grid:
            require_finite(alpha, "NestedTemporalCVPlan.alpha")
            if alpha <= 0:
                raise ValueError("NestedTemporalCVPlan alpha values must be positive")
        if len(self.alpha_grid) != len(set(self.alpha_grid)):
            raise ValueError("NestedTemporalCVPlan alpha values must be unique")
        require_token(self.optimization_metric, "NestedTemporalCVPlan.optimization_metric")
        if not isinstance(self.optimization_direction, OptimizationDirection):
            raise ValueError("NestedTemporalCVPlan.optimization_direction is invalid")

    @property
    def canonical_payload(self) -> dict[str, object]:
        """Return stable planned folds, row identities, cutoffs, and policy hashes."""

        return {
            "policy_version": self.policy_version,
            "timing_policy_version": self.timing.policy_version,
            "timing_policy_hash": self.timing.content_hash,
            "alpha_grid": [decimal_text(item) for item in self.alpha_grid],
            "optimization_metric": self.optimization_metric,
            "optimization_direction": self.optimization_direction.value,
            "final_fold_id": self.final_fold_id,
            "outer_folds": [
                {
                    "fold_id": outer.fold_id,
                    "training_row_ids": list(outer.training_row_ids),
                    "validation_row_ids": list(outer.validation_row_ids),
                    "out_of_sample_row_ids": list(outer.out_of_sample_row_ids),
                    "selection_as_of": utc_text(outer.selection_as_of),
                    "evaluation_as_of": utc_text(outer.evaluation_as_of),
                    "inner_folds": [
                        {
                            "fold_id": inner.fold_id,
                            "training_row_ids": list(inner.training_row_ids),
                            "validation_row_ids": list(inner.validation_row_ids),
                        }
                        for inner in outer.inner_folds
                    ],
                }
                for outer in self.outer_folds
            ],
        }

    @property
    def content_hash(self) -> str:
        """Return the exact plan hash."""

        return hash_payload(self.canonical_payload)

    def validated_copy(self) -> NestedTemporalCVPlan:
        """Reconstruct timing and every fold before an execution request."""

        return NestedTemporalCVPlan(
            policy_version=self.policy_version,
            timing=self.timing.validated_copy(),
            alpha_grid=self.alpha_grid,
            optimization_metric=self.optimization_metric,
            optimization_direction=self.optimization_direction,
            outer_folds=tuple(item.validated_copy() for item in self.outer_folds),
            final_fold_id=self.final_fold_id,
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

    def __post_init__(self) -> None:
        require_token(self.run_key, "MacroFactorRunnerSpec.run_key")
        require_positive(self.run_version, "MacroFactorRunnerSpec.run_version")
        require_token(self.factor_version, "MacroFactorRunnerSpec.factor_version")
        require_sha256(
            self.expected_manifest_content_hash,
            "MacroFactorRunnerSpec.expected_manifest_content_hash",
        )
        require_aware(self.calculated_at, "MacroFactorRunnerSpec.calculated_at")
        self.inference_target_period.validated_copy()
        self.input_knowledge_freshness_policy.validated_copy()
        self.output_validity_policy.validated_copy()
        if any(
            fold.selection_as_of > self.calculated_at or fold.evaluation_as_of > self.calculated_at
            for fold in self.plan.outer_folds
        ):
            raise ValueError(
                "MacroFactorRunnerSpec.calculated_at cannot precede fold selection or "
                "evaluation evidence"
            )
        if isinstance(self.random_seed, bool) or self.random_seed < 0:
            raise ValueError("MacroFactorRunnerSpec.random_seed cannot be negative")
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

    def validated_copy(self) -> MacroFactorRunnerSpec:
        """Reconstruct mutable-at-runtime nested policies before orchestration."""

        return MacroFactorRunnerSpec(
            run_key=self.run_key,
            run_version=self.run_version,
            factor_version=self.factor_version,
            expected_manifest_content_hash=self.expected_manifest_content_hash,
            target=self.target,
            inference_target_period=self.inference_target_period.validated_copy(),
            input_knowledge_freshness_policy=(
                self.input_knowledge_freshness_policy.validated_copy()
            ),
            candidates=self.candidates,
            plan=self.plan.validated_copy(),
            temporal_split=self.temporal_split,
            historical_mean_benchmark=self.historical_mean_benchmark,
            fixed_fmp=self.fixed_fmp,
            cost_model=self.cost_model,
            split_contract=self.split_contract,
            selection_protocol=self.selection_protocol,
            metrics_protocol=self.metrics_protocol,
            output_validity_policy=self.output_validity_policy.validated_copy(),
            reproducibility=self.reproducibility,
            random_seed=self.random_seed,
            calculated_at=self.calculated_at,
        )


@dataclass(frozen=True)
class InnerFoldBinding:
    """Exact row binding for one inner fold inside an execution request."""

    fold_id: str
    training_row_ids: tuple[str, ...]
    validation_row_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionFoldBinding:
    """Manifest and design seal for one outer execution fold."""

    fold_id: str
    manifest_id: str
    manifest_hash: str
    outer_training_row_ids: tuple[str, ...]
    outer_validation_row_ids: tuple[str, ...]
    outer_oos_row_ids: tuple[str, ...]
    inner_folds: tuple[InnerFoldBinding, ...]
    selection_as_of: datetime
    evaluation_as_of: datetime
    design_hash: str

    def canonical_payload(self) -> dict[str, object]:
        """Return stable fold request content."""

        return {
            "fold_id": self.fold_id,
            "manifest_id": self.manifest_id,
            "manifest_hash": self.manifest_hash,
            "outer_training_row_ids": list(self.outer_training_row_ids),
            "outer_validation_row_ids": list(self.outer_validation_row_ids),
            "outer_oos_row_ids": list(self.outer_oos_row_ids),
            "inner_folds": [
                {
                    "fold_id": item.fold_id,
                    "training_row_ids": list(item.training_row_ids),
                    "validation_row_ids": list(item.validation_row_ids),
                }
                for item in self.inner_folds
            ],
            "selection_as_of": utc_text(self.selection_as_of),
            "evaluation_as_of": utc_text(self.evaluation_as_of),
            "design_hash": self.design_hash,
        }


@dataclass(frozen=True)
class NestedCVExecutionRequest:
    """Typed external-runner request with no execution implementation."""

    run_key: str
    run_version: int
    factor_version: str
    target_code: str
    candidate_asset_codes: tuple[str, ...]
    pit_manifest_id: str
    pit_manifest_hash: str
    pit_manifest_content_hash: str
    dataset_hash: str
    inference_row_id: str
    inference_row_hash: str
    inference_target_period_id: str
    inference_target_calendar_id: str
    inference_target_calendar_version: str
    inference_target_calendar_hash: str
    inference_target_period_hash: str
    plan_version: str
    plan_hash: str
    benchmark_version: str
    benchmark_hash: str
    fixed_fmp_version: str
    fixed_fmp_hash: str
    cost_model_version: str
    cost_model_hash: str
    split_contract_version: str
    split_contract_hash: str
    selection_protocol_version: str
    selection_protocol_hash: str
    metrics_protocol_version: str
    metrics_protocol_hash: str
    output_validity_policy_version: str
    output_validity_policy_hash: str
    output_valid_for_seconds: int
    output_maximum_valid_for_seconds: int
    input_freshness_policy_version: str
    input_freshness_policy_hash: str
    max_manifest_age_seconds: int
    max_inference_age_seconds: int
    maximum_allowed_input_age_seconds: int
    manifest_fresh_until: datetime
    inference_fresh_until: datetime
    timing_policy_version: str
    timing_policy_hash: str
    code_version: str
    dependency_lock_hash: str
    parameter_version: str
    parameter_hash: str
    random_seed: int
    calculated_at: datetime
    alpha_grid: tuple[Decimal, ...]
    optimization_metric: str
    optimization_direction: OptimizationDirection
    final_fold_id: str
    folds: tuple[ExecutionFoldBinding, ...]

    @property
    def canonical_payload(self) -> dict[str, object]:
        """Return the full request manifest consumed by the external runner."""

        return {
            "run_key": self.run_key,
            "run_version": self.run_version,
            "factor_version": self.factor_version,
            "target_code": self.target_code,
            "candidate_asset_codes": list(self.candidate_asset_codes),
            "pit_manifest_id": self.pit_manifest_id,
            "pit_manifest_hash": self.pit_manifest_hash,
            "pit_manifest_content_hash": self.pit_manifest_content_hash,
            "dataset_hash": self.dataset_hash,
            "inference": {
                "row_id": self.inference_row_id,
                "row_hash": self.inference_row_hash,
                "target_period_id": self.inference_target_period_id,
                "target_calendar_id": self.inference_target_calendar_id,
                "target_calendar_version": self.inference_target_calendar_version,
                "target_calendar_hash": self.inference_target_calendar_hash,
                "target_period_hash": self.inference_target_period_hash,
            },
            "plan_version": self.plan_version,
            "plan_hash": self.plan_hash,
            "benchmark": {"version": self.benchmark_version, "hash": self.benchmark_hash},
            "fixed_fmp": {"version": self.fixed_fmp_version, "hash": self.fixed_fmp_hash},
            "cost_model": {"version": self.cost_model_version, "hash": self.cost_model_hash},
            "split_contract": {
                "version": self.split_contract_version,
                "hash": self.split_contract_hash,
            },
            "selection_protocol": {
                "version": self.selection_protocol_version,
                "hash": self.selection_protocol_hash,
            },
            "metrics_protocol": {
                "version": self.metrics_protocol_version,
                "hash": self.metrics_protocol_hash,
            },
            "output_validity_policy": {
                "version": self.output_validity_policy_version,
                "hash": self.output_validity_policy_hash,
                "valid_for_seconds": self.output_valid_for_seconds,
                "maximum_valid_for_seconds": self.output_maximum_valid_for_seconds,
            },
            "input_knowledge_freshness_policy": {
                "version": self.input_freshness_policy_version,
                "hash": self.input_freshness_policy_hash,
                "max_manifest_age_seconds": self.max_manifest_age_seconds,
                "max_inference_age_seconds": self.max_inference_age_seconds,
                "maximum_allowed_age_seconds": self.maximum_allowed_input_age_seconds,
                "manifest_fresh_until": utc_text(self.manifest_fresh_until),
                "inference_fresh_until": utc_text(self.inference_fresh_until),
            },
            "timing_policy": {
                "version": self.timing_policy_version,
                "hash": self.timing_policy_hash,
            },
            "reproducibility": {
                "code_version": self.code_version,
                "dependency_lock_hash": self.dependency_lock_hash,
                "parameter_version": self.parameter_version,
                "parameter_hash": self.parameter_hash,
                "random_seed": self.random_seed,
            },
            "calculated_at": utc_text(self.calculated_at),
            "alpha_grid": [decimal_text(item) for item in self.alpha_grid],
            "optimization_metric": self.optimization_metric,
            "optimization_direction": self.optimization_direction.value,
            "final_fold_id": self.final_fold_id,
            "folds": [item.canonical_payload() for item in self.folds],
            "research_only": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }

    @property
    def content_hash(self) -> str:
        """Return the exact external-runner request hash."""

        return hash_payload(self.canonical_payload)


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


def _validate_manifest_scope(
    spec: MacroFactorRunnerSpec,
    dataset: PITResearchDataset,
    manifest: PITManifestEvidence,
) -> None:
    if (
        dataset.manifest_id != manifest.manifest_id
        or dataset.manifest_hash.lower() != manifest.manifest_hash.lower()
        or dataset.manifest_content_hash.lower() != manifest.content_hash.lower()
        or dataset.manifest_as_of != manifest.as_of_time
        or spec.expected_manifest_content_hash.lower() != manifest.content_hash.lower()
    ):
        raise ValueError("dataset does not match the exact PIT manifest")
    if not manifest.is_complete:
        raise ValueError("PIT manifest must be complete and verified")
    if dataset.target_code != spec.target.target_code:
        raise ValueError("dataset target does not match runner target")
    candidate_codes = tuple(item.asset_code for item in spec.candidates)
    if dataset.candidate_asset_codes != candidate_codes:
        raise ValueError("dataset candidate order does not match runner candidates")
    required = {
        (spec.target.dataset_key, spec.target.business_key),
        *((item.dataset_key, item.business_key) for item in spec.candidates),
    }
    if not required.issubset(manifest.slice_identities):
        raise ValueError("PIT manifest does not cover target and candidate scopes")
    slices = {(item.dataset_key, item.business_key): item for item in manifest.slices}
    target_slice = slices[(spec.target.dataset_key, spec.target.business_key)]
    candidates_by_code = {item.asset_code: item for item in spec.candidates}
    seen_target_versions: set[int] = set()
    seen_proxy_versions: dict[str, set[int]] = {item.asset_code: set() for item in spec.candidates}
    for row in dataset.rows:
        if (
            row.available_at > dataset.manifest_as_of
            or row.label_available_at > dataset.manifest_as_of
        ):
            raise ValueError("PIT design row exceeds manifest knowledge time")
        target_selected = target_slice.selected_by_id.get(row.target_fact_version.version_id)
        if target_selected != row.target_fact_version:
            raise ValueError(
                f"PIT row {row.row_id} target fact is not an exact manifest-selected version"
            )
        if row.target_fact_version.version_id in seen_target_versions:
            raise ValueError("PIT target fact version cannot be reused across design rows")
        seen_target_versions.add(row.target_fact_version.version_id)
        for observation in row.proxies:
            candidate = candidates_by_code[observation.asset_code]
            selected_slice = slices[(candidate.dataset_key, candidate.business_key)]
            selected = selected_slice.selected_by_id.get(observation.fact_version.version_id)
            if selected != observation.fact_version:
                raise ValueError(
                    f"PIT row {row.row_id} proxy fact is not an exact manifest-selected version"
                )
            seen = seen_proxy_versions[observation.asset_code]
            if observation.fact_version.version_id in seen:
                raise ValueError("PIT proxy fact version cannot be reused across design rows")
            seen.add(observation.fact_version.version_id)
    inference = dataset.inference_row
    if inference is None:
        raise ValueError("one label-free inference row is required")
    for observation in inference.proxies:
        candidate = candidates_by_code[observation.asset_code]
        selected_slice = slices[(candidate.dataset_key, candidate.business_key)]
        selected = selected_slice.selected_by_id.get(observation.fact_version.version_id)
        if selected != observation.fact_version:
            raise ValueError("inference proxy fact is not an exact manifest-selected version")
        if observation.fact_version.version_id in seen_proxy_versions[observation.asset_code]:
            raise ValueError("inference proxy fact cannot alias a design-row fact version")
        if observation.fact_version.available_at > dataset.manifest_as_of:
            raise ValueError("inference proxy fact exceeds manifest knowledge time")


def _validate_inference_calendar_member(
    *,
    target_period: InferenceTargetCalendarPeriod,
    manifest: PITManifestEvidence,
) -> None:
    """Require the inference period to equal one owner-sealed manifest member."""

    members = tuple(
        item for item in manifest.inference_periods if item.period_id == target_period.period_id
    )
    if len(members) != 1:
        raise ValueError("inference target period is not a unique PIT manifest member")
    member = members[0]
    if (
        target_period.calendar_id != manifest.calendar_id
        or target_period.calendar_version != manifest.calendar_version
        or target_period.calendar_hash.lower() != manifest.calendar_hash.lower()
        or member.calendar_id != target_period.calendar_id
        or member.calendar_version != target_period.calendar_version
        or member.calendar_hash.lower() != target_period.calendar_hash.lower()
        or member.period_start != target_period.period_start
        or member.period_end != target_period.period_end
        or member.content_hash.lower() != target_period.content_hash.lower()
    ):
        raise ValueError("inference target period does not equal its PIT manifest member")


def _validate_run_chronology(
    spec: MacroFactorRunnerSpec,
    dataset: PITResearchDataset,
    manifest: PITManifestEvidence,
) -> None:
    """Revalidate every owner/run clock immediately before numerical execution."""

    if manifest.as_of_time > spec.calculated_at:
        raise ValueError("PIT manifest cannot be known after runner calculated_at")
    if dataset.manifest_as_of > spec.calculated_at:
        raise ValueError("PIT dataset cannot be known after runner calculated_at")
    if any(
        fold.selection_as_of > spec.calculated_at or fold.evaluation_as_of > spec.calculated_at
        for fold in spec.plan.outer_folds
    ):
        raise ValueError(
            "runner calculated_at cannot precede fold selection or evaluation evidence"
        )
    if any(
        version.available_at > manifest.as_of_time
        for dataset_slice in manifest.slices
        for version in dataset_slice.selected_versions
    ):
        raise ValueError("PIT manifest contains a future selected fact version")


def _rows_for(
    row_ids: tuple[str, ...],
    rows_by_id: dict[str, PITResearchRow],
    label: str,
) -> tuple[PITResearchRow, ...]:
    try:
        return tuple(rows_by_id[row_id] for row_id in row_ids)
    except KeyError as exc:
        raise ValueError(f"{label} references an unknown PIT row") from exc


def _validate_gap(
    earlier: tuple[PITResearchRow, ...],
    later: tuple[PITResearchRow, ...],
    minimum_days: int,
    label: str,
) -> None:
    latest_target = max(item.target_period_end for item in earlier)
    earliest_observation = min(item.observation_date for item in later)
    if latest_target + timedelta(days=minimum_days) >= earliest_observation:
        raise ValueError(f"{label} lacks required purge/embargo interval")


def _validate_rows_in_window(
    rows: tuple[PITResearchRow, ...],
    *,
    start: date,
    end: date,
    label: str,
) -> None:
    if any(not start <= row.observation_date <= end for row in rows):
        raise ValueError(f"{label} rows fall outside typed temporal split window")


def _validate_fact_cutoff(
    rows: tuple[PITResearchRow, ...],
    *,
    cutoff: datetime,
    label: str,
) -> None:
    """Check every target and proxy fact clock, not only cached row summaries."""

    if any(
        row.target_fact_version.available_at > cutoff
        or any(item.fact_version.available_at > cutoff for item in row.proxies)
        for row in rows
    ):
        raise ValueError(f"{label} contains a fact unavailable at its cutoff")


def build_execution_request(
    spec: MacroFactorRunnerSpec,
    dataset: PITResearchDataset,
    manifest: PITManifestEvidence,
) -> NestedCVExecutionRequest:
    """Build and validate a nested-CV request from manifest-bound in-memory rows."""

    spec = spec.validated_copy()
    dataset = dataset.validated_copy()
    manifest = manifest.validated_copy()
    validity_policy = spec.output_validity_policy.validated_copy()
    _validate_run_chronology(spec, dataset, manifest)
    _validate_manifest_scope(spec, dataset, manifest)
    inference = dataset.inference_row
    if inference is None:
        raise ValueError("one label-free inference row is required")
    target_period = inference.target_period
    if target_period != spec.inference_target_period:
        raise ValueError("inference target period does not match preregistered runner spec")
    _validate_inference_calendar_member(target_period=target_period, manifest=manifest)
    freshness_policy = spec.input_knowledge_freshness_policy.validated_copy()
    manifest_fresh_until = freshness_policy.manifest_expires_at(manifest.as_of_time)
    inference_fresh_until = freshness_policy.inference_expires_at(inference.available_at)
    if spec.calculated_at > manifest_fresh_until:
        raise ValueError("PIT manifest knowledge is stale at calculated_at")
    if spec.calculated_at > inference_fresh_until:
        raise ValueError("PIT inference knowledge is stale at calculated_at")
    output_valid_until = validity_policy.valid_until(spec.calculated_at)
    if output_valid_until > manifest_fresh_until:
        raise ValueError("output validity exceeds PIT manifest freshness")
    if output_valid_until > inference_fresh_until:
        raise ValueError("output validity exceeds PIT inference freshness")
    knowledge_date = dataset.manifest_as_of.date()
    produced_date = spec.calculated_at.date()
    if spec.target.output_role is FactorOutputRole.FORWARD_EXPECTATION:
        if (
            target_period.period_start <= knowledge_date
            or target_period.period_start <= produced_date
        ):
            raise ValueError("forward inference target period must follow knowledge and production")
    elif target_period.period_end > knowledge_date or target_period.period_end > produced_date:
        raise ValueError("current-state inference target period exceeds its knowledge cutoff")
    rows_by_id = dataset.rows_by_id
    bindings: list[ExecutionFoldBinding] = []
    minimum_gap = max(spec.plan.timing.purge_days, spec.plan.timing.embargo_days)
    split_folds = {item.fold_id: item for item in spec.temporal_split.walk_forward_folds}
    for outer in spec.plan.outer_folds:
        split_fold = split_folds[outer.fold_id]
        training = _rows_for(outer.training_row_ids, rows_by_id, outer.fold_id)
        outer_validation = _rows_for(
            outer.validation_row_ids,
            rows_by_id,
            outer.fold_id,
        )
        out_of_sample = _rows_for(outer.out_of_sample_row_ids, rows_by_id, outer.fold_id)
        _validate_rows_in_window(
            training,
            start=split_fold.training.start,
            end=split_fold.training.end,
            label=f"fold {outer.fold_id} training",
        )
        _validate_rows_in_window(
            outer_validation,
            start=split_fold.validation.start,
            end=split_fold.validation.end,
            label=f"fold {outer.fold_id} validation",
        )
        _validate_rows_in_window(
            out_of_sample,
            start=split_fold.out_of_sample.start,
            end=split_fold.out_of_sample.end,
            label=f"fold {outer.fold_id} OOS",
        )
        if any(
            row.available_at > outer.selection_as_of
            or row.label_available_at > outer.selection_as_of
            for row in (*training, *outer_validation)
        ):
            raise ValueError(f"fold {outer.fold_id} final-fit row exceeds selection cutoff")
        _validate_fact_cutoff(
            (*training, *outer_validation),
            cutoff=outer.selection_as_of,
            label=f"fold {outer.fold_id} final fit",
        )
        if outer.selection_as_of.date() >= min(row.observation_date for row in out_of_sample):
            raise ValueError(f"fold {outer.fold_id} outer OOS begins before selection cutoff")
        if any(
            row.available_at > outer.evaluation_as_of
            or row.label_available_at > outer.evaluation_as_of
            for row in out_of_sample
        ):
            raise ValueError(f"fold {outer.fold_id} OOS row exceeds evaluation cutoff")
        _validate_fact_cutoff(
            out_of_sample,
            cutoff=outer.evaluation_as_of,
            label=f"fold {outer.fold_id} OOS",
        )
        _validate_gap(
            training,
            outer_validation,
            minimum_gap,
            f"fold {outer.fold_id} validation",
        )
        _validate_gap(
            outer_validation,
            out_of_sample,
            minimum_gap,
            f"fold {outer.fold_id} OOS",
        )
        inner_bindings: list[InnerFoldBinding] = []
        for inner in outer.inner_folds:
            inner_training = _rows_for(inner.training_row_ids, rows_by_id, inner.fold_id)
            validation = _rows_for(inner.validation_row_ids, rows_by_id, inner.fold_id)
            if any(
                row.available_at > outer.selection_as_of
                or row.label_available_at > outer.selection_as_of
                for row in (*inner_training, *validation)
            ):
                raise ValueError(f"inner fold {inner.fold_id} row exceeds selection cutoff")
            _validate_fact_cutoff(
                (*inner_training, *validation),
                cutoff=outer.selection_as_of,
                label=f"inner fold {inner.fold_id}",
            )
            _validate_gap(inner_training, validation, minimum_gap, f"inner fold {inner.fold_id}")
            inner_bindings.append(
                InnerFoldBinding(
                    fold_id=inner.fold_id,
                    training_row_ids=inner.training_row_ids,
                    validation_row_ids=inner.validation_row_ids,
                )
            )
        design_rows = {
            row.row_id: row.canonical_payload()
            for row in (*training, *outer_validation, *out_of_sample)
        }
        design_hash = hash_payload(
            {
                "manifest_id": dataset.manifest_id,
                "manifest_hash": dataset.manifest_hash,
                "manifest_content_hash": dataset.manifest_content_hash,
                "fold_id": outer.fold_id,
                "training_row_ids": list(outer.training_row_ids),
                "validation_row_ids": list(outer.validation_row_ids),
                "out_of_sample_row_ids": list(outer.out_of_sample_row_ids),
                "inner_folds": [
                    {
                        "fold_id": item.fold_id,
                        "training_row_ids": list(item.training_row_ids),
                        "validation_row_ids": list(item.validation_row_ids),
                    }
                    for item in inner_bindings
                ],
                "rows": [design_rows[key] for key in sorted(design_rows)],
            }
        )
        bindings.append(
            ExecutionFoldBinding(
                fold_id=outer.fold_id,
                manifest_id=dataset.manifest_id,
                manifest_hash=dataset.manifest_hash,
                outer_training_row_ids=outer.training_row_ids,
                outer_validation_row_ids=outer.validation_row_ids,
                outer_oos_row_ids=outer.out_of_sample_row_ids,
                inner_folds=tuple(inner_bindings),
                selection_as_of=outer.selection_as_of,
                evaluation_as_of=outer.evaluation_as_of,
                design_hash=design_hash,
            )
        )
    return NestedCVExecutionRequest(
        run_key=spec.run_key,
        run_version=spec.run_version,
        factor_version=spec.factor_version,
        target_code=spec.target.target_code,
        candidate_asset_codes=tuple(item.asset_code for item in spec.candidates),
        pit_manifest_id=dataset.manifest_id,
        pit_manifest_hash=dataset.manifest_hash,
        pit_manifest_content_hash=dataset.manifest_content_hash,
        dataset_hash=dataset.content_hash,
        inference_row_id=inference.row_id,
        inference_row_hash=hash_payload(inference.canonical_payload()),
        inference_target_period_id=target_period.period_id,
        inference_target_calendar_id=target_period.calendar_id,
        inference_target_calendar_version=target_period.calendar_version,
        inference_target_calendar_hash=target_period.calendar_hash,
        inference_target_period_hash=target_period.content_hash,
        plan_version=spec.plan.policy_version,
        plan_hash=spec.plan.content_hash,
        benchmark_version=spec.historical_mean_benchmark.version,
        benchmark_hash=spec.historical_mean_benchmark.content_hash,
        fixed_fmp_version=spec.fixed_fmp.benchmark_version,
        fixed_fmp_hash=spec.fixed_fmp.content_hash,
        cost_model_version=spec.cost_model.version,
        cost_model_hash=spec.cost_model.content_hash,
        split_contract_version=spec.split_contract.version,
        split_contract_hash=spec.split_contract.content_hash,
        selection_protocol_version=spec.selection_protocol.version,
        selection_protocol_hash=spec.selection_protocol.content_hash,
        metrics_protocol_version=spec.metrics_protocol.version,
        metrics_protocol_hash=spec.metrics_protocol.content_hash,
        output_validity_policy_version=validity_policy.policy_version,
        output_validity_policy_hash=validity_policy.content_hash,
        output_valid_for_seconds=validity_policy.valid_for_seconds,
        output_maximum_valid_for_seconds=validity_policy.maximum_valid_for_seconds,
        input_freshness_policy_version=freshness_policy.policy_version,
        input_freshness_policy_hash=freshness_policy.content_hash,
        max_manifest_age_seconds=freshness_policy.max_manifest_age_seconds,
        max_inference_age_seconds=freshness_policy.max_inference_age_seconds,
        maximum_allowed_input_age_seconds=(freshness_policy.maximum_allowed_age_seconds),
        manifest_fresh_until=manifest_fresh_until,
        inference_fresh_until=inference_fresh_until,
        timing_policy_version=spec.plan.timing.policy_version,
        timing_policy_hash=spec.plan.timing.content_hash,
        code_version=spec.reproducibility.code_version,
        dependency_lock_hash=spec.reproducibility.dependency_lock_hash,
        parameter_version=spec.reproducibility.parameter_version,
        parameter_hash=spec.reproducibility.parameter_hash,
        random_seed=spec.random_seed,
        calculated_at=spec.calculated_at,
        alpha_grid=spec.plan.alpha_grid,
        optimization_metric=spec.plan.optimization_metric,
        optimization_direction=spec.plan.optimization_direction,
        final_fold_id=spec.plan.final_fold_id,
        folds=tuple(bindings),
    )


__all__ = [
    "ExecutionFoldBinding",
    "InnerFoldBinding",
    "InnerTemporalFoldPlan",
    "MacroFactorRunnerSpec",
    "NestedCVExecutionRequest",
    "NestedTemporalCVPlan",
    "OptimizationDirection",
    "OuterTemporalFoldPlan",
    "TargetAvailabilityPolicy",
    "build_execution_request",
    "calculate_temporal_split_hash",
]
