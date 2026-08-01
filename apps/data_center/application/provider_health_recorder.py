"""Persistent and runtime provider capability health recording."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import (
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
)


def persist_provider_health_metric(
    provider_repo: ProviderConfigRepositoryProtocol,
    provider_registry: ProviderRegistryProtocol,
    config: ProviderConfig,
    *,
    capability: str,
    latency_ms: float,
    success: bool,
    error: str = "",
    recorded_at: datetime | None = None,
    output_count: int | None = None,
) -> None:
    """Persist output-aware provider health and update the runtime circuit state."""

    recorded = recorded_at or datetime.now(UTC)
    effective_success = success and (output_count is None or output_count > 0)
    effective_error = error or (
        "provider completed without output" if success and output_count == 0 else ""
    )
    extra_config = dict(config.extra_config or {})
    capability_metrics = dict(extra_config.get("health_metrics") or {})
    metric = dict(capability_metrics.get(capability) or {})
    if effective_success:
        success_count = int(metric.get("success_count", 0)) + 1
        previous_avg = metric.get("avg_latency_ms")
        avg_latency_ms = (
            round(latency_ms, 3)
            if previous_avg is None
            else round(
                ((float(previous_avg) * (success_count - 1)) + latency_ms) / success_count,
                3,
            )
        )
        metric.update(
            {
                "success_count": success_count,
                "avg_latency_ms": avg_latency_ms,
                "last_success_at": recorded.isoformat(),
                "consecutive_failures": 0,
                "last_status": "healthy",
                "last_error": "",
                "last_output_count": output_count,
            }
        )
        extra_config["provider_last_success_at"] = recorded.isoformat()
        provider_avg = extra_config.get("provider_avg_latency_ms")
        provider_success_count = int(extra_config.get("provider_success_count", 0)) + 1
        extra_config["provider_avg_latency_ms"] = (
            round(latency_ms, 3)
            if provider_avg is None
            else round(
                ((float(provider_avg) * (provider_success_count - 1)) + latency_ms)
                / provider_success_count,
                3,
            )
        )
        extra_config["provider_success_count"] = provider_success_count
        extra_config["provider_last_status"] = "healthy"
        extra_config["provider_last_error"] = ""
    else:
        metric.update(
            {
                "consecutive_failures": int(metric.get("consecutive_failures", 0)) + 1,
                "last_failure_at": recorded.isoformat(),
                "last_status": "degraded",
                "last_error": effective_error,
                "last_output_count": output_count,
            }
        )
        extra_config["provider_last_status"] = "degraded"
        extra_config["provider_last_error"] = effective_error
    capability_metrics[capability] = metric
    extra_config["health_metrics"] = capability_metrics
    provider_repo.save(dataclasses.replace(config, extra_config=extra_config))
    try:
        runtime_capability = DataCapability(capability)
    except ValueError:
        return
    if effective_success:
        provider_registry.record_success(config.name, runtime_capability, latency_ms)
    else:
        provider_registry.record_failure(config.name, runtime_capability)
