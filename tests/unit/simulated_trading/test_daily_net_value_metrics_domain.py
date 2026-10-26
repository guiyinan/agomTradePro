"""Domain tests for correction-aware daily performance metrics."""

from __future__ import annotations

from typing import cast

import pytest

from apps.simulated_trading.domain.daily_net_value_metrics import (
    DailyNetValueMetricInput,
    _drawdown,
    _finite_float,
    _percent_change,
    project_daily_net_value_metrics,
)


def _row(
    net_value: float | None,
    *,
    daily_return: float | None = 0.0,
    cumulative_return: float | None = 0.0,
    drawdown: float | None = 0.0,
    coverage: bool = True,
    overlay: bool = False,
) -> DailyNetValueMetricInput:
    return DailyNetValueMetricInput(
        net_value=net_value,
        stored_daily_return=daily_return,
        stored_cumulative_return=cumulative_return,
        stored_drawdown=drawdown,
        correction_coverage_known=coverage,
        correction_overlay_applied=overlay,
    )


def test_empty_history_returns_no_metric_rows() -> None:
    assert project_daily_net_value_metrics((), initial_capital=100.0) == ()


def test_unadjusted_rows_preserve_original_values_and_invalid_stored_metrics() -> None:
    rows = (
        _row(101.0, daily_return=1.0, cumulative_return=1.0, drawdown=0.0),
        _row(102.0, daily_return=None, cumulative_return=2.0, drawdown=0.0),
    )

    result = project_daily_net_value_metrics(rows, initial_capital=100.0)

    assert result[0].daily_return == result[0].original_daily_return == 1.0
    assert result[0].metrics_known is True
    assert result[1].daily_return is None
    assert result[1].reason_code == "STORED_PERFORMANCE_VALUE_INVALID"
    assert result[1].metrics_known is False


def test_overlay_reuses_the_prior_peak_outside_a_display_window() -> None:
    rows = (
        _row(150.0),
        _row(120.0, overlay=True, daily_return=-20.0, cumulative_return=20.0),
        _row(130.0, daily_return=8.33, cumulative_return=30.0),
    )

    result = project_daily_net_value_metrics(rows, initial_capital=100.0)

    assert result[1].drawdown == pytest.approx(20.0)
    assert result[2].drawdown == pytest.approx(20.0 / 150.0 * 100.0)


def test_corrected_new_high_updates_peak_before_drawdown() -> None:
    rows = (_row(100.0), _row(120.0, overlay=True), _row(110.0))

    result = project_daily_net_value_metrics(rows, initial_capital=100.0)

    assert result[1].drawdown == 0.0
    assert result[2].drawdown == pytest.approx(100.0 / 12.0)
    assert result[1].metrics_known is True
    assert result[2].metrics_known is True


def test_first_overlay_has_no_daily_baseline_but_uses_known_capital() -> None:
    result = project_daily_net_value_metrics(
        (_row(110.0, overlay=True),),
        initial_capital=100.0,
    )[0]

    assert result.daily_return is None
    assert result.cumulative_return == pytest.approx(10.0)
    assert result.drawdown == 0.0
    assert result.reason_code == "DAILY_RETURN_BASELINE_UNAVAILABLE"
    assert result.metrics_known is False


def test_zero_previous_value_does_not_create_a_daily_return() -> None:
    result = project_daily_net_value_metrics(
        (_row(0.0), _row(10.0, overlay=True)),
        initial_capital=10.0,
    )[1]

    assert result.daily_return is None
    assert result.cumulative_return == 0.0
    assert result.drawdown == 0.0
    assert result.reason_code == "DAILY_RETURN_BASELINE_UNAVAILABLE"


@pytest.mark.parametrize("capital", [None, 0.0, -1.0, float("inf")])
def test_unknown_or_nonpositive_initial_capital_keeps_cumulative_return_unknown(
    capital: float | None,
) -> None:
    result = project_daily_net_value_metrics(
        (_row(100.0), _row(110.0, overlay=True)),
        initial_capital=capital,
    )[1]

    assert result.cumulative_return is None
    assert result.reason_code == "INITIAL_CAPITAL_UNKNOWN"
    assert result.metrics_known is False


def test_unknown_coverage_blocks_current_and_later_metrics() -> None:
    result = project_daily_net_value_metrics(
        (_row(100.0), _row(90.0, coverage=False), _row(95.0)),
        initial_capital=100.0,
    )

    assert result[0].metrics_known is True
    assert result[1].daily_return is None
    assert result[2].daily_return is None
    assert result[1].reason_code == result[2].reason_code == "FEE_CORRECTION_COVERAGE_UNKNOWN"


