"""Behavioral regression tests for shared monitoring metrics."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.infrastructure.metrics import (
    AlphaMetrics,
    HistogramBucket,
    HistogramValue,
    MetricsRegistry,
    get_alpha_metrics,
    track_provider_latency,
)


def test_histogram_prometheus_buckets_have_complete_labels() -> None:
    histogram = HistogramValue(
        name="provider_latency",
        buckets=[HistogramBucket(1.0, 0)],
        labels={"provider": "qlib"},
        timestamp=datetime(2026, 7, 22, tzinfo=UTC),
    )
    histogram.observe(0.5)

    output = histogram.to_prometheus()

    assert 'provider_latency_bucket{provider="qlib",le="1.0"} 1 ' in output
    assert 'provider_latency_bucket{provider="qlib",le="+Inf"} 1 ' in output


def test_histogram_prometheus_bucket_without_base_labels_is_valid() -> None:
    histogram = HistogramValue(
        name="latency",
        buckets=[HistogramBucket(0.5, 0)],
        timestamp=datetime(2026, 7, 22, tzinfo=UTC),
    )

    assert 'latency_bucket{le="0.5"} 0 ' in histogram.to_prometheus()


def test_provider_latency_decorator_preserves_metadata_and_records_failure() -> None:
    metrics = get_alpha_metrics()
    metrics.registry.reset_metrics()

    @track_provider_latency("broken-provider")
    def load(value: int) -> str:
        """Load one provider value."""
        raise ConnectionError(value)

    assert load.__name__ == "load"
    assert load.__doc__ == "Load one provider value."

    with pytest.raises(ConnectionError):
        load(3)

    success_rate = metrics.registry.get_metric(
        AlphaMetrics.PROVIDER_SUCCESS_RATE,
        {"provider": "broken-provider"},
    )
    request_count = metrics.registry.get_metric(
        AlphaMetrics.SCORE_REQUEST_COUNT,
        {"provider": "broken-provider"},
    )
    assert success_rate is not None
    assert success_rate.value == 0.0
    assert request_count is not None
    assert request_count.value == 1.0


def test_registry_aggregates_same_counter_across_label_sets() -> None:
    registry = MetricsRegistry()
    registry.reset_metrics()
    registry.inc_counter("requests", labels={"provider": "one"})
    registry.inc_counter("requests", value=2, labels={"provider": "two"})

    aggregate = registry.get_metric("requests")

    assert aggregate is not None
    assert aggregate.value == 3.0
