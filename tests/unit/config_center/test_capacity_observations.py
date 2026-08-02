"""Capacity profile evidence persistence contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.config_center.application.capacity_profile import (
    RecordStorageCapacityObservationUseCase,
)
from apps.config_center.domain.runtime_config import StorageCapacityObservation
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
