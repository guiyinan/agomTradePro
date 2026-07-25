from __future__ import annotations

import json
from datetime import date, datetime
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import CommandError, call_command

from apps.task_monitor.management.commands import (
    collect_personal_readiness_evidence as command_module,
)


@pytest.fixture(autouse=True)
def _closed_trade_date(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 6, 30),
    )
    monkeypatch.setattr(
        command_module,
        "collect_quote_pre_readiness_scheduler_status",
        lambda: {
            "status": "ok",
            "enabled": True,
            "name": "decision-quote-pre-readiness-refresh",
            "schedule": {
                "hour": "18",
                "minute": "20",
                "day_of_week": "1,2,3,4,5",
                "timezone": "Asia/Shanghai",
            },
            "run_metadata": {
                "last_run_at": "2026-06-30T18:20:00+08:00",
                "total_run_count": 1,
            },
            "safety": {"status": "ok", "issues": []},
        },
    )
    monkeypatch.setattr(
        command_module,
        "get_broker_execution_readiness_evidence",
        lambda **kwargs: {
            "status": "skipped",
            "reason": "live_broker_binding_not_configured",
            "account_id": kwargs["account_id"],
        },
    )


def test_parse_date_defaults_to_latest_closed_trading_day():
    assert command_module._parse_date(None) == date(2026, 6, 30)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"user_id": 0}, "user-id must be a positive integer"),
        ({"account_id": -1}, "account-id must be a positive integer"),
        (
            {"max_qlib_staleness_days": -1},
            "max-qlib-staleness-days must be non-negative",
        ),
    ],
)
def test_collect_personal_readiness_evidence_rejects_invalid_direct_inputs(kwargs, message):
    options = {
        "target_date": date(2026, 6, 30),
        "user_id": None,
        "account_id": None,
    }
    options.update(kwargs)

    with pytest.raises(CommandError, match=message):
        command_module.collect_personal_readiness_evidence(**options)


def test_collect_personal_readiness_evidence_rejects_unclosed_direct_target():
    with pytest.raises(CommandError, match="later than latest closed trading day"):
        command_module.collect_personal_readiness_evidence(
            target_date=date(2026, 7, 1),
            user_id=None,
            account_id=None,
        )


def test_readiness_rollup_fails_closed_on_unknown_status():
    assert command_module._rollup_status(["ok", "unknown", "skipped"]) == "error"


def test_collect_personal_readiness_evidence_includes_scheduler_in_status(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "_collect_system_readiness",
        lambda **kwargs: {"status": "ok", "checks": {}},
    )
    monkeypatch.setattr(
        command_module,
        "_collect_qlib_readiness",
        lambda **kwargs: {"status": "ok"},
    )
    monkeypatch.setattr(
        command_module,
        "_collect_workspace_refresh",
        lambda **kwargs: {"status": "skipped"},
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_evidence",
        lambda **kwargs: {
            "quote_pre_readiness_scheduler": {
                "status": "error",
                "reason": "scheduler_unavailable",
            }
        },
    )
    monkeypatch.setattr(command_module, "_resolve_targets", lambda **kwargs: [])

    payload = command_module.collect_personal_readiness_evidence(
        target_date=date(2026, 6, 30),
        user_id=None,
        account_id=None,
    )

    assert payload["status"] == "error"
    assert payload["summary"]["quote_pre_readiness_scheduler_status"] == "error"


def test_pre_trade_probe_requires_observed_symbol_and_price():
    assert (
        command_module._build_pre_trade_probe(
            account_equity=100000.0,
            cash_balance=50000.0,
            total_position_value=0.0,
            positions=[],
        )
        is None
    )
    assert (
        command_module._build_pre_trade_probe(
            account_equity=100000.0,
            cash_balance=50000.0,
            total_position_value=10000.0,
            positions=[{"asset_code": "000001.SZ", "market_value": 10000.0}],
        )
        is None
    )


def test_optional_float_rejects_non_finite_values():
    assert command_module._optional_float(float("nan")) is None
    assert command_module._optional_float(float("inf")) is None


