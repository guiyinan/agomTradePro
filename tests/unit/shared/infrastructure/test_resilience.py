"""Behavioral regression tests for shared resilience primitives."""

from __future__ import annotations

import signal
from unittest.mock import patch

import pytest

from shared.infrastructure.resilience import (
    CacheManager,
    DataSourceHealth,
    DataSourceUnavailable,
    MaxRetriesExceeded,
    cached,
    circuit_breaker,
    fallback_to,
    retry_on_error,
    timeout,
    with_cache_stats,
)


def test_retry_reports_attempt_and_eventually_returns() -> None:
    attempts = 0
    retries: list[tuple[int, str]] = []

    @retry_on_error(
        max_retries=2,
        initial_delay=0,
        on_retry=lambda attempt, exc: retries.append((attempt, str(exc))),
    )
    def load() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise ConnectionError("temporary")
        return "ok"

    with patch("time.sleep"):
        assert load() == "ok"

    assert retries == [(1, "temporary")]


def test_retry_exhaustion_raises_normalized_exception() -> None:
    @retry_on_error(max_retries=1, initial_delay=0)
    def load() -> str:
        raise ConnectionError("offline")

    with patch("time.sleep"), pytest.raises(MaxRetriesExceeded, match="最大重试次数"):
        load()


def test_timeout_degrades_safely_when_sigalrm_is_unavailable() -> None:
    @timeout(seconds=1)
    def load() -> str:
        return "ok"

    with patch.object(signal, "SIGALRM", None, create=True):
        assert load() == "ok"


def test_circuit_breaker_opens_after_threshold() -> None:
    should_fail = True

    @circuit_breaker(failure_threshold=2, reset_timeout=60)
    def load() -> str:
        if should_fail:
            raise ConnectionError("offline")
        return "ok"

    with pytest.raises(ConnectionError):
        load()
    with pytest.raises(ConnectionError):
        load()

    should_fail = False
    with pytest.raises(DataSourceUnavailable):
        load()


def test_fallback_preserves_arguments_and_return_type() -> None:
    def fallback(value: int) -> str:
        return f"cached:{value}"

    @fallback_to(fallback, exceptions=(ConnectionError,))
    def load(value: int) -> str:
        raise ConnectionError("offline")

    assert load(3) == "cached:3"


def test_cached_callable_exposes_invalidation() -> None:
    calls = 0

    @cached(ttl=60)
    def calculate(value: int) -> int:
        nonlocal calls
        calls += 1
        return value * 2

    assert calculate(5) == 10
    assert calculate(5) == 10
    assert calls == 1

    calculate.invalidate(5)
    assert calculate(5) == 10
    assert calls == 2


def test_cache_stats_callable_exposes_snapshot() -> None:
    @with_cache_stats
    def load() -> str:
        return "ok"

    assert load() == "ok"
    assert load.get_cache_stats() == {"hits": 0, "misses": 1}


def test_health_state_recovers_after_success() -> None:
    health = DataSourceHealth()

    for _ in range(3):
        health.record_failure("quotes", "offline")
    assert health.is_healthy("quotes") is False

    health.record_success("quotes")
    assert health.is_healthy("quotes") is True
    assert health.get_health_status("quotes")["failure_count"] == 0


def test_cache_manager_expires_stale_values() -> None:
    manager = CacheManager()

    with patch("shared.infrastructure.resilience.time.time", side_effect=[10.0, 12.0]):
        manager.set("key", "value")
        assert manager.get("key", max_age=1) is None
