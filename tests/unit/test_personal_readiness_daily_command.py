from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.management import CommandError, call_command

from apps.task_monitor.management.commands import run_personal_readiness_daily as command_module


def _handle_options(tmp_path, **overrides: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "target_date": "2026-06-30",
        "user_id": None,
        "account_id": None,
        "output_dir": str(tmp_path),
        "required_days": 20,
        "calendar_source": "auto",
        "max_qlib_staleness_days": 5,
        "initial_capital": "1000000.00",
        "repair_accounts": False,
        "skip_workspace_refresh": False,
        "skip_weekly_advisor": False,
        "persist_risk_report": False,
        "strict_daily": False,
        "allow_unclosed_target_date": False,
        "print_json": False,
    }
    options.update(overrides)
    return options


def test_resolve_default_readiness_target_date_does_not_hide_stale_qlib_calendar(
    monkeypatch,
):
    monkeypatch.setattr(
        command_module,
        "resolve_recent_closed_trade_date",
        lambda: date(2026, 7, 1),
    )

    assert command_module.resolve_default_readiness_target_date() == date(2026, 7, 1)


def test_runtime_trade_date_boundary_rejects_dynamic_invalid_value(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "import_module",
        lambda name: SimpleNamespace(resolve_recent_closed_trade_date=lambda: "2026-07-01"),
    )

    with pytest.raises(CommandError, match="invalid value"):
        command_module.resolve_recent_closed_trade_date()


def test_runtime_account_repair_boundary_rejects_dynamic_invalid_payload(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "import_module",
        lambda name: SimpleNamespace(
            AccountReadinessRepairRequest=lambda **kwargs: object(),
            repair_personal_account_readiness=lambda request: ["not", "an", "object"],
        ),
    )

    with pytest.raises(CommandError, match="invalid payload"):
        command_module.repair_personal_account_readiness(object())


def test_parse_date_keeps_explicit_target_date(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 6, 30),
    )

    assert command_module._parse_date("2026-07-01") == date(2026, 7, 1)


def test_daily_command_rejects_unclosed_explicit_target_date(monkeypatch, tmp_path):
    run_called = False

    def fake_run(**kwargs):
        nonlocal run_called
        run_called = True
        return {}

    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 6, 30),
    )
    monkeypatch.setattr(command_module, "run_personal_readiness_daily", fake_run)

    with pytest.raises(CommandError, match="later than latest closed trading day"):
        command_module.Command().handle(**_handle_options(tmp_path, target_date="2026-07-01"))

    assert run_called is False


def test_daily_command_allows_unclosed_target_date_for_diagnostics(
    monkeypatch,
    tmp_path,
):
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {
            "status": "ok",
            "evidence": {"status": "ok"},
            "validation": {
                "required_days": 20,
                "accepted_days": 1,
                "remaining_days": 19,
            },
            "evidence_output_paths": {},
        }

    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 6, 30),
    )
    monkeypatch.setattr(command_module, "run_personal_readiness_daily", fake_run)

    command_module.Command().handle(
        **_handle_options(
            tmp_path,
            target_date="2026-07-01",
            allow_unclosed_target_date=True,
        )
    )

    assert captured["target_date"] == date(2026, 7, 1)


def test_daily_command_allows_closed_historical_target_date(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {
            "status": "ok",
            "evidence": {"status": "ok"},
            "validation": {
                "required_days": 20,
                "accepted_days": 1,
                "remaining_days": 19,
            },
            "evidence_output_paths": {},
        }

    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 6, 30),
    )
    monkeypatch.setattr(command_module, "run_personal_readiness_daily", fake_run)

    command_module.Command().handle(**_handle_options(tmp_path, target_date="2026-06-29"))

    assert captured["target_date"] == date(2026, 6, 29)

    help_text = (
        command_module.Command()
        .create_parser(
            "manage.py",
            "run_personal_readiness_daily",
        )
        .format_help()
    )
    assert "--trigger-source" not in help_text

    captured.clear()
    call_command(
        "run_personal_readiness_daily",
        target_date="2026-06-29",
        output_dir=str(tmp_path),
        trigger_source="scheduler",
        stdout=StringIO(),
    )

    assert captured["target_date"] == date(2026, 6, 29)
    assert captured["trigger_source"] == "scheduler"