def test_nonfinite_net_value_blocks_its_row_and_later_rows() -> None:
    result = project_daily_net_value_metrics(
        (_row(100.0), _row(float("nan"), overlay=True), _row(110.0)),
        initial_capital=100.0,
    )

    assert result[1].daily_return is None
    assert result[1].reason_code == "DAILY_NET_VALUE_INVALID"
    assert result[2].daily_return is None
    assert result[2].reason_code == "DAILY_NET_VALUE_INVALID"


def test_unrepresentable_percentages_become_unknown_not_infinity() -> None:
    result = project_daily_net_value_metrics(
        (_row(10.0), _row(1e308, overlay=True)),
        initial_capital=10.0,
    )[1]

    assert result.daily_return is None
    assert result.cumulative_return is None
    assert result.drawdown == 0.0
    assert result.reason_code == "DAILY_RETURN_UNREPRESENTABLE"
    assert result.metrics_known is False


def test_zero_peak_is_unknown_but_zero_value_after_positive_peak_is_valid() -> None:
    zero_peak = project_daily_net_value_metrics(
        (_row(0.0, overlay=True),),
        initial_capital=100.0,
    )[0]
    zero_after_peak = project_daily_net_value_metrics(
        (_row(100.0), _row(0.0, overlay=True)),
        initial_capital=100.0,
    )[1]

    assert zero_peak.drawdown is None
    assert zero_peak.reason_code == "DAILY_RETURN_BASELINE_UNAVAILABLE"
    assert zero_after_peak.drawdown == 100.0
    assert zero_after_peak.metrics_known is True


def test_invalid_runtime_numeric_input_fails_closed() -> None:
    invalid = cast(float, object())
    result = project_daily_net_value_metrics(
        (_row(invalid, overlay=True),),
        initial_capital=100.0,
    )[0]

    assert result.daily_return is None
    assert result.reason_code == "DAILY_NET_VALUE_INVALID"


@pytest.mark.parametrize(
    "invalid_value",
    [
        pytest.param(cast(float, True), id="boolean"),
        pytest.param(cast(float, object()), id="object"),
        pytest.param(cast(float, 10**10000), id="integer-overflow"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="infinity"),
    ],
)
def test_direct_domain_net_value_rejects_bool_invalid_overflow_and_nonfinite(
    invalid_value: float,
) -> None:
    result = project_daily_net_value_metrics(
        (_row(invalid_value, overlay=True),),
        initial_capital=100.0,
    )[0]

    assert result.daily_return is None
    assert result.cumulative_return is None
    assert result.drawdown is None
    assert result.reason_code == "DAILY_NET_VALUE_INVALID"


@pytest.mark.parametrize(
    "invalid_capital",
    [
        pytest.param(cast(float, True), id="boolean"),
        pytest.param(cast(float, object()), id="object"),
        pytest.param(cast(float, 10**10000), id="integer-overflow"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="infinity"),
    ],
)
def test_direct_domain_initial_capital_rejects_bool_invalid_overflow_and_nonfinite(
    invalid_capital: float,
) -> None:
    result = project_daily_net_value_metrics(
        (_row(100.0), _row(110.0, overlay=True)),
        initial_capital=invalid_capital,
    )[1]

    assert result.cumulative_return is None
    assert result.reason_code == "INITIAL_CAPITAL_UNKNOWN"


def test_negative_peak_cannot_be_reported_as_a_known_drawdown() -> None:
    result = project_daily_net_value_metrics(
        (_row(-10.0, overlay=True),),
        initial_capital=100.0,
    )[0]

    assert result.drawdown is None
    assert result.metrics_known is False


def test_finite_float_rejects_bool_overflow_and_bad_conversion() -> None:
    class BadNumber:
        def __float__(self) -> float:
            raise ValueError("not numeric")

    assert _finite_float(None) is None
    assert _finite_float(cast(float, True)) is None
    assert _finite_float(cast(float, 10**10000)) is None
    assert _finite_float(cast(float, object())) is None
    assert _finite_float(cast(float, BadNumber())) is None


def test_percentage_and_drawdown_helpers_reject_unrepresentable_results() -> None:
    assert _percent_change(1.0, 0.0) is None
    assert _percent_change(100.0, 100.0) == 0.0
    assert _percent_change(1e308, 1e-308) is None
    assert _percent_change(1e308, 10.0) is None
    assert _percent_change(-1e308, 1e308) is None
    assert _drawdown(100.0, 0.0) is None
    assert _drawdown(100.0, 100.0) == 0.0
    assert _drawdown(-1e308, 1e-308) is None
    assert _drawdown(-1e308, 10.0) is None
    assert _drawdown(-1e308, 1e308) is None
    assert _drawdown(110.0, 100.0) == 0.0
