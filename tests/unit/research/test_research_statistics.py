import pytest

from apps.research.domain.statistics import (
    benjamini_hochberg_q_values,
    deflated_sharpe_ratio,
)


def test_benjamini_hochberg_is_order_stable_and_monotone() -> None:
    q_values = benjamini_hochberg_q_values([0.04, 0.001, 0.02, 0.5])

    assert q_values == pytest.approx([0.0533333333, 0.004, 0.04, 0.5])


def test_deflated_sharpe_penalizes_larger_trial_families() -> None:
    small_family = deflated_sharpe_ratio(0.2, sample_count=252, trial_count=2)
    large_family = deflated_sharpe_ratio(0.2, sample_count=252, trial_count=100)

    assert small_family > large_family
    assert 0 <= large_family <= 1