def test_collect_personal_readiness_evidence_runs_account_chain(monkeypatch):
    captured: dict[str, object] = {}

    class FakeRiskUseCase:
        def execute(self, **kwargs):
            captured["risk_kwargs"] = kwargs
            return SimpleNamespace(
                report_id=None,
                risk_daily_report={"status": "ok", "headline": "ok"},
                position_daily_report={"position_count": 1},
                post_investment_check={"passed": True},
            )

    class FakePreTradeUseCase:
        def execute(self, **kwargs):
            captured["pre_trade_kwargs"] = kwargs
            return SimpleNamespace(
                passed=True,
                violations=[],
                warnings=[],
                metrics={"projected_total_position_pct": 0.76},
                effective_policy={"account_id": kwargs["account_id"]},
            )

    user = SimpleNamespace(id=7, is_authenticated=True, is_staff=False)

    monkeypatch.setattr(
        command_module,
        "run_readiness_checks",
        lambda: {
            "database": {"status": "ok"},
            "alpha_workspace_consistency": {
                "status": "ok",
                "checked_account_id": "default",
                "alpha": {
                    "latest_trade_date": "2026-06-30",
                    "latest_updated_at": "2026-06-30T16:00:00+08:00",
                    "top_codes": ["000001.SZ", "000002.SZ"],
                    "provider_source": "qlib",
                    "status": "available",
                },
                "workspace": {
                    "account_id": "default",
                    "latest_updated_at": "2026-06-30T16:10:00+08:00",
                    "recommendation_codes": ["000001.SZ"],
                    "source_candidate_ids": ["alpha_rank:000001.SZ:2026-06-30"],
                    "total_count": 30,
                },
                "issues": [],
            },
        },
    )
    monkeypatch.setattr(command_module, "is_healthy", lambda checks: True)
    monkeypatch.setattr(
        command_module.status_services,
        "build_current_macro_context",
        lambda *, target_date: {
            "regime": {
                "status": "ok",
                "observed_at": target_date,
                "dominant_regime": "Recovery",
                "confidence": 0.34,
                "source": "akshare",
                "is_fallback": False,
                "records_count": 149,
                "warnings": [],
            },
            "pulse": {
                "status": "ok",
                "observed_at": target_date,
                "regime_context": "Recovery",
                "composite_score": 0.107,
                "regime_strength": "moderate",
                "transition_warning": False,
                "transition_direction": None,
                "stale_indicator_count": 0,
                "data_source": "calculated",
            },
        },
    )
    monkeypatch.setattr(command_module, "call_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        command_module,
        "list_active_account_targets",
        lambda: [
            {"user_id": 7, "account_id": 101},
            {"user_id": 7, "account_id": 101},
        ],
    )
    monkeypatch.setattr(
        command_module,
        "list_dashboard_account_payloads",
        lambda user_id: [
            {
                "id": 101,
                "is_active": True,
                "total_value": 100000.0,
                "cash": 25000.0,
                "market_value": 75000.0,
            }
        ],
    )
    monkeypatch.setattr(command_module, "get_application_user_by_id", lambda user_id: user)
    monkeypatch.setattr(
        command_module,
        "get_position_snapshots",
        lambda account_id: [
            {
                "asset_code": "510300.SH",
                "current_price": 4.0,
                "market_value": 75000.0,
            }
        ],
    )
    monkeypatch.setattr(command_module, "GenerateRiskCenterDailyReportUseCase", FakeRiskUseCase)
    monkeypatch.setattr(command_module, "EvaluatePreTradeRiskUseCase", FakePreTradeUseCase)
    monkeypatch.setattr(
        command_module,
        "build_auto_advisor_console_payload",
        lambda *, account_id, user: {"status": "ok", "account": {"id": int(account_id)}},
    )
    monkeypatch.setattr(
        command_module,
        "build_auto_advisor_weekly_report_payload",
        lambda *, account_id, user, as_of: {
            "status": "ok",
            "week": {"as_of": as_of.isoformat()},
        },
    )
    monkeypatch.setattr(
        command_module,
        "build_auto_advisor_weekly_report_history_payload",
        lambda *, user, account_id, limit: {
            "status": "ok",
            "count": 1,
            "reports": [
                {
                    "id": 501,
                    "user_id": user.id,
                    "account_id": int(account_id),
                    "report_date": "2026-06-30",
                    "week_start": "2026-06-29",
                    "week_end": "2026-07-05",
                    "status": "ready",
                    "audit_log_id": "audit-501",
                    "created_at": "2026-06-30T17:30:00+08:00",
                    "updated_at": "2026-06-30T17:31:00+08:00",
                }
            ],
        },
    )
    monkeypatch.setattr(
        command_module,
        "build_auto_advisor_notifications_payload",
        lambda *, user, account_id, limit: {
            "status": "ok",
            "count": 1,
            "notifications": [
                {
                    "id": 701,
                    "report_id": 501,
                    "channel": "dashboard",
                    "delivery_status": "delivered",
                    "delivered_at": "2026-06-30T17:31:00+08:00",
                    "created_at": "2026-06-30T17:31:00+08:00",
                }
            ],
        },
    )

    payload = command_module.collect_personal_readiness_evidence(
        target_date=date(2026, 6, 30),
        user_id=None,
        account_id=None,
        include_weekly_advisor=True,
    )

    assert payload["status"] == "ok"
    assert payload["operation_context"]["mode"] == "formal"
    assert payload["operation_context"]["target_date_closed"] is True
    assert payload["operation_context"]["latest_closed_date"] == "2026-06-30"
    assert payload["operation_context"]["trigger_source"] == "manual"
    assert payload["operation_context"]["trigger_task_id"] is None
    assert payload["operation_context"]["trigger_task_name"] is None
    assert payload["inputs"]["allow_unclosed_target_date"] is False
    assert payload["inputs"]["trigger_source"] == "manual"
    assert (
        payload["scheduler_evidence"]["quote_pre_readiness_scheduler"]["run_metadata"][
            "last_run_at"
        ]
        == "2026-06-30T18:20:00+08:00"
    )
    assert (
        payload["scheduler_evidence"]["quote_pre_readiness_scheduler"]["schedule_expectation"][
            "target_date"
        ]
        == "2026-06-30"
    )
    assert (
        payload["scheduler_evidence"]["quote_pre_readiness_scheduler"]["schedule_expectation"][
            "task_name"
        ]
        == "decision-quote-pre-readiness-refresh"
    )
    assert payload["summary"]["quote_pre_readiness_scheduler_status"] == "ok"
    assert payload["summary"]["target_count"] == 1
    assert payload["summary"]["alpha_workspace_consistency"]["alpha"]["provider_source"] == "qlib"
    assert payload["summary"]["alpha_workspace_consistency"]["workspace"]["total_count"] == 30
    assert payload["system"]["checks"]["regime"]["dominant_regime"] == "Recovery"
    assert payload["system"]["checks"]["regime"]["observed_at"] == date(2026, 6, 30)
    assert payload["system"]["checks"]["pulse"]["composite_score"] == 0.107
    assert payload["system"]["checks"]["pulse"]["stale_indicator_count"] == 0
    assert payload["accounts"][0]["status"] == "ok"
    assert payload["accounts"][0]["risk_center_daily_report"]["pre_trade_check"]["status"] == "ok"
    assert payload["accounts"][0]["risk_center_daily_report"]["pre_trade_check"]["passed"] is True
    assert payload["accounts"][0]["auto_advisor"]["weekly_report"]["week"]["as_of"] == "2026-06-30"
    persistence = payload["accounts"][0]["auto_advisor"]["weekly_report_persistence"]
    assert persistence["status"] == "ok"
    assert persistence["target_report_date"] == "2026-06-30"
    assert persistence["matched_report"]["audit_log_id"] == "audit-501"
    assert persistence["delivered_notification_count"] == 1
    assert captured["risk_kwargs"]["persist"] is False
    assert captured["risk_kwargs"]["account_equity"] == 100000.0
    assert captured["pre_trade_kwargs"]["account_id"] == 101
    assert captured["pre_trade_kwargs"]["side"] == "buy"
    assert captured["pre_trade_kwargs"]["symbol"] == "510300.SH"


