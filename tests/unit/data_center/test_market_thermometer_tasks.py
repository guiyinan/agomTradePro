"""Tests for market thermometer Celery tasks."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from apps.data_center.application import tasks


def test_resolve_market_thermometer_as_of_date_uses_previous_business_day_before_close(
    monkeypatch,
):
    monkeypatch.setattr(
        tasks.timezone,
        "localtime",
        lambda: datetime(2026, 5, 25, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert tasks._resolve_market_thermometer_as_of_date() == date(2026, 5, 22)


def test_refresh_market_thermometer_task_runs_sync_then_calculate(monkeypatch):
    calls: list[tuple[str, date]] = []

    class _SyncUseCase:
        def execute(self, *, as_of_date: date):
            calls.append(("sync", as_of_date))
            return {"as_of_date": as_of_date.isoformat(), "results": []}

    class _CalcUseCase:
        def execute(self, *, as_of_date: date):
            calls.append(("calculate", as_of_date))
            return SimpleNamespace(
                to_dict=lambda: {
                    "observed_at": as_of_date.isoformat(),
                    "score": 48.89,
                    "valid_component_count": 4,
                    "data_source": "degraded",
                }
            )

    monkeypatch.setattr(
        tasks,
        "make_sync_market_thermometer_inputs_use_case",
        lambda: _SyncUseCase(),
    )
    monkeypatch.setattr(
        tasks,
        "make_calculate_market_thermometer_use_case",
        lambda: _CalcUseCase(),
    )

    payload = tasks.refresh_market_thermometer_task.run(as_of_date="2026-05-22")

    assert calls == [("sync", date(2026, 5, 22)), ("calculate", date(2026, 5, 22))]
    assert payload["snapshot"]["score"] == 48.89
