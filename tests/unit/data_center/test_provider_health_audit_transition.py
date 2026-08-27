"""RED contracts for provider-health transition audit wiring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import pytest

from apps.data_center.application.provider_health_recorder import (
    persist_provider_health_metric,
)
from apps.data_center.domain.entities import ProviderConfig, ProviderHealthSnapshot
from apps.data_center.domain.enums import DataCapability, ProviderHealthStatus

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class _ProviderRepository(Protocol):
    def save(self, config: ProviderConfig) -> None:
        """Persist the updated provider configuration."""


class _HealthAuditWriter(Protocol):
    def write(self, observation: object) -> None:
        """Persist one provider-health transition observation."""


@dataclass
class _RecordingProviderRepository:
    saved: list[ProviderConfig]

    def save(self, config: ProviderConfig) -> None:
        self.saved.append(config)


@dataclass
class _RecordingAuditWriter:
    observations: list[object]
    fail: bool = False

    def write(self, observation: object) -> None:
        if self.fail:
            raise RuntimeError("writer failure must propagate")
        self.observations.append(observation)


class _TransitionRegistry:
    def __init__(self, before: ProviderHealthStatus, after: ProviderHealthStatus) -> None:
        self.before = before
        self.after = after
        self.current = before

    def record_failure(self, _provider: str, _capability: DataCapability) -> None:
        self.current = self.after

    def record_success(
        self, _provider: str, _capability: DataCapability, _latency_ms: float
    ) -> None:
        self.current = self.after

    def get_all_statuses(self) -> list[ProviderHealthSnapshot]:
        return [
            ProviderHealthSnapshot(
                provider_name="provider-primary",
                capability=DataCapability.MACRO,
                status=self.current,
                dataset_key=DataCapability.MACRO.dataset_key,
            )
        ]


def _config() -> ProviderConfig:
    return ProviderConfig(
        id=1,
        name="provider-primary",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="secret-key",
        api_secret="secret-value",
        http_url="",
        api_endpoint="https://example.invalid",
        extra_config={},
        description="test provider",
    )


def _persist(
    registry: _TransitionRegistry,
    writer: _HealthAuditWriter | None = None,
    *,
    success: bool,
) -> None:
    """Invoke the intended identity-bound provider-health API."""

    persist_provider_health_metric(
        _RecordingProviderRepository([]),
        registry,
        _config(),
        capability="macro",
        latency_ms=12.0,
        success=success,
        recorded_at=NOW,
        output_count=1,
        audit_writer=writer,
        run_id="run-1",
        ingested_run_id="ingested-1",
    )


def test_only_healthy_to_circuit_open_transition_writes_once() -> None:
    writer = _RecordingAuditWriter([])
    registry = _TransitionRegistry(ProviderHealthStatus.HEALTHY, ProviderHealthStatus.CIRCUIT_OPEN)

    _persist(registry, writer, success=False)

    assert len(writer.observations) == 1


def test_non_transition_does_not_write_audit() -> None:
    writer = _RecordingAuditWriter([])
    registry = _TransitionRegistry(ProviderHealthStatus.DEGRADED, ProviderHealthStatus.DEGRADED)

    _persist(registry, writer, success=False)

    assert writer.observations == []


def test_circuit_recovery_writes_once_without_secret_or_error_message() -> None:
    writer = _RecordingAuditWriter([])
    registry = _TransitionRegistry(ProviderHealthStatus.CIRCUIT_OPEN, ProviderHealthStatus.HEALTHY)

    _persist(registry, writer, success=True)

    assert len(writer.observations) == 1
    assert "secret" not in str(writer.observations[0]).lower()
    assert "error_message" not in str(writer.observations[0]).lower()


def test_writer_failure_propagates() -> None:
    writer = _RecordingAuditWriter([], fail=True)
    registry = _TransitionRegistry(ProviderHealthStatus.HEALTHY, ProviderHealthStatus.CIRCUIT_OPEN)

    with pytest.raises(RuntimeError, match="writer failure"):
        _persist(registry, writer, success=False)


def test_writer_without_identity_fails_closed() -> None:
    writer = _RecordingAuditWriter([])
    registry = _TransitionRegistry(ProviderHealthStatus.HEALTHY, ProviderHealthStatus.CIRCUIT_OPEN)

    with pytest.raises((TypeError, ValueError)):
        persist_provider_health_metric(
            _RecordingProviderRepository([]),
            registry,
            _config(),
            capability="macro",
            latency_ms=12.0,
            success=False,
            recorded_at=NOW,
            output_count=1,
            audit_writer=writer,
            run_id=None,
            ingested_run_id=None,
        )
