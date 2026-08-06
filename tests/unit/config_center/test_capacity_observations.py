"""Capacity profile evidence persistence contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.config_center.application.capacity_profile import (
    RecordStorageCapacityObservationUseCase,
    StorageCapacityProfileBlockedError,
    StorageCapacityProfileService,
)
from apps.config_center.domain.runtime_config import (
    StorageBudgetPolicy,
    StorageCapacityObservation,
)
from apps.config_center.infrastructure.capacity_repositories import (
    StorageCapacityObservationRepository,
)


def _observation() -> StorageCapacityObservation:
    """Build a representative capacity observation."""

    return StorageCapacityObservation(
        observation_id=str(uuid4()),
        environment="development",
        observed_at=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
        filesystem_total_bytes=1_000,
        filesystem_used_bytes=400,
        filesystem_free_bytes=600,
        database_size_bytes=120,
        relation_sizes={"data_center_fact": 100},
        policy_key="development",
        configured_capacity_bytes=900,
        effective_capacity_bytes=900,
        usage_ratio=400 / 900,
        pressure_state="healthy",
        source="test",
        metadata={"database_vendor": "sqlite"},
    )


def test_capacity_observation_rejects_naive_time_and_overflow() -> None:
    """Capacity evidence preserves time and filesystem arithmetic invariants."""

    with pytest.raises(ValueError, match="timezone-aware"):
        StorageCapacityObservation(
            observation_id=str(uuid4()),
            environment="development",
            observed_at=datetime(2026, 8, 3, 12, 0),
            filesystem_total_bytes=1,
            filesystem_used_bytes=0,
            filesystem_free_bytes=1,
            database_size_bytes=0,
        )
    with pytest.raises(ValueError, match="cannot exceed"):
        StorageCapacityObservation(
            observation_id=str(uuid4()),
            environment="development",
            observed_at=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
            filesystem_total_bytes=1,
            filesystem_used_bytes=1,
            filesystem_free_bytes=1,
            database_size_bytes=0,
        )


class _BudgetPort:
    """In-memory active-policy port for application orchestration tests."""

    def __init__(self, policy: StorageBudgetPolicy | None) -> None:
        self.policy = policy

    def get_active(self) -> StorageBudgetPolicy | None:
        return self.policy

    def require_active(self) -> StorageBudgetPolicy:
        if self.policy is None or not self.policy.active:
            raise RuntimeError("storage_budget_policy_missing_or_inactive")
        return self.policy


class _Observer:
    """Deterministic infrastructure-port fake."""

    def collect(
        self,
        *,
        environment: str,
        policy_key: str,
        configured_capacity_bytes: int,
        source: str,
    ) -> StorageCapacityObservation:
        return StorageCapacityObservation(
            observation_id="8a1843e3-8330-4587-828a-4a933b1fa318",
            environment=environment,
            observed_at=datetime(2026, 8, 7, 1, 10, tzinfo=UTC),
            filesystem_total_bytes=1_000,
            filesystem_used_bytes=400,
            filesystem_free_bytes=600,
            database_size_bytes=100,
            policy_key=policy_key,
            configured_capacity_bytes=configured_capacity_bytes,
            source=source,
        )


class _ObservationRepository:
    """In-memory persistence port for application orchestration tests."""

    def __init__(self) -> None:
        self.saved: list[StorageCapacityObservation] = []

    def save(self, observation: StorageCapacityObservation) -> StorageCapacityObservation:
        self.saved.append(observation)
        return observation

    def get_latest(self, environment: str) -> StorageCapacityObservation | None:
        del environment
        return self.saved[-1] if self.saved else None

    def list_recent(
        self,
        environment: str,
        *,
        limit: int = 30,
    ) -> list[StorageCapacityObservation]:
        del environment
        return list(reversed(self.saved))[:limit]


def _active_budget() -> StorageBudgetPolicy:
    return StorageBudgetPolicy(
        policy_key="production-90g",
        version=1,
        configured_capacity_bytes=900,
        raw_budget_ratio=0.2,
        quarantine_budget_ratio=0.1,
        database_budget_ratio=0.3,
        logs_budget_ratio=0.1,
        emergency_reserve_ratio=0.1,
        warning_ratio=0.7,
        critical_ratio=0.85,
        active=True,
    )


def test_capacity_profile_service_collects_evaluates_and_persists() -> None:
    """Application orchestration binds host evidence to the active policy."""

    repository = _ObservationRepository()
    saved = StorageCapacityProfileService(
        _BudgetPort(_active_budget()),
        _Observer(),
        repository,
    ).collect_and_record(environment="production", source="test-observer")

    assert saved.pressure_state == "healthy"
    assert saved.effective_capacity_bytes == 900
    assert saved.usage_ratio == 400 / 900
    assert repository.saved == [saved]


def test_capacity_profile_service_blocks_before_observer_without_active_policy() -> None:
    """No observation is collected or persisted when the owner policy is absent."""

    repository = _ObservationRepository()
    service = StorageCapacityProfileService(_BudgetPort(None), _Observer(), repository)

    with pytest.raises(
        StorageCapacityProfileBlockedError,
        match="storage_budget_policy_missing_or_inactive",
    ):
        service.collect_and_record(environment="production")
    assert repository.saved == []


@pytest.mark.django_db
def test_capacity_observation_repository_round_trip() -> None:
    """Repository persistence retains budget, pressure and relation evidence."""

    observation = _observation()
    saved = RecordStorageCapacityObservationUseCase(StorageCapacityObservationRepository()).execute(
        observation
    )
    loaded = StorageCapacityObservationRepository().get_latest("development")

    assert loaded == saved == observation
    assert loaded is not None
    assert loaded.relation_sizes["data_center_fact"] == 100
    assert loaded.pressure_state == "healthy"