def test_enrich_quote_pre_readiness_scheduler_evidence_marks_completed_run():
    payload = command_module._enrich_quote_pre_readiness_scheduler_evidence(
        quote_pre_readiness_scheduler={
            "status": "ok",
            "enabled": True,
            "name": "decision-quote-pre-readiness-refresh",
            "task": "apps.data_center.application.tasks.refresh_decision_quote_snapshots_task",
            "schedule": {
                "hour": "15",
                "minute": "35",
                "day_of_week": "1,2,3,4,5",
                "day_of_month": "*",
                "month_of_year": "*",
                "timezone": "Asia/Shanghai",
            },
            "run_metadata": {
                "last_run_at": "2026-07-08T15:36:00+08:00",
                "total_run_count": 3,
            },
            "safety": {"status": "ok", "issues": []},
        },
        target_date=date(2026, 7, 8),
        current_time=datetime.fromisoformat("2026-07-08T16:05:00+08:00"),
    )

    assert payload["status"] == "ok"
    assert payload["schedule_expectation"]["target_date"] == "2026-07-08"
    assert payload["schedule_expectation"]["due_status"] == "completed"
    assert payload["schedule_expectation"]["completed_at"] == "2026-07-08T15:36:00+08:00"


def test_enrich_quote_pre_readiness_scheduler_evidence_marks_overdue_run():
    payload = command_module._enrich_quote_pre_readiness_scheduler_evidence(
        quote_pre_readiness_scheduler={
            "status": "ok",
            "enabled": True,
            "name": "decision-quote-pre-readiness-refresh",
            "task": "apps.data_center.application.tasks.refresh_decision_quote_snapshots_task",
            "schedule": {
                "hour": "15",
                "minute": "35",
                "day_of_week": "1,2,3,4,5",
                "day_of_month": "*",
                "month_of_year": "*",
                "timezone": "Asia/Shanghai",
            },
            "run_metadata": {
                "last_run_at": "2026-07-03T15:35:00+08:00",
                "total_run_count": 2,
            },
            "safety": {"status": "ok", "issues": []},
        },
        target_date=date(2026, 7, 7),
        current_time=datetime.fromisoformat("2026-07-08T12:30:00+08:00"),
    )

    assert payload["status"] == "warning"
    assert payload["schedule_expectation"]["due_status"] == "overdue"
    assert payload["safety"]["issues"][-1]["code"] == "quote_pre_readiness_run_missing_after_grace"


