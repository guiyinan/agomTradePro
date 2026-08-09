"""Pure planning contracts for nested temporal cross-validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from apps.macro_factor.domain.entities import FactorOutputRole

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
        if type(self.horizon_periods) is not int or self.horizon_periods < 0:
            raise ValueError(
                "TargetAvailabilityPolicy.horizon_periods must be an integer and cannot be negative"
            )
        if self.output_role is FactorOutputRole.CURRENT_STATE and self.horizon_periods != 0:
            raise ValueError("current-state availability requires horizon_periods=0")
        if self.output_role is FactorOutputRole.FORWARD_EXPECTATION and self.horizon_periods == 0:
            raise ValueError("forward availability requires a positive horizon")
        if type(self.normalized_horizon_days) is not int:
            raise ValueError("normalized_horizon_days must be an integer")
        if self.output_role is FactorOutputRole.CURRENT_STATE:
            if self.normalized_horizon_days != 0:
                raise ValueError("current-state normalized horizon must be zero")
        else:
            require_positive(
                self.normalized_horizon_days,
                "TargetAvailabilityPolicy.normalized_horizon_days",
            )
        if (
            type(self.label_availability_lag_days) is not int
            or self.label_availability_lag_days < 0
        ):
            raise ValueError(
                "label_availability_lag_days must be an integer and cannot be negative"
            )
        if type(self.purge_days) is not int or self.purge_days < 0:
            raise ValueError("purge_days must be a non-negative integer")
        if type(self.embargo_days) is not int or self.embargo_days < 0:
            raise ValueError("embargo_days must be a non-negative integer")
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


__all__ = [
    "InnerTemporalFoldPlan",
    "NestedTemporalCVPlan",
    "OptimizationDirection",
    "OuterTemporalFoldPlan",
    "TargetAvailabilityPolicy",
]
