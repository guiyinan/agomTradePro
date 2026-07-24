"""Regime scheduled-task success, skip, change, and health contracts."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from apps.regime.application import tasks


def test_calculate_regime_task_skips_failed_sync_and_serializes_result(monkeypatch) -> None:
    """A failed upstream sync skips work while a valid snapshot is fully serialized."""
    skipped = tasks.calculate_regime_task.run({"success": False, "error": "offline"})
    assert skipped["reason"] == "sync_failed"

    monkeypatch.setattr(
        tasks,
        "resolve_current_regime",
        lambda **kwargs: SimpleNamespace(
            dominant_regime="Recovery",
            confidence=0.82,
            distribution={"Recovery": 0.82},
            warnings=["stale-cpi"],
            data_source="pit",
            is_fallback=False,
        ),
    )
    result = tasks.calculate_regime_task.run(None, "2026-07-24", True)
    assert result["status"] == "success"
    assert result["dominant_regime"] == "Recovery"
    assert result["distribution"] == {"Recovery": 0.82}


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
