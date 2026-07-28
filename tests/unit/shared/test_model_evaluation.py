"""Numerical integrity tests for shared model evaluation infrastructure."""

import math

import numpy as np
import pytest

from shared.infrastructure.model_evaluation import (
    IC_Calculator,
    ModelEvaluator,
    ModelMetrics,
    PerformanceCalculator,
)


def test_ic_uses_only_finite_aligned_pairs():
    ic = IC_Calculator.calculate_ic(
        np.array([1.0, 2.0, float("nan"), float("inf"), 3.0]),
        np.array([1.0, 2.0, 9.0, 10.0, 3.0]),
    )

    assert ic == pytest.approx(1.0)


def test_ic_rejects_mismatched_or_multidimensional_inputs():
    with pytest.raises(ValueError, match="长度"):
        IC_Calculator.calculate_ic(np.array([1.0]), np.array([1.0, 2.0]))
    with pytest.raises(ValueError, match="one-dimensional"):
        IC_Calculator.calculate_ic(np.array([[1.0, 2.0]]), np.array([[1.0, 2.0]]))


def test_rank_ic_assigns_average_rank_to_ties():
    rank_ic = IC_Calculator.calculate_rank_ic(
        np.array([3.0, 3.0, 1.0]),
        np.array([2.0, 2.0, 0.0]),
    )

    assert rank_ic == pytest.approx(1.0)


def test_icir_drops_nan_and_infinity():
    result = IC_Calculator.calculate_icir(
        [0.1, float("nan"), float("inf"), 0.2],
        annualize=False,
    )

    assert math.isfinite(result)
    assert result == pytest.approx(3.0)


def test_group_ic_does_not_fabricate_missing_members_as_zero():
    result = IC_Calculator.calculate_group_ic(
        predictions={"A": 1.0, "B": 2.0},
        targets={"A": 1.0, "B": 2.0},
        groups={"A": "bank", "B": "bank", "MISSING": "bank"},
    )

    assert result == pytest.approx(1.0)


def test_rolling_ic_validates_window_and_alignment():
    with pytest.raises(ValueError, match="window"):
        IC_Calculator.calculate_rolling_ic([1.0, 2.0], [1.0, 2.0], window=1)
    with pytest.raises(ValueError, match="长度"):
        IC_Calculator.calculate_rolling_ic([1.0, 2.0], [1.0], window=2)


def test_performance_metrics_reject_nonfinite_drawdown_and_bound_turnover():
    with pytest.raises(ValueError, match="finite"):
        PerformanceCalculator.calculate_max_drawdown(np.array([0.1, float("inf")]))

    turnover = PerformanceCalculator.calculate_turnover(
        current_positions=[f"NEW-{index}" for index in range(10)],
        previous_positions=["OLD"],
    )
    assert 0.0 <= turnover <= 1.0
    assert turnover == pytest.approx(1.0)


def test_evaluator_coverage_uses_finite_common_universe_only():
    metrics = ModelEvaluator().evaluate_predictions(
        predictions={"A": 1.0, "B": 2.0, "EXTRA": 3.0, "BAD": float("nan")},
        targets={"A": 1.0, "B": 2.0, "C": 3.0},
    )

    assert metrics.coverage == pytest.approx(2 / 3)
    assert metrics.ic == pytest.approx(1.0)


def test_model_metrics_rejects_nonfinite_and_out_of_range_evidence():
    with pytest.raises(ValueError, match="finite"):
        ModelMetrics(ic=float("nan"))
    with pytest.raises(ValueError, match="coverage"):
        ModelMetrics(coverage=1.01)
    with pytest.raises(ValueError, match="turnover"):
        ModelMetrics(turnover=-0.01)