def test_weekly_report_persistence_evidence_warns_without_delivered_notification():
    payload = command_module._build_weekly_report_persistence_evidence(
        target_date=date(2026, 6, 30),
        history={
            "status": "ok",
            "count": 1,
            "reports": [
                {
                    "id": 501,
                    "report_date": "2026-06-30",
                    "status": "ready",
                    "audit_log_id": "audit-501",
                }
            ],
        },
        notifications={
            "status": "ok",
            "count": 1,
            "notifications": [
                {
                    "id": 701,
                    "report_id": 501,
                    "delivery_status": "pending",
                }
            ],
        },
    )

    assert payload["status"] == "warning"
    assert payload["target_report_date"] == "2026-06-30"
    assert payload["matched_report"]["id"] == 501
    assert payload["matched_notification_count"] == 1
    assert payload["delivered_notification_count"] == 0


def test_collect_risk_report_records_persisted_report_id(monkeypatch):
    class FakeRiskUseCase:
        def execute(self, **kwargs):
            assert kwargs["persist"] is True
            return SimpleNamespace(
                report_id=901,
                risk_daily_report={"status": "ok"},
                position_daily_report={"position_count": 1},
                post_investment_check={"passed": True},
            )

    class FakePreTradeUseCase:
        def execute(self, **kwargs):
            return SimpleNamespace(
                passed=True,
                violations=[],
                warnings=[],
                metrics={},
                effective_policy={"account_id": kwargs["account_id"]},
            )

    monkeypatch.setattr(
        command_module,
        "get_position_snapshots",
        lambda account_id: [
            {
                "asset_code": "510300.SH",
                "current_price": 4.0,
                "market_value": 75000.0,
            }
        ],
    )
    monkeypatch.setattr(command_module, "GenerateRiskCenterDailyReportUseCase", FakeRiskUseCase)
    monkeypatch.setattr(command_module, "EvaluatePreTradeRiskUseCase", FakePreTradeUseCase)

    payload = command_module._collect_risk_report(
        user=SimpleNamespace(id=7),
        account_id=101,
        account_payload={
            "total_value": 100000.0,
            "cash": 25000.0,
            "market_value": 75000.0,
        },
        target_date=date(2026, 6, 30),
        persist=True,
    )

    assert payload["status"] == "ok"
    assert payload["persisted"] is True
    assert payload["report_id"] == 901
    assert payload["pre_trade_check"]["status"] == "ok"
    assert payload["post_investment_check"]["passed"] is True


