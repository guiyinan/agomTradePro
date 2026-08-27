"""Persistent and runtime provider capability health recording."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, datetime

from apps.audit.application.data_provider_health_audit import (
    DataProviderHealthAuditObservation,
)
from apps.audit.domain.system_audit_event import AuditOutcome
from apps.data_center.application.sync_transaction import DataProviderHealthAuditWriter
from apps.data_center.domain.entities import ProviderConfig, ProviderHealthSnapshot
from apps.data_center.domain.enums import (
    DataCapability,
    ProviderHealthStatus,
)
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
    audit_writer: DataProviderHealthAuditWriter | None = None,
    run_id: str | None = None,
    ingested_run_id: str | None = None,
) -> None:
    """Persist output-aware provider health and update the runtime circuit state."""

    recorded = recorded_at or datetime.now(UTC)
    try:
        runtime_capability = DataCapability(capability)
    except ValueError:
        runtime_capability = None
    before = (
        _find_provider_health_snapshot(
            provider_registry,
            provider_name=config.name,
            capability=runtime_capability,
        )
        if runtime_capability is not None
        else None
    )
    effective_success = success and (output_count is None or output_count > 0)
    effective_error = error or (
        "provider completed without output" if success and output_count == 0 else ""
    )
    extra_config = dict(config.extra_config or {})
    capability_metrics = dict(extra_config.get("health_metrics") or {})
    try:
        dataset_key = DataCapability(capability).dataset_key
    except ValueError:
        dataset_key = capability
    dataset_metrics = dict(extra_config.get("health_metrics_by_dataset") or {})
    metric = dict(
        dataset_metrics.get(dataset_key)
        or capability_metrics.get(capability)
        or capability_metrics.get(dataset_key)
        or {}
    )
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
    dataset_metrics[dataset_key] = metric
    extra_config["health_metrics_by_dataset"] = dataset_metrics
    provider_repo.save(dataclasses.replace(config, extra_config=extra_config))
    if runtime_capability is None:
        return
    if effective_success:
        provider_registry.record_success(config.name, runtime_capability, latency_ms)
    else:
        provider_registry.record_failure(config.name, runtime_capability)
    after = _find_provider_health_snapshot(
        provider_registry,
        provider_name=config.name,
        capability=runtime_capability,
    )
    transition = _provider_health_transition(before=before, after=after)
    if transition is None or audit_writer is None:
        return
    if run_id is None or ingested_run_id is None:
        raise ValueError("provider health audit transition requires exact sync identity")
    if after is None:
        raise ValueError("provider health audit transition lost its current snapshot")
    snapshot_id, snapshot_hash = _provider_health_evidence(
        provider_name=config.name,
        capability=runtime_capability,
        before=before,
        after=after,
        recorded_at=recorded,
    )
    recovered = transition == "recovered"
    audit_writer.write(
        DataProviderHealthAuditObservation(
            provider_key=config.name,
            capability=runtime_capability.value,
            dataset_key=after.dataset_key,
            run_id=run_id,
            ingested_run_id=ingested_run_id,
            provider_health_snapshot_id=snapshot_id,
            provider_health_snapshot_version="1",
            provider_health_snapshot_hash=snapshot_hash,
            transition=transition,
            reason_code=("provider_recovered" if recovered else "provider_circuit_opened"),
            outcome=AuditOutcome.RECOVERED if recovered else AuditOutcome.BLOCKED,
            occurred_at=recorded,
            recorded_at=recorded,
        )
    )


def _find_provider_health_snapshot(
    provider_registry: ProviderRegistryProtocol,
    *,
    provider_name: str,
    capability: DataCapability,
) -> ProviderHealthSnapshot | None:
    """Return one exact runtime slot, preserving legacy registries without snapshots."""

    reader = getattr(provider_registry, "get_all_statuses", None)
    if not callable(reader):
        return None
    snapshots = reader()
    matches = [
        snapshot
        for snapshot in snapshots
        if isinstance(snapshot, ProviderHealthSnapshot)
        and snapshot.provider_name == provider_name
        and snapshot.capability is capability
    ]
    if len(matches) > 1:
        raise ValueError("provider registry returned duplicate health snapshots")
    return matches[0] if matches else None


def _provider_health_transition(
    *,
    before: ProviderHealthSnapshot | None,
    after: ProviderHealthSnapshot | None,
) -> str | None:
    """Return only registered circuit-open or recovery state changes."""

    if after is None:
        return None
    before_status = before.status if before is not None else ProviderHealthStatus.UNKNOWN
    if (
        after.status is ProviderHealthStatus.CIRCUIT_OPEN
        and before_status is not ProviderHealthStatus.CIRCUIT_OPEN
    ):
        return "circuit_opened"
    if after.status is ProviderHealthStatus.HEALTHY and before_status in {
        ProviderHealthStatus.DEGRADED,
        ProviderHealthStatus.CIRCUIT_OPEN,
    }:
        return "recovered"
    return None


def _provider_health_evidence(
    *,
    provider_name: str,
    capability: DataCapability,
    before: ProviderHealthSnapshot | None,
    after: ProviderHealthSnapshot,
    recorded_at: datetime,
) -> tuple[str, str]:
    """Hash one sanitized transition snapshot without credentials or errors."""

    payload = {
        "provider_name": provider_name,
        "capability": capability.value,
        "dataset_key": after.dataset_key,
        "from_status": (
            before.status.value if before is not None else ProviderHealthStatus.UNKNOWN.value
        ),
        "to_status": after.status.value,
        "consecutive_failures": after.consecutive_failures,
        "last_success_at": (
            after.last_success_at.isoformat() if after.last_success_at is not None else None
        ),
        "recorded_at": recorded_at.isoformat(),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    snapshot_hash = hashlib.sha256(
        b"agomtradepro:data-center:provider-health-snapshot:v1\0" + encoded
    ).hexdigest()
    identity_hash = hashlib.sha256(f"{provider_name}|{capability.value}".encode()).hexdigest()[:40]
    return f"provider-health-{identity_hash}", snapshot_hash
