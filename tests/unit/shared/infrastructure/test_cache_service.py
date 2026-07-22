"""Behavioral regression tests for the shared cache service."""

from __future__ import annotations

from unittest.mock import patch

from shared.infrastructure.cache_service import CacheDecorator, CacheService


def test_cache_key_is_stable_across_keyword_order() -> None:
    first = CacheService._make_key("regime", date="2026-07-22", growth="pmi")
    second = CacheService._make_key("regime", growth="pmi", date="2026-07-22")

    assert first == second


def test_set_regime_returns_documented_success_and_preserves_zero_timeout() -> None:
    payload = {"dominant_regime": "recovery"}

    with patch("shared.infrastructure.cache_service.cache.set") as cache_set:
        success = CacheService.set_regime(
            as_of_date="2026-07-22",
            growth_indicator="pmi",
            inflation_indicator="cpi",
            data=payload,
            timeout=0,
        )

    assert success is True
    cache_set.assert_called_once()
    assert cache_set.call_args.kwargs["timeout"] == 0


def test_get_regime_rejects_cache_values_with_wrong_shape() -> None:
    with patch("shared.infrastructure.cache_service.cache.get", return_value="corrupt"):
        result = CacheService.get_regime("2026-07-22", "pmi", "cpi")

    assert result is None


def test_cache_decorator_preserves_metadata_and_reuses_cached_result() -> None:
    calls = 0

    @CacheDecorator("calculation", ttl=60)
    def calculate(value: int) -> int:
        """Calculate a value once."""
        nonlocal calls
        calls += 1
        return value * 2

    with (
        patch(
            "shared.infrastructure.cache_service.cache.get",
            side_effect=[None, 10],
        ) as cache_get,
        patch("shared.infrastructure.cache_service.cache.set") as cache_set,
    ):
        assert calculate(5) == 10
        assert calculate(5) == 10

    assert calculate.__name__ == "calculate"
    assert calculate.__doc__ == "Calculate a value once."
    assert calls == 1
    assert cache_get.call_count == 2
    cache_set.assert_called_once_with("calculation:calculate:5", 10, timeout=60)
