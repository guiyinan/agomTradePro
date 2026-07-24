"""T5 cache-family and pure correlation contracts for shared services."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from shared.domain.correlation import CorrelationMatrix, RollingCorrelationCalculator
from shared.infrastructure.cache_service import CacheDecorator, CacheService


@pytest.mark.parametrize(
    ("getter", "arguments"),
    [
        (CacheService.get_macro_series, ("PMI", "2026-07-25")),
        (CacheService.get_ai_insights, ("recovery", 85.4, 0.65)),
        (CacheService.get_allocation_advice, ("recovery", "balanced", "P1")),
    ],
)
def test_cache_family_getters_accept_payloads_and_reject_wrong_shapes(
    getter: object,
    arguments: tuple[object, ...],
) -> None:
    """Every cache family must return only dictionary payloads."""
    with patch(
        "shared.infrastructure.cache_service.cache.get",
        side_effect=[{"value": 1}, ["wrong"]],
    ):
        assert callable(getter)
        assert getter(*arguments) == {"value": 1}
        assert getter(*arguments) is None


@pytest.mark.parametrize(
    ("setter", "arguments", "default_timeout"),
    [
        (
            CacheService.set_macro_series,
            ("PMI", "2026-07-25", {"values": [50.1]}),
            CacheService.TTL_MACRO_SERIES,
        ),
        (
            CacheService.set_ai_insights,
            ("recovery", 85.4, 0.65, {"summary": "hold"}),
            CacheService.TTL_AI_INSIGHTS,
        ),
        (
            CacheService.set_allocation_advice,
            ("recovery", "balanced", "P1", {"equity": 0.5}),
            CacheService.TTL_ALLOCATION,
        ),
    ],
)
def test_cache_family_setters_apply_default_and_explicit_timeouts(
    setter: object,
    arguments: tuple[object, ...],
    default_timeout: int,
) -> None:
    """All cache families must preserve zero and apply their documented default."""
    with patch("shared.infrastructure.cache_service.cache.set") as cache_set:
        assert callable(setter)
        assert setter(*arguments) is True
        assert setter(*arguments, timeout=0) is True

    assert cache_set.call_args_list[0].kwargs["timeout"] == default_timeout
    assert cache_set.call_args_list[1].kwargs["timeout"] == 0


def test_regime_cache_hit_invalidation_and_failure_contracts() -> None:
    """Regime cache operations must expose hits and isolate clear failures."""
    with patch(
        "shared.infrastructure.cache_service.cache.get",
        return_value={"dominant_regime": "recovery"},
    ):
        assert CacheService.get_regime("2026-07-25", "PMI", "CPI") == {
            "dominant_regime": "recovery"
        }

    with patch("shared.infrastructure.cache_service.cache.clear") as cache_clear:
        assert CacheService.invalidate_regime() is True
        cache_clear.assert_called_once_with()
    with patch(
        "shared.infrastructure.cache_service.cache.clear",
        side_effect=RuntimeError("backend offline"),
    ):
        assert CacheService.invalidate_regime() is False


def test_cache_decorator_key_includes_sorted_keyword_arguments() -> None:
    """Decorated cache keys must be deterministic for keyword arguments."""
    calls = 0

    @CacheDecorator("risk", ttl=30)
    def calculate(value: int, *, scale: int, offset: int) -> int:
        nonlocal calls
        calls += 1
        return value * scale + offset

    with (
        patch(
            "shared.infrastructure.cache_service.cache.get",
            side_effect=[None, 9],
        ),
        patch("shared.infrastructure.cache_service.cache.set") as cache_set,
    ):
        assert calculate(2, scale=4, offset=1) == 9
        assert calculate(2, offset=1, scale=4) == 9

    assert calls == 1
    cache_set.assert_called_once_with(
        "risk:calculate:2:offset=1:scale=4",
        9,
        timeout=30,
    )


def test_correlation_matrix_lookup_and_validation_contracts() -> None:
    """Matrix lookup and price-series validation must fail predictably."""
    matrix = CorrelationMatrix(
        assets=["asset", "benchmark"],
        matrix=[[1.0, 0.5], [0.5, 1.0]],
        calc_date="2026-07-25",
        window_days=20,
    )
    assert matrix.get_correlation("asset", "benchmark") == 0.5
    assert matrix.get_correlation("missing", "benchmark") is None
    malformed = CorrelationMatrix(["asset"], [], "", 1)
    assert malformed.get_correlation("asset", "asset") is None

    calculator = RollingCorrelationCalculator()
    with pytest.raises(ValueError, match="same length"):
        calculator.calculate_rolling_correlation([1, 2], [1])
    with pytest.raises(ValueError, match="same length"):
        calculator.calculate_correlation([1, 2], [1])
    with pytest.raises(ValueError, match="at least 2"):
        calculator.calculate_correlation([1], [1])
    with pytest.raises(ValueError, match="same length"):
        calculator.calculate_covariance([1, 2], [1])
    with pytest.raises(ValueError, match="at least 2"):
        calculator.calculate_covariance([1], [1])
    with pytest.raises(ValueError, match="same length"):
        calculator.calculate_beta([1, 2], [1])
    with pytest.raises(ValueError, match="at least 2"):
        calculator.calculate_beta([1], [1])


def test_correlation_calculations_cover_short_constant_and_regular_series() -> None:
    """The pure calculator must handle warm-up, zero variance, and regular inputs."""
    calculator = RollingCorrelationCalculator()
    assert calculator.calculate_rolling_correlation([1, 2], [1, 2], window=3) == [
        None,
        None,
    ]

    prices = [100.0, 110.0, 99.0, 118.8, 106.92]
    benchmark = [200.0, 210.0, 199.5, 219.45, 208.4775]
    rolling = calculator.calculate_rolling_correlation(prices, benchmark, window=2)
    assert rolling[:2] == [None, None]
    assert rolling[2] is not None
    assert calculator.calculate_correlation(prices, benchmark) == pytest.approx(1.0)
    assert calculator.calculate_covariance(prices, benchmark) != 0

    result = calculator.calculate_correlation_matrix(
        {"asset": prices, "benchmark": benchmark},
        window=4,
    )
    assert result.assets == ["asset", "benchmark"]
    assert result.matrix[0][1] == result.matrix[1][0]
    assert result.window_days == 4
    full = calculator.calculate_correlation_matrix(
        {"asset": prices, "benchmark": benchmark}
    )
    assert full.window_days == len(prices)

    assert calculator.calculate_beta(prices, benchmark) != 0
    assert calculator.calculate_beta([1, 2, 3], [5, 5, 5]) == 0
    assert calculator._calculate_returns([0, 1, 2]) == [0.0, 1.0]
    assert calculator._correlation_coefficient([1], [1]) == 0
    assert calculator._correlation_coefficient([1, 1], [2, 2]) == 0
