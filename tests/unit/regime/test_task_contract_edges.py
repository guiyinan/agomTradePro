"""Regime scheduled-task success, skip, change, and health contracts."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from apps.regime.application import tasks


def test_calculate_regime_task_skips_failed_sync_and_serializes_result(monkeypatch) -> None:
    """A failed upstream sync skips work while a valid snapshot is fully serialized."""
    resolver_calls = 0

    def resolve(**kwargs):
        nonlocal resolver_calls
        resolver_calls += 1
        return SimpleNamespace(
            dominant_regime="Recovery",
            confidence=0.82,
            distribution={"Recovery": 0.82},
            warnings=["stale-cpi"],
            data_source="pit",
            is_fallback=False,
            growth_momentum_z=0.31,
            inflation_momentum_z=-0.42,
        )

    monkeypatch.setattr(tasks, "resolve_current_regime", resolve)
    skipped = tasks.calculate_regime_task.run(
        {"success": False, "error": "postgresql://user:secret@database"}
    )
    assert skipped == {"status": "skipped", "reason": "sync_failed"}
    assert resolver_calls == 0

    result = tasks.calculate_regime_task.run(None, "2026-07-24", True)
    assert result == {
        "status": "success",
        "as_of_date": "2026-07-24",
        "dominant_regime": "Recovery",
        "confidence": 0.82,
        "distribution": {"Recovery": 0.82},
        "growth_z": 0.31,
        "inflation_z": -0.42,
        "warnings": ["stale-cpi"],
        "source": "pit",
        "is_fallback": False,
    }
    assert resolver_calls == 1


@pytest.mark.parametrize(
    "sync_result",
    [
        {"success": "false"},
        {"success": 0},
    ],
)
def test_calculate_regime_task_rejects_invalid_sync_contract(
    monkeypatch,
    sync_result,
) -> None:
    """Malformed upstream status must fail before the Regime resolver runs."""

    def fail_resolution(**kwargs):
        pytest.fail("resolver must not be called")

    monkeypatch.setattr(tasks, "resolve_current_regime", fail_resolution)

    with pytest.raises(ValueError, match="sync_result.success must be a boolean"):
        tasks.calculate_regime_task.run(sync_result)


def test_calculate_regime_task_rejects_invalid_date_before_resolution(monkeypatch) -> None:
    """Deterministic input errors must not open the calculation boundary."""

    def fail_resolution(**kwargs):
        pytest.fail("resolver must not be called")

    monkeypatch.setattr(tasks, "resolve_current_regime", fail_resolution)

    with pytest.raises(ValueError, match="as_of_date must use YYYY-MM-DD format"):
        tasks.calculate_regime_task.run(None, "2026-02-30")


def test_notification_and_health_tasks_cover_change_stale_and_missing(monkeypatch) -> None:
    """Notification compares the previous snapshot and health exposes stale evidence."""
    assert (
        tasks.notify_regime_change.run({"status": "skipped"})["reason"] == "regime_not_successful"
    )

    previous = SimpleNamespace(dominant_regime="Overheat", confidence=0.9)
    stale = SimpleNamespace(
        dominant_regime="Recovery",
        confidence=0.1,
        observed_at=date.today() - timedelta(days=10),
    )
    repo = SimpleNamespace(
        get_latest_snapshot=lambda before_date=None: previous if before_date else stale,
    )
    monkeypatch.setattr(tasks, "get_regime_repository", lambda: repo)
    notified = tasks.notify_regime_change.run(
        {
            "status": "success",
            "as_of_date": "2026-07-24",
            "dominant_regime": "Recovery",
            "confidence": 0.5,
        }
    )
    assert notified["notified"] is True
    health = tasks.check_regime_health.run()
    assert health["health"] == "warning"
    assert health["is_stale"] is True
    assert health["is_low_confidence"] is True

    monkeypatch.setattr(
        tasks,
        "get_regime_repository",
        lambda: SimpleNamespace(get_latest_snapshot=lambda: None),
    )
    assert tasks.check_regime_health.run()["status"] == "error"


def test_notification_validates_payload_before_repository_access(monkeypatch) -> None:
    """A successful marker is insufficient without typed calculation fields."""

    repository_calls = 0

    def get_repository():
        nonlocal repository_calls
        repository_calls += 1
        return object()

    monkeypatch.setattr(tasks, "get_regime_repository", get_repository)

    with pytest.raises(ValueError, match="dominant_regime must be a non-empty string"):
        tasks.notify_regime_change.run(
            {
                "status": "success",
                "as_of_date": "2026-07-24",
                "confidence": 0.5,
            }
        )

    assert repository_calls == 0


def test_health_rejects_invalid_persisted_confidence(monkeypatch) -> None:
    """Monitoring reports corrupt persisted confidence as a stable error."""

    snapshot = SimpleNamespace(
        dominant_regime="Recovery",
        confidence=float("nan"),
        observed_at=date.today(),
    )
    monkeypatch.setattr(
        tasks,
        "get_regime_repository",
        lambda: SimpleNamespace(get_latest_snapshot=lambda: snapshot),
    )

    assert tasks.check_regime_health.run() == {
        "status": "error",
        "error": "Latest Regime snapshot is invalid.",
        "error_code": "INVALID_REGIME_SNAPSHOT",
    }