def test_operation_context_marks_closed_override_as_diagnostic():
    payload = command_module._build_operation_context(
        target_date=date(2026, 6, 30),
        latest_closed_date=date(2026, 6, 30),
        allow_unclosed_target_date=True,
        trigger_source="scheduler",
        trigger_task_id="task-123",
        trigger_task_name="apps.task_monitor.application.tasks.run_personal_readiness_daily_task",
    )

    assert payload["target_date_closed"] is True
    assert payload["allow_unclosed_target_date"] is True
    assert payload["mode"] == "diagnostic_override"
    assert payload["trigger_source"] == "scheduler"
    assert payload["trigger_task_id"] == "task-123"
    assert (
        payload["trigger_task_name"]
        == "apps.task_monitor.application.tasks.run_personal_readiness_daily_task"
    )


def test_operation_context_marks_unclosed_override_as_diagnostic():
    payload = command_module._build_operation_context(
        target_date=date(2026, 7, 1),
        latest_closed_date=date(2026, 6, 30),
        allow_unclosed_target_date=True,
    )

    assert payload["target_date_closed"] is False
    assert payload["allow_unclosed_target_date"] is True
    assert payload["mode"] == "diagnostic_unclosed_target"
    assert payload["trigger_source"] == "manual"


def test_collect_personal_readiness_evidence_marks_qlib_staleness_as_warning(monkeypatch):
    def fake_call_command(*args, **kwargs):
        raise CommandError("qlib stale")

    monkeypatch.setattr(
        command_module,
        "run_readiness_checks",
        lambda: {"database": {"status": "ok"}},
    )
    monkeypatch.setattr(command_module, "is_healthy", lambda checks: True)
    monkeypatch.setattr(command_module, "call_command", fake_call_command)
    monkeypatch.setattr(command_module, "list_active_account_targets", lambda: [])

    payload = command_module.collect_personal_readiness_evidence(
        target_date=date(2026, 6, 30),
        user_id=None,
        account_id=None,
    )

    assert payload["status"] == "warning"
    assert payload["qlib"]["status"] == "warning"
    assert payload["qlib"]["error"] == "qlib stale"


