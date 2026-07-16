"""Tests for market thermometer Celery tasks."""

from __future__ import annotations

import json
from datetime import date, datetime
from io import StringIO
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.data_center.application import tasks
from apps.data_center.application.market_thermometer_dates import (
    resolve_market_thermometer_as_of_date,
)
from apps.data_center.management.commands import calculate_market_thermometer as calculate_command
from apps.data_center.management.commands import import_investor_accounts as import_command
from apps.data_center.management.commands import sync_market_thermometer_inputs as sync_command


def test_resolve_market_thermometer_as_of_date_uses_previous_business_day_before_close():
    assert resolve_market_thermometer_as_of_date(
        now=datetime(2026, 5, 25, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    ) == date(2026, 5, 22)
    assert tasks._resolve_market_thermometer_as_of_date("2026-05-21") == date(2026, 5, 21)


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


def test_decision_quote_degraded_alerts_once_on_third_consecutive_run(monkeypatch):
    values: dict[str, int] = {}
    alerts: list[dict] = []
    monkeypatch.setattr(
        tasks,
        "refresh_decision_quote_snapshots",
        lambda **_kwargs: {
            "status": "success",
            "synced_count": 1,
            "must_not_use_for_decision": False,
            "readiness": {"data_source": "degraded"},
        },
    )
    monkeypatch.setattr(tasks.cache, "get", lambda key, default=0: values.get(key, default))
    monkeypatch.setattr(
        tasks.cache, "set", lambda key, value, timeout: values.__setitem__(key, value)
    )
    monkeypatch.setattr(tasks, "record_operational_alert", lambda **kwargs: alerts.append(kwargs))

    for _ in range(4):
        payload = tasks.refresh_decision_quote_snapshots_task.run()

    assert payload["degraded"] is True
    assert values[tasks.DECISION_QUOTE_DEGRADED_STREAK_KEY] == 4
    assert len(alerts) == 1
    assert alerts[0]["level"] == "warning"


def test_decision_quote_blocked_alerts_immediately(monkeypatch):
    alerts: list[dict] = []
    monkeypatch.setattr(
        tasks,
        "refresh_decision_quote_snapshots",
        lambda **_kwargs: {
            "status": "failure",
            "synced_count": 0,
            "must_not_use_for_decision": True,
            "readiness": {},
        },
    )
    monkeypatch.setattr(tasks.cache, "get", lambda *_args: 0)
    monkeypatch.setattr(tasks.cache, "set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "record_operational_alert", lambda **kwargs: alerts.append(kwargs))

    tasks.refresh_decision_quote_snapshots_task.run()

    assert len(alerts) == 1
    assert alerts[0]["level"] == "critical"


def test_sync_market_thermometer_command_resolves_default_date(monkeypatch):
    captured: dict[str, date] = {}

    class _SyncUseCase:
        def execute(self, *, as_of_date: date):
            captured["as_of_date"] = as_of_date
            return {"as_of_date": as_of_date.isoformat(), "results": []}

    monkeypatch.setattr(
        sync_command,
        "resolve_market_thermometer_as_of_date",
        lambda raw="": date(2026, 5, 22),
    )
    monkeypatch.setattr(
        sync_command,
        "make_sync_market_thermometer_inputs_use_case",
        lambda: _SyncUseCase(),
    )

    call_command("sync_market_thermometer_inputs", stdout=StringIO())

    assert captured["as_of_date"] == date(2026, 5, 22)


def test_sync_market_thermometer_command_can_emit_json(monkeypatch):
    class _SyncUseCase:
        def execute(self, *, as_of_date: date):
            return {
                "as_of_date": as_of_date.isoformat(),
                "results": [
                    {
                        "component": "etf_net_flow",
                        "provider": "AKShare Public",
                        "status": "error",
                        "error": "timed out",
                    }
                ],
            }

    monkeypatch.setattr(
        sync_command,
        "resolve_market_thermometer_as_of_date",
        lambda raw="": date(2026, 5, 22),
    )
    monkeypatch.setattr(
        sync_command,
        "make_sync_market_thermometer_inputs_use_case",
        lambda: _SyncUseCase(),
    )

    output = StringIO()
    call_command("sync_market_thermometer_inputs", "--json", stdout=output)

    payload = json.loads(output.getvalue())
    assert payload["as_of_date"] == "2026-05-22"
    assert payload["results"][0]["component"] == "etf_net_flow"
    assert payload["results"][0]["status"] == "error"


def test_import_investor_accounts_command_accepts_file_option(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class _ImportUseCase:
        def execute(self, csv_text: str, **kwargs):
            captured["csv_text"] = csv_text
            captured["kwargs"] = kwargs
            return {"stored_count": 1}

    csv_path = tmp_path / "investor_accounts.csv"
    csv_path.write_text("reporting_period,value\n2026-05-31,12345\n", encoding="utf-8")
    monkeypatch.setattr(
        import_command,
        "make_import_investor_accounts_use_case",
        lambda: _ImportUseCase(),
    )

    output = StringIO()
    call_command("import_investor_accounts", "--file", str(csv_path), stdout=output)

    assert captured["csv_text"] == "reporting_period,value\n2026-05-31,12345\n"
    assert captured["kwargs"] == {"dry_run": False, "value_unit": "户"}
    assert "'stored_count': 1" in output.getvalue()


def test_import_investor_accounts_command_passes_dry_run(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class _ImportUseCase:
        def execute(self, csv_text: str, **kwargs):
            captured["csv_text"] = csv_text
            captured["kwargs"] = kwargs
            return {
                "dry_run": True,
                "parsed_count": 1,
                "stored_count": 0,
                "warnings": [
                    {
                        "code": "suspicious_low_account_count",
                        "message": "check unit",
                    }
                ],
            }

    csv_path = tmp_path / "investor_accounts.csv"
    csv_path.write_text("reporting_period,value\n2026-05-31,12345\n", encoding="utf-8")
    monkeypatch.setattr(
        import_command,
        "make_import_investor_accounts_use_case",
        lambda: _ImportUseCase(),
    )

    output = StringIO()
    call_command(
        "import_investor_accounts",
        "--file",
        str(csv_path),
        "--dry-run",
        "--json",
        "--value-unit",
        "万户",
        stdout=output,
    )

    assert captured["csv_text"] == "reporting_period,value\n2026-05-31,12345\n"
    assert captured["kwargs"] == {"dry_run": True, "value_unit": "万户"}
    assert json.loads(output.getvalue()) == {
        "dry_run": True,
        "parsed_count": 1,
        "stored_count": 0,
        "warnings": [
            {
                "code": "suspicious_low_account_count",
                "message": "check unit",
            }
        ],
    }

    fail_output = StringIO()
    with pytest.raises(CommandError, match="CSV has warnings"):
        call_command(
            "import_investor_accounts",
            "--file",
            str(csv_path),
            "--dry-run",
            "--json",
            "--fail-on-warning",
            "--value-unit",
            "万户",
            stdout=fail_output,
        )
    assert json.loads(fail_output.getvalue())["warnings"][0]["code"] == (
        "suspicious_low_account_count"
    )


def test_import_investor_accounts_command_prints_template_without_path():
    output = StringIO()

    call_command("import_investor_accounts", "--print-template", stdout=output)

    assert output.getvalue() == "reporting_period,value\n2026-05-31,12345\n"


def test_import_investor_accounts_command_requires_path():
    with pytest.raises(CommandError, match="CSV path is required"):
        call_command("import_investor_accounts", stdout=StringIO())


def test_calculate_market_thermometer_command_resolves_default_date(monkeypatch):
    captured: dict[str, date] = {}
    sync_calls: list[date] = []

    class _SyncUseCase:
        def execute(self, *, as_of_date: date):
            sync_calls.append(as_of_date)
            return {"as_of_date": as_of_date.isoformat(), "results": []}

    class _CalcUseCase:
        def execute(self, *, as_of_date: date, persist_blocked: bool = True):
            captured["as_of_date"] = as_of_date
            captured["persist_blocked"] = persist_blocked
            return SimpleNamespace(
                must_not_use_for_decision=False,
                to_dict=lambda: {
                    "observed_at": as_of_date.isoformat(),
                    "score": 50.0,
                    "valid_component_count": 4,
                    "must_not_use_for_decision": False,
                },
            )

    monkeypatch.setattr(
        calculate_command,
        "resolve_market_thermometer_as_of_date",
        lambda raw="": date(2026, 5, 22),
    )
    monkeypatch.setattr(
        calculate_command,
        "make_calculate_market_thermometer_use_case",
        lambda: _CalcUseCase(),
    )
    monkeypatch.setattr(
        calculate_command,
        "make_sync_market_thermometer_inputs_use_case",
        lambda: _SyncUseCase(),
    )

    output = StringIO()
    call_command("calculate_market_thermometer", stdout=output)

    assert sync_calls == [date(2026, 5, 22)]
    assert captured["as_of_date"] == date(2026, 5, 22)
    assert captured["persist_blocked"] is False
    assert "'persisted': True" in output.getvalue()


def test_calculate_market_thermometer_command_can_emit_json(monkeypatch):
    class _SyncUseCase:
        def execute(self, *, as_of_date: date):
            return {
                "as_of_date": as_of_date.isoformat(),
                "results": [{"component": "turnover", "status": "success"}],
            }

    class _CalcUseCase:
        def execute(self, *, as_of_date: date, persist_blocked: bool = True):
            return SimpleNamespace(
                must_not_use_for_decision=False,
                to_dict=lambda: {
                    "observed_at": as_of_date.isoformat(),
                    "score": 50.0,
                    "valid_component_count": 4,
                    "must_not_use_for_decision": False,
                },
            )

    monkeypatch.setattr(
        calculate_command,
        "resolve_market_thermometer_as_of_date",
        lambda raw="": date(2026, 5, 22),
    )
    monkeypatch.setattr(
        calculate_command,
        "make_calculate_market_thermometer_use_case",
        lambda: _CalcUseCase(),
    )
    monkeypatch.setattr(
        calculate_command,
        "make_sync_market_thermometer_inputs_use_case",
        lambda: _SyncUseCase(),
    )

    output = StringIO()
    call_command("calculate_market_thermometer", "--json", stdout=output)

    payload = json.loads(output.getvalue())
    assert payload["observed_at"] == "2026-05-22"
    assert payload["persisted"] is True
    assert payload["sync"]["results"][0]["component"] == "turnover"


def test_calculate_market_thermometer_command_requires_flag_for_blocked_write(monkeypatch):
    captured: dict[str, object] = {}

    class _CalcUseCase:
        def execute(self, *, as_of_date: date, persist_blocked: bool = True):
            captured["as_of_date"] = as_of_date
            captured["persist_blocked"] = persist_blocked
            return SimpleNamespace(
                must_not_use_for_decision=True,
                to_dict=lambda: {
                    "observed_at": as_of_date.isoformat(),
                    "score": 42.0,
                    "valid_component_count": 2,
                    "must_not_use_for_decision": True,
                },
            )

    monkeypatch.setattr(
        calculate_command,
        "resolve_market_thermometer_as_of_date",
        lambda raw="": date(2026, 5, 22),
    )
    monkeypatch.setattr(
        calculate_command,
        "make_calculate_market_thermometer_use_case",
        lambda: _CalcUseCase(),
    )

    output = StringIO()
    call_command("calculate_market_thermometer", "--skip-sync", stdout=output)

    assert captured == {
        "as_of_date": date(2026, 5, 22),
        "persist_blocked": False,
    }
    assert "'persisted': False" in output.getvalue()
    assert "'blocked_write_skipped': True" in output.getvalue()
