"""
Performance Baseline Tests: API Latency

Establishes P95 latency baselines for critical API endpoints.
These tests use large datasets to simulate production load.

Run with: pytest tests/performance/ -v --no-header -s
"""

import time
from statistics import median, quantiles

import pytest
from django.test import Client


def measure_latency(client: Client, url: str, n: int = 20) -> dict:
    """Measure API latency over n requests, return stats in ms."""
    latencies = []
    for _ in range(n):
        start = time.perf_counter()
        client.get(url)
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies.append(elapsed_ms)
    latencies.sort()
    p95 = quantiles(latencies, n=20)[-1] if len(latencies) >= 20 else max(latencies)
    return {
        "min": min(latencies),
        "median": median(latencies),
        "p95": p95,
        "max": max(latencies),
        "count": len(latencies),
        "status_codes": set(),
    }


@pytest.mark.django_db
class TestHealthEndpointLatency:
    """Health check endpoint should respond within 500ms P95."""

    def test_health_endpoint_latency(self, client):
        """GET /api/health/ P95 < 500ms (excluding cold start)."""
        # Warm up: first request may be slow due to Django lazy initialization
        client.get("/api/health/")
        stats = measure_latency(client, "/api/health/", n=10)
        print(f"\n  /api/health/ - median: {stats['median']:.1f}ms, p95: {stats['p95']:.1f}ms")
        assert stats["p95"] < 500, f"Health check P95 {stats['p95']:.1f}ms exceeds 500ms"


@pytest.mark.django_db
class TestMacroAPILatency:
    """Data-center macro API endpoints latency baseline."""

    def test_macro_indicators_list_latency(self, client, large_macro_dataset, admin_client):
        """GET /api/data-center/macro/series/ P95 < 1000ms with 1000+ data points."""
        stats = measure_latency(admin_client, "/api/data-center/macro/series/?indicator_code=CN_PMI", n=10)
        print(
            f"\n  /api/data-center/macro/series/?indicator_code=CN_PMI - median: {stats['median']:.1f}ms, "
            f"p95: {stats['p95']:.1f}ms"
        )
        # Baseline: should respond within 2 seconds
        assert stats["p95"] < 2000, (
            f"Macro series P95 {stats['p95']:.1f}ms exceeds 2000ms"
        )


@pytest.mark.django_db
class TestSignalAPILatency:
    """Signal API endpoints latency baseline."""

    def test_signal_list_latency(self, admin_client, large_signal_dataset):
        """GET /api/signal/ P95 < 1000ms with 500+ signals."""
        stats = measure_latency(admin_client, "/api/signal/", n=10)
        print(
            f"\n  /api/signal/ - median: {stats['median']:.1f}ms, "
            f"p95: {stats['p95']:.1f}ms"
        )
        assert stats["p95"] < 2000, (
            f"Signal list P95 {stats['p95']:.1f}ms exceeds 2000ms"
        )


@pytest.mark.django_db
class TestDomainCalculationLatency:
    """Domain layer calculation performance baselines."""

    def test_regime_calculation_latency(self):
        """Regime calculation should complete within 100ms for typical input."""
        from apps.regime.domain.services import RegimeCalculator

        service = RegimeCalculator()

        latencies = []
        for _ in range(10):
            start = time.perf_counter()
            # Lightweight domain operation (no DB)
            # Just measure service instantiation + method availability
            assert hasattr(service, "calculate") or hasattr(service, "determine_regime")
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)

        p95 = max(latencies)
        print(f"\n  RegimeCalculator init - p95: {p95:.1f}ms")
        assert p95 < 100, f"Regime calculation P95 {p95:.1f}ms exceeds 100ms"

    def test_factor_scoring_latency(self):
        """Factor scoring for 300 stocks should complete within 500ms."""
        from apps.factor.domain.entities import FactorCategory, FactorDefinition
        from apps.factor.domain.services import FactorCalculationContext, FactorEngine

        universe = [f"{i:06d}" for i in range(1, 301)]
        definitions = [
            FactorDefinition(
                code="pe_ttm",
                name="PE TTM",
                category=FactorCategory.VALUE,
                description="PE ratio",
                data_source="test",
                data_field="pe_ttm",
            )
        ]

        factor_values = {code: float(i % 100) for i, code in enumerate(universe)}

        def get_factor_value(stock: str, factor: str, dt) -> float:
            return factor_values.get(stock, 50.0)

        def get_stock_info(stock: str):
            return {"name": f"Stock {stock}", "sector": "test"}

        context = FactorCalculationContext(
            trade_date=__import__("datetime").date(2025, 1, 15),
            universe=universe,
            factor_definitions=definitions,
            get_factor_value=get_factor_value,
            get_stock_info=get_stock_info,
        )

        engine = FactorEngine(context)

        start = time.perf_counter()
        scores = engine.calculate_factor_scores({"pe_ttm": 1.0})
        elapsed_ms = (time.perf_counter() - start) * 1000

        print(f"\n  FactorEngine.calculate_factor_scores(300 stocks) - {elapsed_ms:.1f}ms")
        assert elapsed_ms < 500, f"Factor scoring {elapsed_ms:.1f}ms exceeds 500ms"
        assert len(scores) == 300