def test_collect_personal_readiness_evidence_prefers_positive_equity_accounts(monkeypatch):
    captured_accounts: list[int] = []

    class FakeRiskUseCase:
        def execute(self, **kwargs):
            captured_accounts.append(int(kwargs["account_id"]))
            return SimpleNamespace(
                report_id=None,
                risk_daily_report={"status": "ok"},
                position_daily_report={},
                post_investment_check={"passed": True},
            )

    class FakePreTradeUseCase:
        def execute(self, **kwargs):
            return SimpleNamespace(
                passed=True,
                violations=[],
                warnings=[],
                metrics={},
                effective_policy={"account_id": kwargs["account_id"]},
            )

    monkeypatch.setattr(
        command_module,
        "run_readiness_checks",
        lambda: {"database": {"status": "ok"}},
    )
    monkeypatch.setattr(command_module, "is_healthy", lambda checks: True)
    monkeypatch.setattr(command_module, "call_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        command_module,
        "list_active_account_targets",
        lambda: [
            {"user_id": 7, "account_id": 101},
            {"user_id": 7, "account_id": 102},
        ],
    )
    monkeypatch.setattr(
        command_module,
        "list_dashboard_account_payloads",
        lambda user_id: [
            {"id": 101, "is_active": True, "total_value": 0.0, "cash": 0.0},
            {
                "id": 102,
                "is_active": True,
                "total_value": 100000.0,
                "cash": 100000.0,
                "market_value": 0.0,
            },
        ],
    )
    monkeypatch.setattr(
        command_module,
        "get_application_user_by_id",
        lambda user_id: SimpleNamespace(id=user_id, is_authenticated=True),
    )
    monkeypatch.setattr(command_module, "get_position_snapshots", lambda account_id: [])
    monkeypatch.setattr(command_module, "GenerateRiskCenterDailyReportUseCase", FakeRiskUseCase)
    monkeypatch.setattr(command_module, "EvaluatePreTradeRiskUseCase", FakePreTradeUseCase)
    monkeypatch.setattr(
        command_module,
        "build_auto_advisor_console_payload",
        lambda *, account_id, user: {"status": "ok"},
    )

    payload = command_module.collect_personal_readiness_evidence(
        target_date=date(2026, 6, 30),
        user_id=None,
        account_id=None,
    )

    assert payload["summary"]["target_count"] == 1
    assert payload["accounts"][0]["account_id"] == 102
    assert captured_accounts == [102]


