"""Reproducible research statistics implemented with the standard library."""

from __future__ import annotations

import math


def benjamini_hochberg_q_values(p_values: list[float]) -> list[float]:
    """Return monotone Benjamini-Hochberg adjusted q-values."""

    if any(value < 0 or value > 1 for value in p_values):
        raise ValueError("p-values must be within [0, 1]")
    count = len(p_values)
    if not count:
        return []
    ranked = sorted(enumerate(p_values), key=lambda item: (item[1], item[0]))
    adjusted = [1.0] * count
    running = 1.0
    for reverse_index in range(count - 1, -1, -1):
        original_index, value = ranked[reverse_index]
        rank = reverse_index + 1
        running = min(running, value * count / rank)
        adjusted[original_index] = min(1.0, running)
    return adjusted


def deflated_sharpe_ratio(
    sharpe: float,
    *,
    sample_count: int,
    trial_count: int,
    skewness: float = 0.0,
    excess_kurtosis: float = 0.0,
) -> float:
    """Return a conservative normal-score DSR approximation.

    The expected maximum Sharpe penalty grows with the declared trial family,
    preventing selection of only the best parameter combination.
    """

    if sample_count < 2 or trial_count < 1:
        raise ValueError("sample_count >= 2 and trial_count >= 1 are required")
    expected_max = math.sqrt(2.0 * math.log(max(2, trial_count))) / math.sqrt(sample_count)
    variance = max(
        1e-12,
        (1.0 - skewness * sharpe + ((excess_kurtosis + 2.0) / 4.0) * sharpe**2)
        / (sample_count - 1),
    )
    z_score = (sharpe - expected_max) / math.sqrt(variance)
    return 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))

