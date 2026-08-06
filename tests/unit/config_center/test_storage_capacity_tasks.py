"""Celery contracts for hourly Config Center capacity observations."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.config_center.application.capacity_profile import (
    StorageCapacityProfileBlockedError,
)
from apps.config_center.application.tasks import collect_storage_capacity_profile_task
from apps.config_center.domain.runtime_config import StorageCapacityObservation


def _observation() -> StorageCapacityObservation:
    """Return a persisted observation-shaped task result fixture."""

    return StorageCapacityObservation(
        observation_id="ccddaf80-629a-432e-84c1-7fa3c94ac51e",
        environment="production",
        observed_at=datetime(2026, 8, 7, 1, 10, tzinfo=UTC),
        filesystem_total_bytes=1_000,
        filesystem_used_bytes=400,
        filesystem_free_bytes=600,
        database_size_bytes=100,
        policy_key="production-90g",
        configured_capacity_bytes=900,
        effective_capacity_bytes=900,
        usage_ratio=400 / 900,
        pressure_state="healthy",
        source="celery-hourly-observer",
    )


def test_storage_capacity_task_persists_observation_with_normalized_counts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A successful probe publishes one requested/succeeded/stored item."""

    monkeypatch.setattr(
        "apps.config_center.application.tasks.collect_and_record_storage_capacity_profile",
        lambda **_kwargs: _observation(),
    )

    result = collect_storage_capacity_profile_task(environment="production")

    assert result == {
        "success": True,
        "outcome": "success",
        "requested": 1,
        "succeeded": 1,
        "failed": 0,
        "stored": 1,
        "blocked": 0,
        "environment": "production",
        "observation_id": "ccddaf80-629a-432e-84c1-7fa3c94ac51e",
        "pressure_state": "healthy",
        "error": "",
    }


def test_storage_capacity_task_blocks_without_active_policy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Missing policy is a business block and never reports a stored row."""

    def _blocked(**_kwargs: object) -> StorageCapacityObservation:
        raise StorageCapacityProfileBlockedError("storage_budget_policy_missing_or_inactive")

    monkeypatch.setattr(
        "apps.config_center.application.tasks.collect_and_record_storage_capacity_profile",
        _blocked,
    )

    result = collect_storage_capacity_profile_task(environment="production")

    assert result["outcome"] == "blocked"
    assert result["success"] is False
    assert result["requested"] == 1
    assert result["succeeded"] == 0
    assert result["failed"] == 0
    assert result["stored"] == 0
    assert result["blocked"] == 1
    assert result["error"] == "storage_budget_policy_missing_or_inactive"


def test_storage_capacity_task_reports_collection_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Observer or persistence failures publish a technical failure contract."""

    def _failed(**_kwargs: object) -> StorageCapacityObservation:
        raise OSError("mount unavailable")

    monkeypatch.setattr(
        "apps.config_center.application.tasks.collect_and_record_storage_capacity_profile",
        _failed,
    )

    result = collect_storage_capacity_profile_task(environment="production")

    assert result["outcome"] == "failed"
    assert result["requested"] == 1
    assert result["failed"] == 1
    assert result["stored"] == 0
    assert result["error"] == "storage_capacity_profile_collection_failed"


def test_storage_capacity_task_rejects_invalid_input_before_collection(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Task-boundary validation rejects non-string payloads before the public port."""

    monkeypatch.setattr(
        "apps.config_center.application.tasks.collect_and_record_storage_capacity_profile",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not collect")),
    )

    result = collect_storage_capacity_profile_task(environment=1)  # type: ignore[arg-type]

    assert result["outcome"] == "failed"
    assert result["failed"] == 1
    assert result["error"] == "environment and source must be strings"
