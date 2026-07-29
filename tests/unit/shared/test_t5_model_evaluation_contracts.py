"""T5 numerical and edge contracts for shared model evaluation."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from shared.infrastructure.model_evaluation import (
    IC_Calculator,
    ModelEvaluator,
    ModelMetrics,
    PerformanceCalculator,
    RollingMetrics,
)


def test_metric_value_objects_round_trip() -> None:
    metrics = ModelMetrics(ic=0.2, sharpe=1.5)
    assert ModelMetrics.from_dict(metrics.to_dict()) == metrics
    rolling = RollingMetrics(date=date(2024, 1, 2), ic=0.3, icir=1.2)
    assert rolling.to_dict()["date"] == "2024-01-02"


def test_ic_and_rank_ic_validate_shapes_and_degenerate_inputs() -> None:
    with pytest.raises(ValueError, match="长度"):
        IC_Calculator.calculate_ic(np.array([1]), np.array([1, 2]))
    with pytest.raises(ValueError, match="长度"):
        IC_Calculator.calculate_rank_ic(np.array([1]), np.array([1, 2]))
    assert IC_Calculator.calculate_ic(np.array([1]), np.array([1])) == 0
    assert IC_Calculator.calculate_rank_ic(np.array([1]), np.array([1])) == 0
    with pytest.warns(RuntimeWarning):
        assert IC_Calculator.calculate_ic(np.array([1, 1]), np.array([2, 2])) == 0
    assert IC_Calculator.calculate_rank_ic(np.array([1, 2, 3]), np.array([1, 2, 3])) == 1


def test_icir_filters_nan_and_handles_zero_variance() -> None:
    assert IC_Calculator.calculate_icir([]) == 0
    assert IC_Calculator.calculate_icir([np.nan, 1]) == 0
    assert IC_Calculator.calculate_icir([1, 1]) == 0
    raw = IC_Calculator.calculate_icir([0.1, 0.2, 0.3], annualize=False)
    annualized = IC_Calculator.calculate_icir([0.1, 0.2, 0.3])
    assert annualized == pytest.approx(raw * np.sqrt(252))


def test_group_and_rolling_ic_cover_empty_and_grouped_data() -> None:
    assert IC_Calculator.calculate_group_ic({}, {}, {}) == 0
    assert (
        IC_Calculator.calculate_group_ic(
            {"a": 1},
            {"a": 2},
            {"a": "one"},
        )
        == 0
    )
    grouped = IC_Calculator.calculate_group_ic(
        {"a": 1, "b": 2, "c": 3, "d": 4},
        {"a": 1, "b": 2, "c": 4, "d": 3},
        {"a": "one", "b": "one", "c": "two", "d": "two"},
    )
    assert -1 <= grouped <= 1
    assert IC_Calculator.calculate_rolling_ic([1], [1], window=2) == []
    rolling = IC_Calculator.calculate_rolling_ic([1, 2, 3, 4], [1, 2, 4, 3], window=2)
    assert [index for index, _value in rolling] == [1, 2, 3]


def test_performance_metrics_cover_empty_constant_and_regular_inputs() -> None:
    assert PerformanceCalculator.calculate_sharpe_ratio(np.array([0.1])) == 0
    assert PerformanceCalculator.calculate_sharpe_ratio(np.array([0.1, 0.1])) == 0
    assert PerformanceCalculator.calculate_sharpe_ratio(np.array([0.1, 0.2]), annualize=False) != 0
    assert PerformanceCalculator.calculate_max_drawdown(np.array([1])) == 0
    assert PerformanceCalculator.calculate_max_drawdown(
        np.array([1.0, 1.2, 0.8, 1.1])
    ) == pytest.approx(0.4)
    assert PerformanceCalculator.calculate_turnover(["a"], []) == 0
    assert PerformanceCalculator.calculate_turnover(["b"], ["a"]) == 1
    assert PerformanceCalculator.calculate_coverage(["a"], []) == 0
    assert PerformanceCalculator.calculate_coverage(["a"], ["a", "b"]) == 0.5


def test_model_evaluator_handles_empty_grouped_and_performance_payloads() -> None:
    evaluator = ModelEvaluator()
    assert evaluator.evaluate_predictions({}, {}).ic is None

    metrics = evaluator.evaluate_predictions(
        {"a": 0.9, "b": 0.2, "missing": 0.1},
        {"a": 0.1, "b": -0.1},
        returns={"a": 0.02, "b": -0.01},
        groups={"a": "one", "b": "one"},
    )
    assert metrics.ic is not None
    assert metrics.group_ic is not None
    assert metrics.sharpe is not None
    assert metrics.annual_return == pytest.approx(2.52)
    assert metrics.coverage == 1.5

    unchanged = evaluator._calculate_performance_metrics(
        {"a": 1},
        {"a": 0.1},
        ModelMetrics(ic=0.2),
    )
    assert unchanged.ic == 0.2
    assert unchanged.sharpe is None