def test_daily_pipeline_skips_evidence_when_account_repair_requires_action(
    monkeypatch,
    tmp_path,
):
    collect_called = False

    def fake_collect(**kwargs):
        nonlocal collect_called
        collect_called = True
        return {"status": "ok"}

    monkeypatch.setattr(
        command_module,
        "repair_personal_account_readiness",
        lambda request: {
            "status": "action_required",
            "dry_run": request.dry_run,
            "target_count": 1,
            "results": [{"status": "would_create"}],
        },
    )
    monkeypatch.setattr(command_module, "collect_personal_readiness_evidence", fake_collect)
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "in_progress",
            "required_days": 20,
            "accepted_days": 0,
            "remaining_days": 20,
            "blocking_issues": [],
        },
    )

    payload = command_module.run_personal_readiness_daily(
        target_date=date(2026, 6, 30),
        user_id=1,
        account_id=None,
        output_dir=tmp_path,
    )

    assert payload["status"] == "action_required"
    assert payload["account_readiness"]["dry_run"] is True
    assert payload["evidence"]["status"] == "skipped"
    assert collect_called is False


def test_daily_pipeline_collects_evidence_and_validates_window(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_repair(request):
        captured["repair_request"] = request
        return {"status": "ok", "target_count": 1, "results": [{"status": "ok"}]}

    def fake_collect(**kwargs):
        captured["collect_kwargs"] = kwargs
        return {
            "status": "ok",
            "target_date": kwargs["target_date"].isoformat(),
            "summary": {
                "system_status": "ok",
                "qlib_status": "ok",
                "workspace_status": "ok",
                "target_count": 1,
            },
            "accounts": [
                {
                    "account_id": 1,
                    "status": "ok",
                    "risk_center_daily_report": {"status": "ok"},
                    "auto_advisor": {"status": "ok"},
                }
            ],
        }

    monkeypatch.setattr(command_module, "repair_personal_account_readiness", fake_repair)
    monkeypatch.setattr(command_module, "collect_personal_readiness_evidence", fake_collect)
    monkeypatch.setattr(
        command_module,
        "write_personal_readiness_evidence_files",
        lambda **kwargs: {"json": "daily.json", "markdown": "daily.md"},
    )

    def fake_validate(**kwargs):
        captured["validate_kwargs"] = kwargs
        return {
            "status": "in_progress",
            "required_days": kwargs["required_days"],
            "accepted_days": 1,
            "remaining_days": 19,
            "blocking_issues": [],
        }

    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        fake_validate,
    )

    payload = command_module.run_personal_readiness_daily(
        target_date=date(2026, 6, 30),
        user_id=1,
        account_id=2,
        output_dir=tmp_path,
        required_days=20,
        repair_accounts=True,
        initial_capital=Decimal("200000.00"),
        trigger_task_id="task-123",
        trigger_task_name="task-name",
    )

    repair_request = captured["repair_request"]
    collect_kwargs = captured["collect_kwargs"]
    validate_kwargs = captured["validate_kwargs"]

    assert payload["status"] == "ok"
    assert payload["evidence_output_paths"]["json"] == "daily.json"
    assert repair_request.dry_run is False
    assert repair_request.initial_capital == Decimal("200000.00")
    assert collect_kwargs["run_workspace_refresh"] is True
    assert collect_kwargs["include_weekly_advisor"] is True
    assert collect_kwargs["persist_risk_report"] is False
    assert collect_kwargs["allow_unclosed_target_date"] is False
    assert collect_kwargs["trigger_source"] == "manual"
    assert collect_kwargs["trigger_task_id"] == "task-123"
    assert collect_kwargs["trigger_task_name"] == "task-name"
    assert validate_kwargs["expected_latest_date"] == date(2026, 6, 30)
    assert payload["inputs"]["calendar_source"] == "auto"
    assert payload["inputs"]["allow_unclosed_target_date"] is False
    assert payload["inputs"]["trigger_source"] == "manual"
    assert payload["inputs"]["trigger_task_id"] == "task-123"
    assert payload["inputs"]["trigger_task_name"] == "task-name"


def test_daily_command_strict_daily_raises_when_not_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(
        command_module,
        "run_personal_readiness_daily",
        lambda **kwargs: {
            "status": "action_required",
            "evidence": {"status": "skipped"},
            "validation": {
                "required_days": 20,
                "accepted_days": 0,
                "remaining_days": 20,
            },
            "evidence_output_paths": {},
        },
    )

    with pytest.raises(CommandError):
        command_module.Command().handle(**_handle_options(tmp_path, strict_daily=True))