def test_command_writes_json_and_markdown_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(
        command_module,
        "collect_personal_readiness_evidence",
        lambda **kwargs: {
            "schema_version": "test",
            "status": "ok",
            "target_date": kwargs["target_date"].isoformat(),
            "generated_at": "2026-06-30T00:00:00+00:00",
            "operation_context": {
                "mode": "formal",
                "trigger_source": "scheduler",
                "trigger_task_name": "apps.task_monitor.application.tasks.run_personal_readiness_daily_task",
                "trigger_task_id": "task-123",
                "target_date_closed": True,
                "latest_closed_date": "2026-06-30",
                "allow_unclosed_target_date": False,
            },
            "summary": {
                "system_status": "ok",
                "qlib_status": "ok",
                "workspace_status": "skipped",
                "quote_pre_readiness_scheduler_status": "ok",
                "macro_context": {
                    "regime": {
                        "status": "ok",
                        "observed_at": "2026-06-30",
                        "dominant_regime": "Recovery",
                        "confidence": 0.34,
                        "source": "akshare",
                        "is_fallback": False,
                        "records_count": 149,
                        "warnings": [],
                    },
                    "pulse": {
                        "status": "ok",
                        "observed_at": "2026-06-30",
                        "regime_context": "Recovery",
                        "composite_score": 0.107,
                        "regime_strength": "moderate",
                        "transition_warning": False,
                        "transition_direction": None,
                        "stale_indicator_count": 0,
                        "data_source": "calculated",
                    },
                },
                "alpha_workspace_consistency": {
                    "status": "ok",
                    "checked_account_id": "default",
                    "issue_codes": [],
                    "alpha": {
                        "latest_trade_date": "2026-06-30",
                        "latest_updated_at": "2026-06-30T16:00:00+08:00",
                        "provider_source": "qlib",
                        "status": "available",
                        "top_codes": ["000001.SZ", "000002.SZ"],
                    },
                    "workspace": {
                        "account_id": "default",
                        "latest_updated_at": "2026-06-30T16:10:00+08:00",
                        "recommendation_codes": ["000001.SZ"],
                        "source_candidate_id_count": 2,
                        "total_count": 30,
                    },
                },
                "decision_data": {
                    "status": "ok",
                    "readiness_status": "ok",
                    "must_not_use_for_decision": False,
                    "blocked_reasons": [],
                    "market_thermometer": {
                        "status": "ok",
                        "observed_at": "2026-06-29",
                        "data_source": "database",
                        "blocked_reason": None,
                        "stale_components": [],
                        "missing_components": [],
                    },
                    "skipped_latest_market_thermometer": {
                        "status": "skipped",
                        "observed_at": "2026-06-30",
                        "data_source": "database",
                        "skip_reason": "latest_snapshot_after_decision_safe_date",
                        "blocked_reason": None,
                    },
                },
                "target_count": 1,
            },
            "scheduler_evidence": {
                "quote_pre_readiness_scheduler": {
                    "status": "ok",
                    "enabled": True,
                    "schedule": {
                        "hour": "18",
                        "minute": "20",
                        "day_of_week": "1,2,3,4,5",
                        "timezone": "Asia/Shanghai",
                    },
                    "run_metadata": {
                        "last_run_at": "2026-06-30T18:20:00+08:00",
                        "total_run_count": 1,
                    },
                }
            },
            "accounts": [
                {
                    "account_id": 101,
                    "user_id": 7,
                    "status": "ok",
                    "risk_center_daily_report": {
                        "status": "ok",
                        "persisted": True,
                        "report_id": 901,
                        "pre_trade_check": {"status": "ok"},
                        "post_investment_check": {"passed": True},
                    },
                    "auto_advisor": {
                        "status": "ok",
                        "weekly_report_persistence": {
                            "status": "ok",
                            "matched_report": {"id": 501},
                            "delivered_notification_count": 1,
                        },
                    },
                }
            ],
        },
    )

    command_module.Command().handle(
        target_date="2026-06-30",
        user_id=None,
        account_id=None,
        output_dir=str(tmp_path),
        max_qlib_staleness_days=5,
        run_workspace_refresh=False,
        include_weekly_advisor=False,
        persist_risk_report=False,
        write_file=True,
        print_json=False,
    )

    json_path = tmp_path / "2026-06-30-personal-readiness.json"
    markdown_path = tmp_path / "2026-06-30-personal-readiness.md"
    assert json_path.exists()
    assert markdown_path.exists()
    evidence_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert evidence_json["status"] == "ok"
    assert evidence_json["summary"]["macro_context"]["regime"]["dominant_regime"] == "Recovery"
    assert evidence_json["summary"]["macro_context"]["pulse"]["composite_score"] == 0.107
    assert (
        evidence_json["summary"]["alpha_workspace_consistency"]["alpha"]["provider_source"]
        == "qlib"
    )
    assert evidence_json["summary"]["alpha_workspace_consistency"]["workspace"]["total_count"] == 30
    assert (
        evidence_json["summary"]["decision_data"]["skipped_latest_market_thermometer"][
            "skip_reason"
        ]
        == "latest_snapshot_after_decision_safe_date"
    )
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Personal Readiness Evidence" in markdown
    assert "- mode: formal" in markdown
    assert "- trigger_source: scheduler" in markdown
    assert (
        "- trigger_task_name: apps.task_monitor.application.tasks.run_personal_readiness_daily_task"
        in markdown
    )
    assert "- trigger_task_id: task-123" in markdown
    assert "- allow_unclosed_target_date: False" in markdown
    assert "- quote_pre_readiness_scheduler_status: ok" in markdown
    assert "- quote_pre_readiness_enabled: True" in markdown
    assert "- quote_pre_readiness_schedule: 18:20 1,2,3,4,5 Asia/Shanghai" in markdown
    assert "- quote_pre_readiness_last_run_at: 2026-06-30T18:20:00+08:00" in markdown
    assert "## Macro Context" in markdown
    assert "- dominant_regime: Recovery" in markdown
    assert "- regime_confidence: 0.34" in markdown
    assert "- pulse_composite_score: 0.107" in markdown
    assert "- pulse_stale_indicator_count: 0" in markdown
    assert "## Alpha Workspace" in markdown
    assert "- alpha_workspace_status: ok" in markdown
    assert "- alpha_provider_source: qlib" in markdown
    assert "- alpha_top_codes: 000001.SZ, 000002.SZ" in markdown
    assert "- workspace_total_count: 30" in markdown
    assert "- workspace_source_candidate_id_count: 2" in markdown
    assert "## Decision Data" in markdown
    assert "- decision_data_status: ok" in markdown
    assert "- market_thermometer_observed_at: 2026-06-29" in markdown
    assert "- skipped_latest_market_thermometer_observed_at: 2026-06-30" in markdown
    assert (
        "- skipped_latest_market_thermometer_skip_reason: "
        "latest_snapshot_after_decision_safe_date"
    ) in markdown
    assert "### Account 101" in markdown
    assert "- risk_persisted: True" in markdown
    assert "- risk_report_id: 901" in markdown
    assert "- pre_trade_status: ok" in markdown
    assert "- post_investment_passed: True" in markdown
    assert "- weekly_persistence_status: ok" in markdown
    assert "- weekly_persistence_report_id: 501" in markdown
    assert "- weekly_delivered_notifications: 1" in markdown


