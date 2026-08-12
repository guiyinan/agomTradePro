"""Compatibility checks for the temporal-plan Domain module split."""

from apps.macro_factor.domain import temporal_plan
from apps.macro_factor.domain.temporal_cv_contracts import (
    InnerTemporalFoldPlan,
    NestedTemporalCVPlan,
    OptimizationDirection,
    OuterTemporalFoldPlan,
    TargetAvailabilityPolicy,
)
from apps.macro_factor.domain.temporal_runner_spec import (
    MacroFactorRunnerSpec,
    calculate_temporal_split_hash,
)


def test_temporal_plan_preserves_legacy_public_reexports() -> None:
    """Existing callers keep importing every moved contract from temporal_plan."""

    expected = {
        "InnerTemporalFoldPlan": InnerTemporalFoldPlan,
        "MacroFactorRunnerSpec": MacroFactorRunnerSpec,
        "NestedTemporalCVPlan": NestedTemporalCVPlan,
        "OptimizationDirection": OptimizationDirection,
        "OuterTemporalFoldPlan": OuterTemporalFoldPlan,
        "TargetAvailabilityPolicy": TargetAvailabilityPolicy,
        "calculate_temporal_split_hash": calculate_temporal_split_hash,
    }

    for name, value in expected.items():
        assert getattr(temporal_plan, name) is value
        assert name in temporal_plan.__all__