def test_command_without_target_date_uses_latest_closed_trading_day(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_collect(**kwargs):
        captured.update(kwargs)
        return {
            "schema_version": "test",
            "status": "ok",
            "target_date": kwargs["target_date"].isoformat(),
            "generated_at": "2026-06-30T00:00:00+00:00",
            "summary": {"target_count": 0},
            "accounts": [],
        }

    monkeypatch.setattr(command_module, "collect_personal_readiness_evidence", fake_collect)

    command_module.Command().handle(
        target_date=None,
        user_id=None,
        account_id=None,
        output_dir=str(tmp_path),
        max_qlib_staleness_days=5,
        run_workspace_refresh=False,
        include_weekly_advisor=False,
        persist_risk_report=False,
        allow_unclosed_target_date=False,
        write_file=False,
        print_json=False,
    )

    assert captured["target_date"] == date(2026, 6, 30)

    help_text = (
        command_module.Command()
        .create_parser(
            "manage.py",
            "collect_personal_readiness_evidence",
        )
        .format_help()
    )
    assert "--trigger-source" not in help_text

    captured.clear()
    call_command(
        "collect_personal_readiness_evidence",
        target_date="2026-06-30",
        output_dir=str(tmp_path),
        write_file=False,
        trigger_source="scheduler",
        stdout=StringIO(),
    )

    assert captured["target_date"] == date(2026, 6, 30)
    assert captured["trigger_source"] == "scheduler"


def test_command_rejects_unclosed_target_date_by_default(monkeypatch, tmp_path):
    run_called = False

    def fake_collect(**kwargs):
        nonlocal run_called
        run_called = True
        return {"status": "ok", "target_date": kwargs["target_date"].isoformat()}

    monkeypatch.setattr(command_module, "collect_personal_readiness_evidence", fake_collect)

    with pytest.raises(CommandError, match="later than latest closed trading day"):
        command_module.Command().handle(
            target_date="2026-07-01",
            user_id=None,
            account_id=None,
            output_dir=str(tmp_path),
            max_qlib_staleness_days=5,
            run_workspace_refresh=False,
            include_weekly_advisor=False,
            persist_risk_report=False,
            allow_unclosed_target_date=False,
            write_file=False,
            print_json=False,
        )

    assert run_called is False


def test_command_allows_unclosed_target_date_for_diagnostics(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_collect(**kwargs):
        captured.update(kwargs)
        return {
            "schema_version": "test",
            "status": "ok",
            "target_date": kwargs["target_date"].isoformat(),
            "generated_at": "2026-07-01T00:00:00+00:00",
            "summary": {"target_count": 0},
            "accounts": [],
        }

    monkeypatch.setattr(command_module, "collect_personal_readiness_evidence", fake_collect)

    command_module.Command().handle(
        target_date="2026-07-01",
        user_id=None,
        account_id=None,
        output_dir=str(tmp_path),
        max_qlib_staleness_days=5,
        run_workspace_refresh=False,
        include_weekly_advisor=False,
        persist_risk_report=False,
        allow_unclosed_target_date=True,
        write_file=False,
        print_json=False,
    )

    assert captured["target_date"] == date(2026, 7, 1)
    assert captured["allow_unclosed_target_date"] is True
