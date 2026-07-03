from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from django.core.management import CommandError

from apps.task_monitor.application import readiness_status_services as status_services
from apps.task_monitor.management import auto_advisor_weekly_scheduler_status as weekly_module
from apps.task_monitor.management import quote_pre_readiness_scheduler_status as quote_module
from apps.task_monitor.management import readiness_persistence_status
from apps.task_monitor.management.commands import show_personal_readiness_status as command_module
from apps.task_monitor.management.readiness_runtime import collect_local_scheduler_runtime

ORIGINAL_COLLECT_AUTO_ADVISOR_WEEKLY_SCHEDULER = (
    command_module._collect_auto_advisor_weekly_scheduler_status
)
ORIGINAL_COLLECT_QUOTE_PRE_READINESS_SCHEDULER = (
    command_module._collect_quote_pre_readiness_scheduler_status
)


@pytest.fixture(autouse=True)
def _default_auto_advisor_weekly_scheduler(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "_collect_auto_advisor_weekly_scheduler_status",
        lambda: {
            "status": "ok",
            "name": command_module.AUTO_ADVISOR_WEEKLY_TASK_NAME,
            "task": command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
            "enabled": True,
            "schedule": {
                "minute": "30",
                "hour": "17",
                "day_of_week": "fri",
                "day_of_month": "*",
                "month_of_year": "*",
                "timezone": "Asia/Shanghai",
            },
            "run_metadata": {
                "last_run_at": "2026-07-24T17:30:00+08:00",
                "total_run_count": 4,
                "date_changed": None,
            },
            "safety": {"status": "ok", "issues": []},
        },
    )


@pytest.fixture(autouse=True)
def _default_quote_pre_readiness_scheduler(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "_collect_quote_pre_readiness_scheduler_status",
        lambda: {
            "status": "ok",
            "name": command_module.QUOTE_PRE_READINESS_TASK_NAME,
            "task": command_module.QUOTE_PRE_READINESS_TASK_PATH,
            "enabled": True,
            "schedule": {
                "minute": "20",
                "hour": "18",
                "day_of_week": "1,2,3,4,5",
                "day_of_month": "*",
                "month_of_year": "*",
                "timezone": "Asia/Shanghai",
            },
            "run_metadata": {
                "last_run_at": "2099-01-01T18:20:00+08:00",
                "total_run_count": 20,
                "date_changed": None,
            },
            "safety": {"status": "ok", "issues": []},
        },
    )


@pytest.fixture(autouse=True)
def _default_account_readiness(monkeypatch):
    monkeypatch.setattr(
        command_module.status_services,
        "build_account_readiness_summary",
        lambda: {
            "status": "ok",
            "dry_run": True,
            "target_count": 2,
            "status_counts": {"ok": 2},
            "decision_ready_account_count": 2,
            "decision_ready_account_ids": [613, 614],
            "zero_equity_account_count": 2,
            "zero_equity_account_ids": [365, 519],
            "non_blocking_placeholder_count": 2,
            "blocking_no_positive_equity_count": 0,
            "results": [
                {
                    "user_id": 182,
                    "status": "ok",
                    "decision_ready_account_ids": [613],
                    "zero_equity_account_ids": [365],
                    "zero_equity_status": "non_blocking_placeholder",
                    "created_account_id": None,
                    "message": "decision_ready_account_exists",
                },
                {
                    "user_id": 222,
                    "status": "ok",
                    "decision_ready_account_ids": [614],
                    "zero_equity_account_ids": [519],
                    "zero_equity_status": "non_blocking_placeholder",
                    "created_account_id": None,
                    "message": "decision_ready_account_exists",
                },
            ],
        },
    )


def test_personal_readiness_status_builds_operational_summary(monkeypatch, tmp_path):
    evidence_path = tmp_path / "2026-06-30-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "target_date": "2026-06-30",
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 2,
                },
                "system": {
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "usable",
                            "must_not_use_for_decision": False,
                            "blocked_reasons": [],
                            "market_thermometer": {
                                "status": "ok",
                                "observed_at": "2026-07-01",
                                "data_source": "degraded",
                                "must_not_use_for_decision": False,
                                "stale_components": [
                                    "new_investor_accounts",
                                    "etf_net_flow",
                                ],
                                "missing_components": [],
                                "valid_component_count": 4,
                                "proxy_components": [
                                    {
                                        "component_key": "new_investor_accounts",
                                        "indicator_code": "CN_A_NEW_INVESTOR_ACCOUNTS",
                                        "reporting_period": "2026-05-31",
                                        "source": "akshare",
                                        "proxy": "sse_monthly_all_account_openings",
                                        "verification_status": None,
                                        "source_url": None,
                                    }
                                ],
                                "component_data_provenance": [
                                    {
                                        "component_key": "new_investor_accounts",
                                        "indicator_code": "CN_A_NEW_INVESTOR_ACCOUNTS",
                                        "reporting_period": "2026-05-31",
                                        "source": "akshare",
                                        "proxy": "sse_monthly_all_account_openings",
                                        "verification_status": None,
                                        "source_url": None,
                                    }
                                ],
                                "components": [
                                    {
                                        "component_key": "new_investor_accounts",
                                        "label": "新增开户",
                                        "is_stale": True,
                                        "is_missing": False,
                                        "age_days": 1035,
                                        "current_value": 995900.0,
                                        "unit": "户",
                                    },
                                    {
                                        "component_key": "etf_net_flow",
                                        "label": "ETF 资金净流入",
                                        "is_stale": True,
                                        "is_missing": False,
                                        "age_days": 5,
                                        "current_value": -300496007012.004,
                                        "unit": "元",
                                    },
                                ],
                            },
                        }
                        ,
                        "regime": {
                            "status": "ok",
                            "observed_at": "2026-07-01",
                            "dominant_regime": "Recovery",
                            "confidence": 0.34,
                            "source": "akshare",
                            "is_fallback": False,
                            "records_count": 149,
                            "warnings": [],
                        },
                        "pulse": {
                            "status": "ok",
                            "observed_at": "2026-07-01",
                            "regime_context": "Recovery",
                            "composite_score": 0.107,
                            "regime_strength": "moderate",
                            "transition_warning": False,
                            "transition_direction": None,
                            "stale_indicator_count": 0,
                            "data_source": "calculated",
                        },
                    }
                },
                "workspace": {
                    "result": {
                        "components": {
                            "macro_sync": {
                                "status": "success",
                                "source": "akshare",
                                "synced_count": 4,
                                "skipped_count": 52,
                                "errors": ["no data"],
                            },
                            "regime_snapshot": {
                                "status": "success",
                                "observed_at": "2026-06-30",
                                "dominant_regime": "Recovery",
                            },
                            "pulse_snapshot": {
                                "status": "success",
                                "observed_at": "2026-06-30",
                                "is_reliable": True,
                            },
                            "action_recommendation": {
                                "status": "success",
                                "observed_at": "2026-06-30",
                                "source": "live_action_fallback",
                            },
                            "rotation_signals": {
                                "status": "success",
                                "signal_date": "2026-06-30",
                                "total_configs": 6,
                                "successful": 6,
                                "skipped": 0,
                                "failed": 0,
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "in_progress",
            "required_days": kwargs["required_days"],
            "accepted_days": 1,
            "remaining_days": 19,
            "next_required_date": "2026-07-01",
            "next_required_reason": "next_trading_day",
            "projected_completion_date": "2026-07-27",
            "projected_remaining_calendar_days": 27,
            "scheduler_clean_suffix_days": 0,
            "scheduler_clean_remaining_days": 20,
            "projected_scheduler_completion_date": "2026-07-28",
            "projected_scheduler_remaining_calendar_days": 28,
            "blocking_issues": [],
            "accepted_evidence_manifest": {
                "schema_version": "accepted-readiness-evidence-manifest.v1",
                "record_count": 1,
                "target_dates": ["2026-06-30"],
                "sha256": "manifest-hash",
            },
            "accepted_evidence_quality": {
                "record_count": 1,
                "start_date": "2026-06-30",
                "end_date": "2026-06-30",
                "acceptance_candidate_record_count": 1,
                "formal_record_count": 0,
                "legacy_record_count": 1,
                "diagnostic_record_count": 0,
                "evidence_modes": ["legacy_without_operation_context"],
            },
            "evidence_quality": {
                "record_count": 1,
                "accepted_record_count": 1,
                "rejected_record_count": 0,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "enabled": True,
            "task": command_module.TASK_PATH,
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 6, 30),
    )
    monkeypatch.setattr(
        command_module,
        "_resolve_status_date",
        lambda **kwargs: date(2026, 7, 1),
    )
    macro_context_calls: list[date] = []
    current_decision_calls: list[str] = []

    def fake_current_macro_context(*, target_date):
        macro_context_calls.append(target_date)
        return {
            "regime": {
                "status": "ok",
                "observed_at": target_date.isoformat(),
                "dominant_regime": "Recovery",
                "confidence": 0.34,
            },
            "pulse": {
                "status": "ok",
                "observed_at": target_date.isoformat(),
                "composite_score": 0.107,
                "stale_indicator_count": 0,
            },
        }

    def fake_current_decision_data_from_settings():
        current_decision_calls.append("called")
        return {
            "status": "ok",
            "readiness_status": "ok",
            "must_not_use_for_decision": False,
            "blocked_reasons": [],
            "market_thermometer": {
                "status": "ok",
                "observed_at": "2026-07-01",
                "data_source": "degraded",
                "must_not_use_for_decision": False,
                "stale_components": ["new_investor_accounts"],
                "missing_components": [],
            },
            "skipped_latest_market_thermometer": {
                "status": "skipped",
                "observed_at": "2026-07-02",
                "skip_reason": "latest_snapshot_after_decision_safe_date",
            },
        }

    monkeypatch.setattr(
        command_module.status_services,
        "build_current_macro_context",
        fake_current_macro_context,
    )
    monkeypatch.setattr(
        command_module.status_services,
        "build_current_decision_data_from_settings",
        fake_current_decision_data_from_settings,
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 6, 30),
    )

    assert payload["status"] == "in_progress"
    assert payload["expected_latest_date"] == "2026-06-30"
    assert payload["status_date"] == "2026-07-01"
    assert payload["validation"]["next_required_date"] == "2026-07-01"
    assert payload["latest_evidence"]["target_date"] == "2026-06-30"
    assert payload["latest_evidence"]["formal_evidence"] is None
    assert payload["latest_evidence"]["acceptance_candidate"] is True
    assert payload["latest_evidence"]["evidence_mode"] == "legacy_without_operation_context"
    assert payload["latest_evidence"]["summary"]["workspace_components"] == {
        "macro_sync": {
            "status": "success",
            "source": "akshare",
            "synced_count": 4,
            "skipped_count": 52,
            "error_count": 1,
        },
        "regime_snapshot": {
            "status": "success",
            "observed_at": "2026-06-30",
            "dominant_regime": "Recovery",
        },
        "pulse_snapshot": {
            "status": "success",
            "observed_at": "2026-06-30",
            "is_reliable": True,
        },
        "action_recommendation": {
            "status": "success",
            "observed_at": "2026-06-30",
            "source": "live_action_fallback",
        },
        "rotation_signals": {
            "status": "success",
            "signal_date": "2026-06-30",
            "total_configs": 6,
            "successful": 6,
            "skipped": 0,
            "failed": 0,
        }
    }
    assert payload["latest_formal_evidence"]["target_date"] == "2026-06-30"
    assert payload["acceptance_gate"]["status"] == "in_progress"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["accepted_days"] == 1
    assert payload["acceptance_gate"]["remaining_days"] == 19
    assert payload["acceptance_gate"]["latest_formal_date"] == "2026-06-30"
    assert payload["acceptance_gate"]["latest_formal_acceptance_candidate"] is True
    assert (
        payload["acceptance_gate"]["latest_formal_evidence_mode"]
        == "legacy_without_operation_context"
    )
    assert payload["acceptance_gate"]["accepted_evidence_manifest"]["sha256"] == "manifest-hash"
    assert payload["acceptance_gate"]["accepted_evidence_quality"]["legacy_record_count"] == 1
    assert payload["acceptance_gate"]["accepted_evidence_quality"]["formal_record_count"] == 0
    assert payload["acceptance_gate"]["evidence_quality"]["accepted_record_count"] == 1
    assert payload["acceptance_gate"]["next_action"] == "wait_for_post_close"
    assert payload["acceptance_gate"]["projected_completion_date"] == "2026-07-27"
    assert payload["acceptance_gate"]["projected_remaining_calendar_days"] == 27
    assert payload["acceptance_gate"]["projected_remaining_calendar_days_from_today"] == 26
    assert payload["acceptance_gate"]["scheduler_clean_suffix_days"] == 0
    assert payload["acceptance_gate"]["scheduler_clean_remaining_days"] == 20
    assert payload["acceptance_gate"]["projected_scheduler_completion_date"] == "2026-07-28"
    assert payload["acceptance_gate"]["projected_scheduler_remaining_calendar_days"] == 28
    assert (
        payload["acceptance_gate"]["projected_scheduler_remaining_calendar_days_from_today"]
        == 27
    )
    assert payload["current_macro_context"] is None
    assert payload["current_decision_data"] is None
    assert payload["account_readiness"]["status"] == "ok"
    assert payload["account_readiness"]["decision_ready_account_count"] == 2
    assert payload["account_readiness"]["zero_equity_account_count"] == 2
    assert payload["account_readiness"]["blocking_no_positive_equity_count"] == 0
    assert macro_context_calls == []
    assert current_decision_calls == []

    payload_with_current_context = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 6, 30),
        include_current_macro_context=True,
        include_current_decision_data=True,
    )

    assert macro_context_calls == [date(2026, 6, 30)]
    assert current_decision_calls == ["called"]
    assert payload_with_current_context["current_macro_context"]["regime"]["dominant_regime"] == (
        "Recovery"
    )
    assert (
        payload_with_current_context["current_macro_context"]["pulse"]["composite_score"] == 0.107
    )
    assert payload_with_current_context["current_decision_data"]["market_thermometer"][
        "observed_at"
    ] == "2026-07-01"
    assert payload_with_current_context["current_decision_data"][
        "skipped_latest_market_thermometer"
    ]["observed_at"] == "2026-07-02"
    assert payload["acceptance_gate"]["scheduler_activity"]["status"] == "pending_window"
    assert payload["acceptance_gate"]["scheduler_activity"]["ok"] is True
    assert payload["acceptance_gate"]["requirements"]["evidence_window"]["ok"] is False
    assert payload["acceptance_gate"]["requirements"]["scheduler_safety"]["ok"] is True
    assert payload["acceptance_gate"]["requirements"]["scheduler_activity"]["ok"] is True
    assert payload["acceptance_gate"]["requirements"]["auto_advisor_weekly_scheduler"]["ok"] is True
    assert payload["auto_advisor_weekly_scheduler"]["task"] == (
        command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH
    )
    assert payload["quote_pre_readiness_scheduler"]["task"] == (
        command_module.QUOTE_PRE_READINESS_TASK_PATH
    )
    assert payload["acceptance_gate"]["failed_requirements"] == [
        {
            "name": "evidence_window",
            "status": "in_progress",
            "details": {
                "accepted_days": 1,
                "required_days": 20,
                "remaining_days": 19,
            },
        }
    ]
    assert payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "evidence_window",
            "action": "wait_for_post_close",
            "reason": "target_date_not_closed",
            "target_date": "2026-07-01",
            "command": None,
            "next_check_after": None,
        }
    ]
    assert payload["acceptance_gate"]["can_generate_next_evidence"] is False
    assert payload["latest_evidence"]["summary"]["target_count"] == 2
    assert payload["latest_closed_date"] == "2026-06-30"
    assert payload["next_action"]["action"] == "wait_for_post_close"
    assert payload["next_action"]["target_date"] == "2026-07-01"
    assert payload["next_command"] is None

    (tmp_path / "2026-07-01-personal-readiness.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                    "trigger_source": "manual",
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 2,
                },
                "accounts": [
                    {
                        "user_id": 7,
                        "account_id": 613,
                        "risk_center_daily_report": {"status": "ok", "report_id": None},
                        "auto_advisor": {
                            "status": "ok",
                            "weekly_report": {"status": "ok"},
                            "weekly_report_persistence": {"status": "warning"},
                        },
                    },
                    {
                        "user_id": 7,
                        "account_id": 614,
                        "risk_center_daily_report": {"status": "ok", "report_id": None},
                        "auto_advisor": {
                            "status": "ok",
                            "weekly_report": {"status": "ok"},
                            "weekly_report_persistence": {"status": "warning"},
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    class FakeRiskReportRepository:
        def get_report(self, *, account_id, report_date):
            return SimpleNamespace(
                id=9000 + int(account_id),
                account_id=account_id,
                report_date=report_date,
                status="ok",
            )

    class FakeAutoAdvisorReportRepository:
        def list_recent_reports(self, *, user_id, account_id=None, limit=20):
            return [
                {
                    "id": 8000 + int(account_id),
                    "user_id": user_id,
                    "account_id": account_id,
                    "report_date": "2026-07-01",
                    "status": "ready",
                }
            ]

        def list_recent_notifications(self, *, user_id, account_id=None, limit=20):
            return [
                {
                    "id": 7000 + int(account_id),
                    "report_id": 8000 + int(account_id),
                    "delivery_status": "delivered",
                }
            ]

    monkeypatch.setattr(
        readiness_persistence_status,
        "get_risk_daily_report_repository",
        lambda: FakeRiskReportRepository(),
    )
    monkeypatch.setattr(
        readiness_persistence_status,
        "get_auto_advisor_report_repository",
        lambda: FakeAutoAdvisorReportRepository(),
    )
    monkeypatch.setattr(
        weekly_module,
        "EXPECTED_AUTO_ADVISOR_WEEKLY_DAY_OF_WEEK",
        "wed",
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 6, 30),
    )
    post_evidence = payload["post_evidence_persistence"]
    assert post_evidence["status"] == "ok"
    assert post_evidence["acceptance_gate_impact"] == "none"
    assert post_evidence["risk_center_daily_report"]["ok_account_count"] == 2
    assert post_evidence["auto_advisor_weekly_report"]["ok_account_count"] == 2
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["failed_requirements"] == [
        {
            "name": "evidence_window",
            "status": "in_progress",
            "details": {
                "accepted_days": 1,
                "required_days": 20,
                "remaining_days": 19,
            },
        }
    ]

    not_due_dir = tmp_path / "not-due"
    not_due_dir.mkdir()
    evidence_path = not_due_dir / "2026-07-02-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "target_date": "2026-07-02",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                    "trigger_source": "scheduler",
                },
                "accounts": [
                    {
                        "user_id": 7,
                        "account_id": 613,
                        "risk_center_daily_report": {"status": "ok"},
                        "auto_advisor": {
                            "status": "ok",
                            "weekly_report": {"status": "ok"},
                            "weekly_report_persistence": {"status": "warning"},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        weekly_module,
        "EXPECTED_AUTO_ADVISOR_WEEKLY_DAY_OF_WEEK",
        "fri",
    )
    not_due_payload = readiness_persistence_status.collect_post_evidence_persistence(
        output_dir=not_due_dir
    )

    assert not_due_payload["status"] == "ok"
    weekly = not_due_payload["auto_advisor_weekly_report"]
    assert weekly["status"] == "not_due"
    assert weekly["reason"] == "weekly_report_not_scheduled_for_target_date"
    assert weekly["scheduled_for"] is None
    assert weekly["next_scheduled_for"] == "2026-07-03T17:30:00+08:00"
    assert weekly["records"] == []


def test_personal_readiness_status_returns_run_command_when_target_is_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "in_progress",
            "required_days": kwargs["required_days"],
            "accepted_days": 1,
            "remaining_days": 19,
            "next_required_date": "2026-07-01",
            "next_required_reason": "next_trading_day",
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(command_module, "_collect_scheduler_status", lambda: {"status": "ok"})
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 1),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 1),
    )

    assert payload["next_action"]["action"] == "run_daily"
    assert payload["next_action"]["target_date"] == "2026-07-01"
    assert "--target-date 2026-07-01" in payload["next_command"]
    assert payload["acceptance_gate"]["next_action"] == "run_daily"
    assert payload["acceptance_gate"]["can_generate_next_evidence"] is True


def test_personal_readiness_status_reports_schedule_expectation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "in_progress",
            "required_days": kwargs["required_days"],
            "accepted_days": 1,
            "remaining_days": 19,
            "next_required_date": "2026-07-01",
            "next_required_reason": "next_trading_day",
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "name": command_module.TASK_NAME,
            "schedule": {
                "minute": "40",
                "hour": "18",
                "day_of_week": "mon-fri",
                "day_of_month": "*",
                "month_of_year": "*",
                "timezone": "Asia/Shanghai",
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 6, 30),
    )

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            frozen = datetime.fromisoformat("2026-07-01T18:00:00+08:00")
            if tz is not None:
                return frozen.astimezone(tz)
            return frozen.replace(tzinfo=None)

    monkeypatch.setattr(command_module, "datetime", FrozenDatetime)

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 6, 30),
    )

    assert payload["schedule_expectation"]["status"] == "scheduled"
    assert payload["schedule_expectation"]["target_date"] == "2026-07-01"
    assert payload["schedule_expectation"]["scheduled_for"] == "2026-07-01T18:40:00+08:00"
    assert payload["schedule_expectation"]["timezone"] == "Asia/Shanghai"
    assert payload["schedule_expectation"]["hour"] == 18
    assert payload["schedule_expectation"]["minute"] == 40
    assert payload["schedule_expectation"]["task_name"] == command_module.TASK_NAME
    assert payload["schedule_expectation"]["due_status"] in {
        "pending",
        "due_now",
        "grace_period",
        "overdue",
    }
    assert payload["schedule_expectation"]["grace_minutes"] == 30
    assert payload["monitor_gate"]["ok"] is True
    assert payload["monitor_gate"]["state"] == "wait_for_post_close"
    assert payload["monitor_gate"]["next_check_after"] == "2026-07-01T18:40:00+08:00"
    assert payload["acceptance_gate"]["schedule_expectation"]["scheduled_for"] == (
        "2026-07-01T18:40:00+08:00"
    )


def test_personal_readiness_schedule_expectation_reports_due_status():
    pending = command_module._build_schedule_expectation(
        validation={"next_required_date": "2026-07-01"},
        scheduler={
            "status": "ok",
            "name": command_module.TASK_NAME,
            "schedule": {
                "minute": "40",
                "hour": "18",
                "timezone": "Asia/Shanghai",
            },
        },
        next_action={"target_date": "2026-07-01"},
        now=datetime.fromisoformat("2026-07-01T18:00:00+08:00"),
    )
    grace = command_module._build_schedule_expectation(
        validation={"next_required_date": "2026-07-01"},
        scheduler={
            "status": "ok",
            "name": command_module.TASK_NAME,
            "schedule": {
                "minute": "40",
                "hour": "18",
                "timezone": "Asia/Shanghai",
            },
        },
        next_action={"target_date": "2026-07-01"},
        now=datetime.fromisoformat("2026-07-01T20:00:00+08:00"),
    )
    overdue = command_module._build_schedule_expectation(
        validation={"next_required_date": "2026-07-01"},
        scheduler={
            "status": "ok",
            "name": command_module.TASK_NAME,
            "schedule": {
                "minute": "40",
                "hour": "18",
                "timezone": "Asia/Shanghai",
            },
        },
        next_action={"target_date": "2026-07-01"},
        now=datetime.fromisoformat("2026-07-01T20:00:00+08:00"),
        schedule_overdue_grace_minutes=5,
    )

    assert pending["due_status"] == "pending"
    assert pending["seconds_until_due"] == 2400
    assert pending["seconds_overdue"] == 0
    assert pending["grace_minutes"] == 30
    assert pending["grace_deadline"] == "2026-07-01T19:10:00+08:00"
    assert grace["due_status"] == "overdue"
    assert grace["seconds_until_grace_deadline"] == 0
    assert overdue["due_status"] == "overdue"
    assert overdue["seconds_until_due"] == 0
    assert overdue["seconds_overdue"] == 4800
    assert overdue["seconds_until_grace_deadline"] == 0


def test_personal_readiness_simulates_2026_07_03_afternoon_checkpoints():
    daily_scheduler = {
        "status": "ok",
        "name": command_module.TASK_NAME,
        "schedule": {
            "minute": "10",
            "hour": "16",
            "timezone": "Asia/Shanghai",
        },
    }
    quote_scheduler = {
        "status": "ok",
        "name": command_module.QUOTE_PRE_READINESS_TASK_NAME,
        "schedule": {
            "minute": "35",
            "hour": "15",
            "timezone": "Asia/Shanghai",
        },
        "run_metadata": {
            "last_run_at": "2026-07-02T15:35:00+08:00",
            "total_run_count": 2,
        },
    }
    validation = {"next_required_date": "2026-07-03"}
    next_action = {"target_date": "2026-07-03"}

    quote_at_grace_deadline = command_module._with_quote_pre_readiness_schedule_expectation(
        scheduler=quote_scheduler,
        validation=validation,
        next_action=next_action,
        now=datetime.fromisoformat("2026-07-03T15:50:00+08:00"),
    )
    daily_before_run = command_module._build_schedule_expectation(
        validation=validation,
        scheduler=daily_scheduler,
        next_action=next_action,
        now=datetime.fromisoformat("2026-07-03T15:50:00+08:00"),
    )
    daily_after_run_grace = command_module._build_schedule_expectation(
        validation=validation,
        scheduler=daily_scheduler,
        next_action=next_action,
        now=datetime.fromisoformat("2026-07-03T16:20:00+08:00"),
    )
    weekly_before_due = weekly_module.build_auto_advisor_weekly_due_status(
        target_date=date(2026, 7, 3),
        now=datetime.fromisoformat("2026-07-03T17:20:00+08:00"),
    )
    weekly_after_due = weekly_module.build_auto_advisor_weekly_due_status(
        target_date=date(2026, 7, 3),
        now=datetime.fromisoformat("2026-07-03T17:45:00+08:00"),
    )

    assert quote_at_grace_deadline["schedule_expectation"]["due_status"] == "grace_period"
    assert quote_at_grace_deadline["status"] == "ok"
    assert daily_before_run["due_status"] == "pending"
    assert daily_before_run["scheduled_for"] == "2026-07-03T16:10:00+08:00"
    assert daily_after_run_grace["due_status"] == "grace_period"
    assert daily_after_run_grace["seconds_overdue"] == 600
    assert weekly_before_due == {
        "due": False,
        "reason": "weekly_report_schedule_not_due_yet",
        "scheduled_for": "2026-07-03T17:30:00+08:00",
    }
    assert weekly_after_due == {
        "due": True,
        "reason": "weekly_report_schedule_due",
        "scheduled_for": "2026-07-03T17:30:00+08:00",
    }


def test_auto_advisor_weekly_due_status_uses_configured_schedule_time():
    schedule = {
        "minute": "45",
        "hour": "17",
        "day_of_week": "fri",
        "day_of_month": "*",
        "month_of_year": "*",
        "timezone": "Asia/Shanghai",
    }

    weekly_before_due = weekly_module.build_auto_advisor_weekly_due_status(
        target_date=date(2026, 7, 3),
        now=datetime.fromisoformat("2026-07-03T17:40:00+08:00"),
        schedule=schedule,
    )
    weekly_after_due = weekly_module.build_auto_advisor_weekly_due_status(
        target_date=date(2026, 7, 3),
        now=datetime.fromisoformat("2026-07-03T17:50:00+08:00"),
        schedule=schedule,
    )

    assert weekly_before_due == {
        "due": False,
        "reason": "weekly_report_schedule_not_due_yet",
        "scheduled_for": "2026-07-03T17:45:00+08:00",
    }
    assert weekly_after_due == {
        "due": True,
        "reason": "weekly_report_schedule_due",
        "scheduled_for": "2026-07-03T17:45:00+08:00",
    }


def test_personal_readiness_next_action_waits_for_scheduled_run_before_grace_expires():
    pending = command_module._normalize_next_action_for_schedule(
        next_action={
            "action": "run_daily",
            "reason": "blocking_issue",
            "target_date": "2026-07-01",
            "command": (
                "python manage.py run_personal_readiness_daily " "--target-date 2026-07-01 --json"
            ),
        },
        schedule_expectation={
            "status": "scheduled",
            "due_status": "pending",
            "scheduled_for": "2026-07-01T18:40:00+08:00",
            "grace_deadline": "2026-07-01T19:10:00+08:00",
        },
    )
    grace = command_module._normalize_next_action_for_schedule(
        next_action={
            "action": "run_daily",
            "reason": "blocking_issue",
            "target_date": "2026-07-01",
            "command": "python manage.py run_personal_readiness_daily --target-date 2026-07-01 --json",
        },
        schedule_expectation={
            "status": "scheduled",
            "due_status": "grace_period",
            "scheduled_for": "2026-07-01T18:40:00+08:00",
            "grace_deadline": "2026-07-01T19:10:00+08:00",
        },
    )
    overdue = command_module._normalize_next_action_for_schedule(
        next_action={
            "action": "run_daily",
            "reason": "blocking_issue",
            "target_date": "2026-07-01",
            "command": "python manage.py run_personal_readiness_daily --target-date 2026-07-01 --json",
        },
        schedule_expectation={
            "status": "scheduled",
            "due_status": "overdue",
            "scheduled_for": "2026-07-01T18:40:00+08:00",
            "grace_deadline": "2026-07-01T19:10:00+08:00",
        },
    )

    assert pending["action"] == "wait_for_scheduled_run"
    assert pending["reason"] == "scheduled_evidence_pending"
    assert pending["command"] is None
    assert grace["action"] == "wait_for_scheduled_run"
    assert overdue["action"] == "inspect_missed_scheduled_run"
    assert overdue["reason"] == "scheduled_evidence_missing_after_grace"
    assert "show_personal_readiness_status" in overdue["command"]
    assert "run_personal_readiness_daily" not in overdue["command"]


def test_personal_readiness_strict_monitor_allows_wait_for_post_close():
    command_module._raise_for_strict_monitor(
        {
            "status": "in_progress",
            "next_action": {
                "action": "wait_for_post_close",
                "reason": "target_date_not_closed",
            },
            "schedule_expectation": {
                "due_status": "pending",
                "scheduled_for": "2026-07-01T18:40:00+08:00",
            },
        }
    )
    command_module._raise_for_strict_monitor(
        {
            "status": "in_progress",
            "next_action": {
                "action": "wait_for_scheduled_run",
                "reason": "scheduled_evidence_pending",
            },
            "schedule_expectation": {
                "due_status": "pending",
            },
        }
    )


def test_personal_readiness_strict_monitor_allows_schedule_grace_period():
    command_module._raise_for_strict_monitor(
        {
            "status": "in_progress",
            "next_action": {
                "action": "wait_for_post_close",
                "reason": "target_date_not_closed",
            },
            "schedule_expectation": {
                "due_status": "grace_period",
                "scheduled_for": "2026-07-01T18:40:00+08:00",
            },
        }
    )


def test_personal_readiness_strict_monitor_fails_when_schedule_is_overdue():
    with pytest.raises(CommandError, match="schedule is overdue"):
        command_module._raise_for_strict_monitor(
            {
                "status": "in_progress",
                "next_action": {
                    "action": "wait_for_post_close",
                    "reason": "target_date_not_closed",
                },
                "schedule_expectation": {
                    "due_status": "overdue",
                    "scheduled_for": "2026-07-01T18:40:00+08:00",
                },
            }
        )


def test_personal_readiness_monitor_gate_reports_operator_states():
    overdue = command_module._build_monitor_gate(
        status="in_progress",
        next_action={"action": "wait_for_post_close", "reason": "target_date_not_closed"},
        schedule_expectation={
            "due_status": "overdue",
            "scheduled_for": "2026-07-01T18:40:00+08:00",
            "grace_deadline": "2026-07-01T19:10:00+08:00",
            "seconds_overdue": 3600,
        },
    )
    run_daily = command_module._build_monitor_gate(
        status="blocked",
        next_action={
            "action": "run_daily",
            "reason": "blocking_issue",
            "command": "python manage.py run_personal_readiness_daily --target-date 2026-07-01",
        },
        schedule_expectation={"due_status": "grace_period"},
    )
    wait_for_scheduled_run = command_module._build_monitor_gate(
        status="blocked",
        next_action={
            "action": "wait_for_scheduled_run",
            "reason": "scheduled_evidence_pending",
        },
        schedule_expectation={
            "due_status": "pending",
            "scheduled_for": "2026-07-01T18:40:00+08:00",
            "grace_deadline": "2026-07-01T19:10:00+08:00",
        },
    )

    assert overdue["ok"] is False
    assert overdue["state"] == "schedule_overdue"
    assert overdue["reason"] == "scheduled_evidence_missing_after_grace"
    assert wait_for_scheduled_run["ok"] is True
    assert wait_for_scheduled_run["state"] == "wait_for_scheduled_run"
    assert wait_for_scheduled_run["next_check_after"] == "2026-07-01T18:40:00+08:00"
    assert run_daily["ok"] is False
    assert run_daily["state"] == "operator_action_required"
    assert run_daily["reason"] == "run_daily"
    assert "run_personal_readiness_daily" in run_daily["command"]


def test_personal_readiness_monitor_gate_blocks_post_evidence_persistence_warning():
    gate = command_module._build_monitor_gate(
        status="in_progress",
        next_action={"action": "wait_for_post_close", "reason": "target_date_not_closed"},
        schedule_expectation={"due_status": "pending"},
        post_evidence_persistence={
            "status": "warning",
            "target_date": "2026-07-03",
            "risk_center_daily_report": {"status": "ok"},
            "auto_advisor_weekly_report": {"status": "warning"},
        },
    )

    assert gate["ok"] is False
    assert gate["state"] == "post_evidence_persistence_not_ok"
    assert gate["reason"] == "post_evidence_warning"
    assert gate["next_action"] == "inspect_post_evidence_persistence"
    assert gate["target_date"] == "2026-07-03"
    assert gate["risk_status"] == "ok"
    assert gate["weekly_status"] == "warning"
    assert "--strict-monitor" in gate["command"]


def test_personal_readiness_monitor_gate_blocks_warning_wait_state():
    gate = command_module._build_monitor_gate(
        status="warning",
        next_action={"action": "wait_for_post_close", "reason": "target_date_not_closed"},
        schedule_expectation={
            "due_status": "pending",
            "scheduled_for": "2026-07-03T16:10:00+08:00",
        },
    )

    assert gate["ok"] is False
    assert gate["state"] == "operator_action_required"
    assert gate["reason"] == "wait_for_post_close"
    assert gate["next_action"] == "wait_for_post_close"
    assert gate["due_status"] == "pending"


def test_personal_readiness_monitor_gate_waits_for_due_weekly_persistence():
    gate = command_module._build_monitor_gate(
        status="in_progress",
        next_action={"action": "wait_for_post_close", "reason": "target_date_not_closed"},
        schedule_expectation={
            "due_status": "pending",
            "scheduled_for": "2026-07-06T16:10:00+08:00",
        },
        post_evidence_persistence={
            "status": "ok",
            "target_date": "2026-07-03",
            "risk_center_daily_report": {"status": "ok"},
            "auto_advisor_weekly_report": {
                "status": "not_due",
                "reason": "weekly_report_schedule_not_due_yet",
                "scheduled_for": "2026-07-03T17:30:00+08:00",
            },
        },
    )

    assert gate["ok"] is True
    assert gate["state"] == "wait_for_post_evidence_persistence"
    assert gate["next_check_after"] == "2026-07-03T17:30:00+08:00"
    assert gate["risk_status"] == "ok"
    assert gate["weekly_status"] == "not_due"


def test_personal_readiness_monitor_gate_requires_local_scheduler_runtime():
    gate = command_module._build_monitor_gate(
        status="in_progress",
        next_action={"action": "wait_for_post_close", "reason": "target_date_not_closed"},
        schedule_expectation={"due_status": "pending"},
        scheduler_runtime={
            "required": True,
            "status": "warning",
            "issues": [{"code": "local_celery_beat_not_running"}],
        },
    )

    assert gate["ok"] is False
    assert gate["state"] == "local_scheduler_runtime_unavailable"
    assert gate["reason"] == "local_celery_beat_not_running"
    assert "--require-local-scheduler-runtime" in gate["command"]


def test_personal_readiness_monitor_gate_uses_runtime_remediation_command():
    gate = command_module._build_monitor_gate(
        status="in_progress",
        next_action={"action": "wait_for_post_close", "reason": "target_date_not_closed"},
        schedule_expectation={"due_status": "pending"},
        scheduler_runtime={
            "required": True,
            "status": "warning",
            "issues": [{"code": "local_celery_required_queue_uncovered"}],
            "remediation_commands": [
                "python manage.py celery_worker_windows "
                "--queues=celery,qlib_infer --hostname=readiness@%h"
            ],
        },
    )

    assert gate["ok"] is False
    assert gate["state"] == "local_scheduler_runtime_unavailable"
    assert gate["reason"] == "local_celery_required_queue_uncovered"
    assert gate["command"] == (
        "python manage.py celery_worker_windows "
        "--queues=celery,qlib_infer --hostname=readiness@%h"
    )
    assert gate["remediation_commands"] == [
        "python manage.py celery_worker_windows "
        "--queues=celery,qlib_infer --hostname=readiness@%h"
    ]


def test_personal_readiness_local_scheduler_runtime_detects_worker_and_beat():
    runtime = collect_local_scheduler_runtime(
        required=True,
        process_commands=[
            {
                "pid": 1,
                "command_line": "python -m celery -A core worker -l info -P solo",
            },
            {
                "pid": 2,
                "command_line": "python manage.py celery_beat_windows --loglevel=info",
            },
        ],
        worker_ping=[{"readiness@local": {"ok": "pong"}}],
        worker_active_queues={
            "readiness@local": [
                {"name": "celery"},
                {"name": "qlib_infer"},
            ],
        },
        worker_registered_tasks={
            "readiness@local": [
                command_module.TASK_PATH,
                command_module.QUOTE_PRE_READINESS_TASK_PATH,
                command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
            ],
        },
    )

    assert runtime["status"] == "ok"
    assert runtime["worker_process_count"] == 1
    assert runtime["beat_process_count"] == 1
    assert runtime["responsive_worker_count"] == 1
    assert runtime["worker_ping_status"] == "ok"
    assert runtime["active_queues_status"] == "ok"
    assert runtime["missing_queues"] == []
    assert runtime["issues"] == []


def test_personal_readiness_local_scheduler_runtime_checks_registered_tasks():
    runtime = collect_local_scheduler_runtime(
        required=True,
        process_commands=[
            {
                "pid": 1,
                "command_line": "python -m celery -A core worker -l info -P solo",
            },
            {
                "pid": 2,
                "command_line": "python manage.py celery_beat_windows --loglevel=info",
            },
        ],
        worker_ping=[{"readiness@local": {"ok": "pong"}}],
        worker_active_queues={
            "readiness@local": [
                {"name": "celery"},
                {"name": "qlib_infer"},
            ],
        },
        worker_registered_tasks={
            "readiness@local": [
                command_module.TASK_PATH,
                command_module.QUOTE_PRE_READINESS_TASK_PATH,
                command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
            ],
        },
        required_registered_tasks=(
            command_module.TASK_PATH,
            command_module.QUOTE_PRE_READINESS_TASK_PATH,
            command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
        ),
    )

    assert runtime["status"] == "ok"
    assert runtime["registered_tasks_status"] == "ok"
    assert runtime["missing_registered_tasks"] == []
    assert runtime["registered_task_worker_count"] == 1


def test_personal_readiness_monitor_gate_blocks_unregistered_weekly_task():
    runtime = collect_local_scheduler_runtime(
        required=True,
        process_commands=[
            {
                "pid": 1,
                "command_line": "python -m celery -A core worker -l info -P solo",
            },
            {
                "pid": 2,
                "command_line": "python manage.py celery_beat_windows --loglevel=info",
            },
        ],
        worker_ping=[{"readiness@local": {"ok": "pong"}}],
        worker_active_queues={
            "readiness@local": [
                {"name": "celery"},
                {"name": "qlib_infer"},
            ],
        },
        worker_registered_tasks={
            "readiness@local": [
                command_module.TASK_PATH,
                command_module.QUOTE_PRE_READINESS_TASK_PATH,
            ],
        },
        required_registered_tasks=(
            command_module.TASK_PATH,
            command_module.QUOTE_PRE_READINESS_TASK_PATH,
            command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
        ),
    )

    gate = command_module._build_monitor_gate(
        status="in_progress",
        next_action={"action": "wait_for_post_close", "reason": "target_date_not_closed"},
        schedule_expectation={"due_status": "pending"},
        scheduler_runtime=runtime,
    )
    requirement = command_module._build_scheduler_runtime_requirement(
        scheduler_runtime=runtime,
    )

    assert runtime["status"] == "warning"
    assert runtime["missing_registered_tasks"] == [
        command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH
    ]
    assert gate["ok"] is False
    assert gate["state"] == "local_scheduler_runtime_unavailable"
    assert gate["reason"] == "local_celery_required_task_unregistered"
    assert requirement["ok"] is False
    assert requirement["missing_registered_tasks"] == [
        command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH
    ]


def test_personal_readiness_local_scheduler_runtime_warns_when_worker_unresponsive():
    runtime = collect_local_scheduler_runtime(
        required=True,
        process_commands=[
            {
                "pid": 1,
                "command_line": "python -m celery -A core worker -l info -P solo",
            },
            {
                "pid": 2,
                "command_line": "python manage.py celery_beat_windows --loglevel=info",
            },
        ],
        worker_ping=[],
        worker_active_queues={
            "readiness@local": [
                {"name": "celery"},
            ],
        },
        required_registered_tasks=(),
    )

    issue_codes = {item["code"] for item in runtime["issues"]}
    assert runtime["status"] == "warning"
    assert runtime["responsive_worker_count"] == 0
    assert runtime["worker_ping_status"] == "unresponsive"
    assert runtime["active_queues_status"] == "missing"
    assert runtime["missing_queues"] == ["qlib_infer"]
    assert runtime["remediation_commands"] == [
        "python manage.py celery_worker_windows "
        "--queues=celery,qlib_infer --hostname=readiness@%h"
    ]
    assert "local_celery_worker_not_responsive" in issue_codes
    assert "local_celery_required_queue_uncovered" in issue_codes


def test_personal_readiness_strict_monitor_fails_when_daily_run_is_due():
    with pytest.raises(CommandError, match="requires operator action: run_daily"):
        command_module._raise_for_strict_monitor(
            {
                "status": "blocked",
                "next_action": {
                    "action": "run_daily",
                    "reason": "blocking_issue",
                },
            }
        )


def test_personal_readiness_strict_acceptance_requires_accepted_gate():
    with pytest.raises(CommandError, match="acceptance gate is not accepted") as exc_info:
        command_module._raise_for_strict_acceptance(
            {
                "acceptance_gate": {
                    "accepted": False,
                    "accepted_days": 1,
                    "required_days": 20,
                    "remaining_days": 19,
                    "next_action": "wait_for_post_close",
                    "failed_requirements": [{"name": "evidence_window"}],
                }
            }
        )
    assert "failed_requirements=evidence_window" in str(exc_info.value)


def test_personal_readiness_strict_acceptance_passes_when_gate_is_accepted():
    command_module._raise_for_strict_acceptance(
        {
            "acceptance_gate": {
                "accepted": True,
                "accepted_days": 20,
                "required_days": 20,
                "remaining_days": 0,
            }
        }
    )


def test_strict_acceptance_handle_requires_local_scheduler_runtime(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return {
            "status": "accepted",
            "acceptance_gate": {"accepted": True, "failed_requirements": []},
        }

    monkeypatch.setattr(command_module, "build_personal_readiness_status", fake_build)
    monkeypatch.setattr(command_module, "_raise_for_strict_acceptance", lambda payload: None)

    command_module.Command().handle(
        output_dir=str(tmp_path),
        required_days=20,
        calendar_source="weekday",
        expected_latest_date="2026-07-01",
        print_json=True,
        strict_monitor=False,
        require_local_scheduler_runtime=False,
        local_runtime_ping_timeout=5.0,
        strict_acceptance=True,
        schedule_overdue_grace_minutes=30,
    )

    assert captured["require_local_scheduler_runtime"] is True


def test_personal_readiness_status_reports_latest_evidence_operation_context(tmp_path):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "latest_closed_date": "2026-07-01",
                    "allow_unclosed_target_date": False,
                    "trigger_source": "scheduler",
                    "trigger_task_id": "task-123",
                    "trigger_task_name": (
                        "apps.task_monitor.application.tasks." "run_personal_readiness_daily_task"
                    ),
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 2,
                },
                "system": {
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "usable",
                            "must_not_use_for_decision": False,
                            "blocked_reasons": [],
                            "market_thermometer": {
                                "status": "ok",
                                "observed_at": "2026-07-01",
                                "data_source": "degraded",
                                "must_not_use_for_decision": False,
                                "stale_components": [
                                    "new_investor_accounts",
                                    "etf_net_flow",
                                ],
                                "missing_components": [],
                                "valid_component_count": 4,
                                "proxy_components": [
                                    {
                                        "component_key": "new_investor_accounts",
                                        "indicator_code": "CN_A_NEW_INVESTOR_ACCOUNTS",
                                        "reporting_period": "2026-05-31",
                                        "source": "akshare",
                                        "proxy": "sse_monthly_all_account_openings",
                                        "verification_status": None,
                                        "source_url": None,
                                    }
                                ],
                                "component_data_provenance": [
                                    {
                                        "component_key": "new_investor_accounts",
                                        "indicator_code": "CN_A_NEW_INVESTOR_ACCOUNTS",
                                        "reporting_period": "2026-05-31",
                                        "source": "akshare",
                                        "proxy": "sse_monthly_all_account_openings",
                                        "verification_status": None,
                                        "source_url": None,
                                    }
                                ],
                                "components": [
                                    {
                                        "component_key": "new_investor_accounts",
                                        "label": "新增开户",
                                        "is_stale": True,
                                        "is_missing": False,
                                        "age_days": 1035,
                                        "current_value": 995900.0,
                                        "unit": "户",
                                    },
                                    {
                                        "component_key": "etf_net_flow",
                                        "label": "ETF 资金净流入",
                                        "is_stale": True,
                                        "is_missing": False,
                                        "age_days": 5,
                                        "current_value": -300496007012.004,
                                        "unit": "元",
                                    },
                                ],
                            },
                            "skipped_latest_market_thermometer": {
                                "status": "skipped",
                                "observed_at": "2026-07-02",
                                "data_source": "degraded",
                                "must_not_use_for_decision": False,
                                "blocked_reason": "",
                                "skip_reason": "latest_snapshot_after_decision_safe_date",
                            },
                        },
                        "regime": {
                            "status": "ok",
                            "observed_at": "2026-07-01",
                            "dominant_regime": "Recovery",
                            "confidence": 0.34,
                            "source": "akshare",
                            "is_fallback": False,
                            "records_count": 149,
                            "warnings": [],
                        },
                        "pulse": {
                            "status": "ok",
                            "observed_at": "2026-07-01",
                            "regime_context": "Recovery",
                            "composite_score": 0.107,
                            "regime_strength": "moderate",
                            "transition_warning": False,
                            "transition_direction": None,
                            "stale_indicator_count": 0,
                            "data_source": "calculated",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    payload = command_module._collect_latest_evidence(output_dir=tmp_path)

    assert payload["target_date"] == "2026-07-01"
    assert payload["formal_evidence"] is True
    assert payload["acceptance_candidate"] is True
    assert payload["evidence_mode"] == "formal"
    assert payload["trigger_source"] == "scheduler"
    assert payload["trigger_task_id"] == "task-123"
    assert (
        payload["trigger_task_name"]
        == "apps.task_monitor.application.tasks.run_personal_readiness_daily_task"
    )
    assert payload["operation_context"]["mode"] == "formal"
    decision_data = payload["summary"]["decision_data"]
    assert decision_data["status"] == "ok"
    assert decision_data["must_not_use_for_decision"] is False
    assert decision_data["market_thermometer"]["data_source"] == "degraded"
    assert decision_data["market_thermometer"]["stale_components"] == [
        "new_investor_accounts",
        "etf_net_flow",
    ]
    assert decision_data["market_thermometer"]["proxy_components"] == [
        {
            "component_key": "new_investor_accounts",
            "indicator_code": "CN_A_NEW_INVESTOR_ACCOUNTS",
            "reporting_period": "2026-05-31",
            "source": "akshare",
            "proxy": "sse_monthly_all_account_openings",
            "verification_status": None,
            "source_url": None,
        }
    ]
    assert decision_data["market_thermometer"]["component_data_provenance"] == [
        {
            "component_key": "new_investor_accounts",
            "indicator_code": "CN_A_NEW_INVESTOR_ACCOUNTS",
            "reporting_period": "2026-05-31",
            "source": "akshare",
            "proxy": "sse_monthly_all_account_openings",
            "verification_status": None,
            "source_url": None,
        }
    ]
    assert decision_data["market_thermometer"]["stale_component_details"] == [
        {
            "component_key": "new_investor_accounts",
            "label": "新增开户",
            "is_stale": True,
            "is_missing": False,
            "age_days": 1035,
            "current_value": 995900.0,
            "unit": "户",
        },
        {
            "component_key": "etf_net_flow",
            "label": "ETF 资金净流入",
            "is_stale": True,
            "is_missing": False,
            "age_days": 5,
            "current_value": -300496007012.004,
            "unit": "元",
        },
    ]
    assert decision_data["skipped_latest_market_thermometer"] == {
        "status": "skipped",
        "observed_at": "2026-07-02",
        "data_source": "degraded",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
        "skip_reason": "latest_snapshot_after_decision_safe_date",
    }
    macro_context = payload["summary"]["macro_context"]
    assert macro_context["regime"]["dominant_regime"] == "Recovery"
    assert macro_context["regime"]["confidence"] == 0.34
    assert macro_context["pulse"]["composite_score"] == 0.107
    assert macro_context["pulse"]["stale_indicator_count"] == 0


def test_personal_readiness_status_marks_latest_diagnostic_evidence(tmp_path):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "diagnostic_unclosed_target",
                    "target_date_closed": False,
                    "latest_closed_date": "2026-06-30",
                    "allow_unclosed_target_date": True,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 2,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = command_module._collect_latest_evidence(output_dir=tmp_path)

    assert payload["target_date"] == "2026-07-01"
    assert payload["formal_evidence"] is False
    assert payload["acceptance_candidate"] is False
    assert payload["evidence_mode"] == "diagnostic_unclosed_target"
    assert payload["operation_context"]["mode"] == "diagnostic_unclosed_target"


def test_personal_readiness_status_keeps_latest_formal_candidate_visible(tmp_path):
    formal_path = tmp_path / "2026-06-30-personal-readiness.json"
    formal_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "target_date": "2026-06-30",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "latest_closed_date": "2026-06-30",
                    "allow_unclosed_target_date": False,
                },
                "summary": {"target_count": 2},
            }
        ),
        encoding="utf-8",
    )
    diagnostic_path = tmp_path / "2026-07-01-personal-readiness.json"
    diagnostic_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "diagnostic_unclosed_target",
                    "target_date_closed": False,
                    "latest_closed_date": "2026-06-30",
                    "allow_unclosed_target_date": True,
                },
                "summary": {"target_count": 2},
            }
        ),
        encoding="utf-8",
    )

    latest = command_module._collect_latest_evidence(output_dir=tmp_path)
    formal = command_module._collect_latest_evidence(
        output_dir=tmp_path,
        formal_candidate_only=True,
    )

    assert latest["target_date"] == "2026-07-01"
    assert latest["formal_evidence"] is False
    assert formal["target_date"] == "2026-06-30"
    assert formal["formal_evidence"] is True


def test_personal_readiness_status_prioritizes_scheduler_fix(monkeypatch, tmp_path):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "in_progress",
            "required_days": kwargs["required_days"],
            "accepted_days": 1,
            "remaining_days": 19,
            "next_required_date": "2026-07-01",
            "next_required_reason": "next_trading_day",
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "warning",
            "safety": {
                "issues": [
                    {
                        "code": "scheduler_disabled",
                        "message": "disabled",
                    }
                ]
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 1),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 1),
    )

    assert payload["status"] == "warning"
    assert payload["next_action"]["action"] == "fix_scheduler"
    assert payload["next_action"]["reason"] == "scheduler_disabled"
    assert payload["next_command"] == "python manage.py setup_personal_readiness_daily"
    assert payload["acceptance_gate"]["status"] == "warning"
    assert payload["acceptance_gate"]["issue"] == "scheduler_disabled"


def test_personal_readiness_status_does_not_accept_when_scheduler_is_unsafe(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "warning",
            "safety": {
                "issues": [
                    {
                        "code": "scheduler_disabled",
                        "message": "disabled",
                    }
                ]
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["next_action"]["action"] == "fix_scheduler"
    assert payload["next_action"]["reason"] == "scheduler_disabled"


def test_personal_readiness_status_does_not_accept_without_scheduler_dispatch_history(
    monkeypatch,
    tmp_path,
):
    state = {
        "trigger_source": "scheduler",
        "trigger_task_name": command_module.TASK_PATH,
        "duplicate_task_id": False,
        "legacy_days": 0,
        "total_run_count": 3,
        "last_run_at": None,
    }

    def fake_validate(**kwargs):
        accepted_evidence = []
        for day in range(1, 21):
            if day <= state["legacy_days"]:
                accepted_evidence.append(
                    {
                        "target_date": f"2026-07-{day:02d}",
                        "evidence_mode": "legacy_without_operation_context",
                        "acceptance_candidate": True,
                        "trigger_source": None,
                        "trigger_task_id": None,
                        "trigger_task_name": None,
                    }
                )
                continue
            accepted_evidence.append(
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": state["trigger_source"],
                    "trigger_task_id": (
                        "task-duplicate" if state["duplicate_task_id"] else f"task-{day}"
                    ),
                    "trigger_task_name": state["trigger_task_name"],
                }
            )
        return {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": accepted_evidence,
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 4,
                "weekly_report_persistence_ok_account_count": 8,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "blocking_issues": [],
        }

    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        fake_validate,
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": state["last_run_at"],
                "total_run_count": state["total_run_count"],
                "date_changed": "2026-06-30T17:07:28+00:00",
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    activity = payload["acceptance_gate"]["scheduler_activity"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "insufficient_dispatch_history"
    assert payload["acceptance_gate"]["requirements"]["evidence_window"]["ok"] is True
    assert payload["acceptance_gate"]["requirements"]["scheduler_safety"]["ok"] is True
    assert payload["acceptance_gate"]["requirements"]["scheduler_activity"]["ok"] is False
    assert payload["acceptance_gate"]["failed_requirements"][0]["name"] == "scheduler_activity"
    assert payload["acceptance_gate"]["operator_actions"][0] == {
        "requirement": "scheduler_activity",
        "action": "verify_scheduler_dispatch_history",
        "reason": "insufficient_dispatch_history",
        "command": "python manage.py show_personal_readiness_status --json",
    }
    assert {item["requirement"] for item in payload["acceptance_gate"]["operator_actions"]} == {
        "scheduler_activity",
    }
    assert activity["status"] == "insufficient_dispatch_history"
    assert activity["ok"] is False
    assert activity["required_dispatches"] == 20
    assert activity["observed_dispatches"] == 3
    assert activity["scheduler_trigger_record_count"] == 20
    assert activity["scheduler_task_provenance_record_count"] == 20
    assert activity["unique_scheduler_task_id_count"] == 20
    assert activity["duplicate_scheduler_task_id_count"] == 0

    state["total_run_count"] = 20
    missing_last_run_payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    missing_last_run_activity = missing_last_run_payload["acceptance_gate"]["scheduler_activity"]
    assert missing_last_run_payload["status"] == "warning"
    assert missing_last_run_payload["acceptance_gate"]["accepted"] is False
    assert missing_last_run_payload["acceptance_gate"]["issue"] == "missing_scheduler_last_run_at"
    assert missing_last_run_activity["status"] == "missing_scheduler_last_run_at"

    state["last_run_at"] = "2026-07-19T23:50:10+08:00"
    stale_last_run_payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    stale_last_run_activity = stale_last_run_payload["acceptance_gate"]["scheduler_activity"]
    assert stale_last_run_payload["status"] == "warning"
    assert stale_last_run_payload["acceptance_gate"]["accepted"] is False
    assert stale_last_run_payload["acceptance_gate"]["issue"] == "stale_scheduler_last_run_at"
    assert stale_last_run_activity["status"] == "stale_scheduler_last_run_at"
    assert stale_last_run_activity["latest_scheduler_evidence_date"] == "2026-07-20"
    assert stale_last_run_activity["latest_scheduler_run_date"] == "2026-07-19"

    state["legacy_days"] = 1
    state["last_run_at"] = "2026-07-28T23:50:10+08:00"
    legacy_payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    legacy_activity = legacy_payload["acceptance_gate"]["scheduler_activity"]
    assert legacy_payload["status"] == "warning"
    assert legacy_payload["acceptance_gate"]["accepted"] is False
    assert legacy_payload["acceptance_gate"]["issue"] == "legacy_evidence_in_accepted_window"
    assert legacy_activity["status"] == "legacy_evidence_in_accepted_window"
    assert legacy_activity["legacy_record_count"] == 1
    assert legacy_payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "scheduler_activity",
            "action": "inspect_scheduler_evidence_provenance",
            "reason": "legacy_evidence_in_accepted_window",
            "command": "python manage.py validate_personal_readiness_window --json",
        }
    ]

    state["legacy_days"] = 0
    state["trigger_task_name"] = "apps.task_monitor.application.tasks.wrong_task"
    state["last_run_at"] = "2026-07-28T23:50:10+08:00"
    wrong_task_payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    wrong_task_activity = wrong_task_payload["acceptance_gate"]["scheduler_activity"]
    assert wrong_task_payload["status"] == "warning"
    assert wrong_task_payload["acceptance_gate"]["accepted"] is False
    assert (
        wrong_task_payload["acceptance_gate"]["issue"] == "insufficient_scheduler_task_provenance"
    )
    assert wrong_task_activity["status"] == "insufficient_scheduler_task_provenance"
    assert wrong_task_activity["scheduler_trigger_record_count"] == 20
    assert wrong_task_activity["scheduler_task_provenance_record_count"] == 0
    assert wrong_task_activity["missing_scheduler_task_provenance_record_count"] == 20
    assert wrong_task_payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "scheduler_activity",
            "action": "inspect_scheduler_evidence_provenance",
            "reason": "insufficient_scheduler_task_provenance",
            "command": "python manage.py validate_personal_readiness_window --json",
        }
    ]

    state["trigger_task_name"] = command_module.TASK_PATH
    state["duplicate_task_id"] = True
    duplicate_task_payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    duplicate_task_activity = duplicate_task_payload["acceptance_gate"]["scheduler_activity"]
    assert duplicate_task_payload["status"] == "warning"
    assert duplicate_task_payload["acceptance_gate"]["accepted"] is False
    assert duplicate_task_payload["acceptance_gate"]["issue"] == "duplicate_scheduler_task_ids"
    assert duplicate_task_activity["status"] == "duplicate_scheduler_task_ids"
    assert duplicate_task_activity["scheduler_task_provenance_record_count"] == 20
    assert duplicate_task_activity["unique_scheduler_task_id_count"] == 1
    assert duplicate_task_activity["duplicate_scheduler_task_id_count"] == 19
    assert duplicate_task_payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "scheduler_activity",
            "action": "inspect_scheduler_evidence_provenance",
            "reason": "duplicate_scheduler_task_ids",
            "command": "python manage.py validate_personal_readiness_window --json",
        }
    ]

    state["trigger_source"] = "manual"
    state["trigger_task_name"] = command_module.TASK_PATH
    state["duplicate_task_id"] = False
    state["last_run_at"] = "2026-07-28T23:50:10+08:00"

    manual_payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    manual_activity = manual_payload["acceptance_gate"]["scheduler_activity"]
    assert manual_payload["status"] == "warning"
    assert manual_payload["acceptance_gate"]["accepted"] is False
    assert manual_payload["acceptance_gate"]["issue"] == "manual_formal_evidence_in_window"
    assert manual_activity["status"] == "manual_formal_evidence_in_window"
    assert manual_activity["manual_trigger_record_count"] == 20
    assert manual_payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "scheduler_activity",
            "action": "inspect_scheduler_evidence_provenance",
            "reason": "manual_formal_evidence_in_window",
            "command": "python manage.py validate_personal_readiness_window --json",
        }
    ]


def test_personal_readiness_status_accepts_when_scheduler_dispatch_history_covers_window(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "blocking_issues": [],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 4,
                "weekly_report_persistence_ok_account_count": 8,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
                "date_changed": "2026-06-30T17:07:28+00:00",
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    activity = payload["acceptance_gate"]["scheduler_activity"]
    assert payload["status"] == "accepted"
    assert payload["acceptance_gate"]["status"] == "accepted"
    assert payload["acceptance_gate"]["accepted"] is True
    assert payload["acceptance_gate"]["issue"] is None
    assert payload["acceptance_gate"]["requirements"]["evidence_window"]["ok"] is True
    assert payload["acceptance_gate"]["requirements"]["scheduler_safety"]["ok"] is True
    assert payload["acceptance_gate"]["requirements"]["scheduler_activity"]["ok"] is True
    assert (
        payload["acceptance_gate"]["requirements"]["workspace_core_formal_evidence"]["ok"] is True
    )
    assert payload["acceptance_gate"]["requirements"]["qlib_formal_evidence"]["ok"] is True
    assert (
        payload["acceptance_gate"]["requirements"]["alpha_workspace_formal_evidence"]["ok"] is True
    )
    assert payload["acceptance_gate"]["requirements"]["decision_data_formal_evidence"]["ok"] is True
    assert (
        payload["acceptance_gate"]["requirements"]["decision_quote_freshness_formal_evidence"]["ok"]
        is True
    )
    assert payload["acceptance_gate"]["requirements"]["risk_center_formal_evidence"]["ok"] is True
    assert (
        payload["acceptance_gate"]["requirements"]["auto_advisor_weekly_persistence"]["ok"] is True
    )
    assert payload["acceptance_gate"]["requirements"]["auto_advisor_weekly_activity"]["ok"] is True
    assert payload["acceptance_gate"]["requirements"]["scheduler_runtime"]["ok"] is True
    assert (
        payload["acceptance_gate"]["requirements"]["scheduler_runtime"]["status"]
        == "not_required"
    )
    assert (
        payload["acceptance_gate"]["requirements"]["quote_pre_readiness_activity"]["ok"] is True
    )
    assert payload["acceptance_gate"]["failed_requirements"] == []
    assert payload["acceptance_gate"]["operator_actions"] == []
    assert activity["status"] == "ok"
    assert activity["ok"] is True
    assert activity["required_dispatches"] == 20
    assert activity["observed_dispatches"] == 20
    assert activity["scheduler_trigger_record_count"] == 20
    assert activity["scheduler_task_provenance_record_count"] == 20
    assert activity["unique_scheduler_task_id_count"] == 20
    assert activity["duplicate_scheduler_task_id_count"] == 0
    assert activity["missing_scheduler_task_provenance_record_count"] == 0
    assert activity["manual_trigger_record_count"] == 0
    assert activity["latest_scheduler_evidence_date"] == "2026-07-20"
    assert activity["latest_scheduler_run_date"] == "2026-07-28"


def test_personal_readiness_status_blocks_final_acceptance_when_required_runtime_is_down(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "blocking_issues": [],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 4,
                "weekly_report_persistence_ok_account_count": 8,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T18:40:10+08:00",
                "total_run_count": 20,
                "date_changed": "2026-06-30T17:07:28+00:00",
            },
            "safety": {"status": "ok", "issues": []},
        },
    )
    monkeypatch.setattr(
        command_module,
        "collect_local_scheduler_runtime",
        lambda **kwargs: {
            "required": True,
            "status": "warning",
            "worker_process_count": 0,
            "beat_process_count": 0,
            "responsive_worker_count": 0,
            "covered_queues": [],
            "missing_queues": ["celery", "qlib_infer"],
            "issues": [{"code": "local_celery_beat_not_running"}],
            "remediation_commands": ["python manage.py celery_beat_windows --loglevel=info"],
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
        require_local_scheduler_runtime=True,
    )

    requirement = payload["acceptance_gate"]["requirements"]["scheduler_runtime"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "local_celery_beat_not_running"
    assert requirement["ok"] is False
    assert requirement["status"] == "warning"
    assert requirement["required"] is True
    assert requirement["reason"] == "local_celery_beat_not_running"
    assert requirement["missing_queues"] == ["celery", "qlib_infer"]
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "scheduler_runtime"
    }
    assert payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "scheduler_runtime",
            "action": "restore_local_scheduler_runtime",
            "reason": "local_celery_beat_not_running",
            "command": "python manage.py celery_beat_windows --loglevel=info",
        }
    ]


def test_personal_readiness_status_uses_scheduled_weekly_persistence_for_final_gate(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_record_count": 20,
                "weekly_report_persistence_ok_record_count": 3,
                "weekly_report_persistence_warning_record_count": 17,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_account_count": 40,
                "weekly_report_persistence_ok_account_count": 6,
                "weekly_report_persistence_warning_account_count": 34,
                "weekly_report_persistence_missing_account_count": 0,
                "scheduled_weekly_report_record_count": 3,
                "scheduled_weekly_report_persistence_ok_record_count": 3,
                "scheduled_weekly_report_persistence_warning_record_count": 0,
                "scheduled_weekly_report_persistence_missing_record_count": 0,
                "scheduled_weekly_report_account_count": 6,
                "scheduled_weekly_report_persistence_ok_account_count": 6,
                "scheduled_weekly_report_persistence_warning_account_count": 0,
                "scheduled_weekly_report_persistence_missing_account_count": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
                "date_changed": "2026-06-30T17:07:28+00:00",
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_auto_advisor_weekly_scheduler_status",
        lambda: {
            "status": "ok",
            "enabled": True,
            "task": command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
            "schedule": {"day_of_week": "fri", "hour": "17", "minute": "30"},
            "run_metadata": {"last_run_at": "2026-07-17T17:30:10+08:00", "total_run_count": 3},
            "safety": {"status": "ok", "issues": []},
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["auto_advisor_weekly_persistence"]
    assert payload["status"] == "accepted"
    assert payload["acceptance_gate"]["accepted"] is True
    assert requirement["ok"] is True
    assert requirement["source"] == "scheduled_weekly_records"
    assert requirement["record_count"] == 3
    assert requirement["expected_record_count"] == 3
    assert requirement["warning_record_count"] == 0
    assert requirement["ok_account_count"] == 6
    assert payload["acceptance_gate"]["failed_requirements"] == []

    resolved_requirement = command_module._build_auto_advisor_weekly_persistence_requirement(
        validation={
            "status": "in_progress",
            "accepted_evidence": [{"target_date": "2026-07-03"}],
            "accepted_evidence_quality": {
                "scheduled_weekly_report_record_count": 1,
                "scheduled_weekly_report_persistence_ok_record_count": 0,
                "scheduled_weekly_report_persistence_warning_record_count": 1,
                "scheduled_weekly_report_persistence_missing_record_count": 0,
                "scheduled_weekly_report_account_count": 2,
                "scheduled_weekly_report_persistence_ok_account_count": 0,
                "scheduled_weekly_report_persistence_warning_account_count": 2,
                "scheduled_weekly_report_persistence_missing_account_count": 0,
            },
        },
        post_evidence_persistence={
            "status": "ok",
            "target_date": "2026-07-03",
            "acceptance_gate_impact": "none",
            "auto_advisor_weekly_report": {
                "status": "ok",
                "account_count": 2,
                "ok_account_count": 2,
                "missing_account_count": 0,
                "records": [
                    {
                        "user_id": 182,
                        "account_id": 613,
                        "report_id": 8,
                        "report_status": "ready",
                        "matched_notification_count": 1,
                        "delivered_notification_count": 1,
                    },
                    {
                        "user_id": 222,
                        "account_id": 614,
                        "report_id": 10,
                        "report_status": "ready",
                        "matched_notification_count": 1,
                        "delivered_notification_count": 1,
                    },
                ],
            },
        },
    )
    assert resolved_requirement["ok"] is True
    assert resolved_requirement["status"] == "resolved_after_evidence"
    assert resolved_requirement["source"] == "post_evidence_database"
    assert resolved_requirement["historical_warning_record_count"] == 1
    assert resolved_requirement["warning_record_count"] == 0
    assert resolved_requirement["ok_account_count"] == 2
    assert resolved_requirement["current_database_report_count"] == 2


def test_personal_readiness_status_blocks_final_acceptance_without_weekly_persistence(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 0,
                "weekly_report_persistence_ok_account_count": 0,
                "weekly_report_persistence_missing_record_count": 20,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["auto_advisor_weekly_persistence"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "auto_advisor_weekly_persistence"
    }
    assert payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "auto_advisor_weekly_persistence",
            "action": "verify_auto_advisor_weekly_outputs",
            "reason": "weekly_report_persistence_proof_missing",
            "command": (
                "python manage.py collect_personal_readiness_evidence "
                "--include-weekly-advisor --no-file --json"
            ),
        }
    ]


def test_personal_readiness_status_blocks_final_acceptance_with_weekly_warnings(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_record_count": 4,
                "weekly_report_persistence_ok_record_count": 3,
                "weekly_report_persistence_ok_account_count": 6,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 1,
                "weekly_report_account_count": 8,
                "weekly_report_persistence_missing_account_count": 0,
                "weekly_report_persistence_warning_account_count": 2,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["auto_advisor_weekly_persistence"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert requirement["record_count"] == 4
    assert requirement["ok_record_count"] == 3
    assert requirement["warning_record_count"] == 1
    assert requirement["account_count"] == 8
    assert requirement["ok_account_count"] == 6
    assert requirement["warning_account_count"] == 2
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "auto_advisor_weekly_persistence"
    }


def test_personal_readiness_status_blocks_final_acceptance_with_insufficient_weekly_records(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_record_count": 2,
                "weekly_report_persistence_ok_record_count": 2,
                "weekly_report_persistence_ok_account_count": 4,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
                "weekly_report_account_count": 4,
                "weekly_report_persistence_missing_account_count": 0,
                "weekly_report_persistence_warning_account_count": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["auto_advisor_weekly_persistence"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "auto_advisor_weekly_persistence_missing"
    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert requirement["record_count"] == 2
    assert requirement["expected_record_count"] == 3
    assert requirement["ok_record_count"] == 2
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "auto_advisor_weekly_persistence"
    }


def test_personal_readiness_status_blocks_final_acceptance_without_alpha_workspace_evidence(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 0,
                "formal_alpha_workspace_ok_record_count": 0,
                "formal_alpha_workspace_missing_record_count": 20,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 4,
                "weekly_report_persistence_ok_account_count": 8,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["alpha_workspace_formal_evidence"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "alpha_workspace_formal_evidence_missing"
    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert requirement["formal_record_count"] == 20
    assert requirement["alpha_workspace_record_count"] == 0
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "alpha_workspace_formal_evidence"
    }
    assert payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "alpha_workspace_formal_evidence",
            "action": "inspect_alpha_workspace_evidence",
            "reason": "formal_alpha_workspace_evidence_incomplete",
            "command": "python manage.py validate_personal_readiness_window --json",
        }
    ]


def test_personal_readiness_status_blocks_final_acceptance_without_workspace_core_evidence(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 0,
                "formal_workspace_core_ok_record_count": 0,
                "formal_workspace_core_missing_record_count": 20,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 4,
                "weekly_report_persistence_ok_account_count": 8,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["workspace_core_formal_evidence"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "workspace_core_formal_evidence_missing"
    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert requirement["formal_record_count"] == 20
    assert requirement["workspace_core_record_count"] == 0
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "workspace_core_formal_evidence"
    }
    assert payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "workspace_core_formal_evidence",
            "action": "inspect_workspace_core_evidence",
            "reason": "formal_workspace_core_evidence_incomplete",
            "command": "python manage.py validate_personal_readiness_window --json",
        }
    ]


def test_personal_readiness_status_blocks_final_acceptance_without_qlib_evidence(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 0,
                "formal_qlib_ok_record_count": 0,
                "formal_qlib_missing_record_count": 20,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 4,
                "weekly_report_persistence_ok_account_count": 8,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["qlib_formal_evidence"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "qlib_formal_evidence_missing"
    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert requirement["formal_record_count"] == 20
    assert requirement["qlib_record_count"] == 0
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "qlib_formal_evidence"
    }
    assert payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "qlib_formal_evidence",
            "action": "inspect_qlib_evidence",
            "reason": "formal_qlib_evidence_incomplete",
            "command": "python manage.py validate_personal_readiness_window --json",
        }
    ]


def test_personal_readiness_status_blocks_final_acceptance_without_decision_data_evidence(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 0,
                "formal_decision_data_ok_record_count": 0,
                "formal_decision_data_missing_record_count": 20,
                "formal_decision_data_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 4,
                "weekly_report_persistence_ok_account_count": 8,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["decision_data_formal_evidence"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "decision_data_formal_evidence_missing"
    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert requirement["formal_record_count"] == 20
    assert requirement["decision_data_record_count"] == 0
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "decision_data_formal_evidence"
    }
    assert payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "decision_data_formal_evidence",
            "action": "inspect_decision_data_evidence",
            "reason": "formal_decision_data_evidence_incomplete",
            "command": "python manage.py validate_personal_readiness_window --json",
        }
    ]


def test_personal_readiness_status_blocks_final_acceptance_without_full_risk_record_coverage(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 19,
                "formal_risk_ok_record_count": 19,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 4,
                "weekly_report_persistence_ok_account_count": 8,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["risk_center_formal_evidence"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "risk_center_formal_evidence_missing"
    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert requirement["formal_record_count"] == 20
    assert requirement["risk_record_count"] == 19
    assert requirement["ok_record_count"] == 19
    assert requirement["account_count"] == 40
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "risk_center_formal_evidence"
    }
    assert payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "risk_center_formal_evidence",
            "action": "inspect_risk_center_evidence",
            "reason": "formal_risk_center_evidence_incomplete",
            "command": "python manage.py validate_personal_readiness_window --json",
        }
    ]


def test_risk_center_formal_evidence_requires_persisted_reports():
    requirement = status_services.build_risk_center_formal_evidence_requirement(
        validation={
            "status": "accepted",
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_risk_persisted_report_account_count": 39,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
            },
        }
    )

    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert requirement["account_count"] == 40
    assert requirement["persisted_report_account_count"] == 39


def test_operator_actions_advise_pending_risk_report_persistence():
    actions = command_module._build_acceptance_operator_actions(
        failed_requirements=[
            {
                "name": "evidence_window",
                "status": "in_progress",
                "details": {
                    "accepted_days": 2,
                    "required_days": 20,
                    "remaining_days": 18,
                },
            }
        ],
        requirements={
            "risk_center_formal_evidence": {
                "ok": True,
                "status": "pending_window",
                "account_count": 2,
                "risk_ok_account_count": 2,
                "persisted_report_account_count": 0,
            }
        },
        next_action={
            "action": "wait_for_post_close",
            "reason": "target_date_not_closed",
            "target_date": "2026-07-02",
            "command": None,
        },
        schedule_expectation={},
        scheduler_activity={"status": "pending_window"},
    )

    assert actions == [
        {
            "requirement": "evidence_window",
            "action": "wait_for_post_close",
            "reason": "target_date_not_closed",
            "target_date": "2026-07-02",
            "command": None,
            "next_check_after": None,
        },
        {
            "requirement": "risk_center_formal_evidence",
            "action": "verify_scheduled_risk_report_persistence",
            "reason": "formal_risk_reports_not_persisted_yet",
            "account_count": 2,
            "persisted_report_account_count": 0,
            "advisory": True,
            "command": "python manage.py show_personal_readiness_status --json --strict-monitor",
        },
    ]

    clarified_actions = command_module._build_acceptance_operator_actions(
        failed_requirements=[
            {
                "name": "evidence_window",
                "status": "in_progress",
                "details": {
                    "accepted_days": 2,
                    "required_days": 20,
                    "remaining_days": 18,
                },
            }
        ],
        requirements={
            "risk_center_formal_evidence": {
                "ok": True,
                "status": "pending_window",
                "account_count": 2,
                "risk_ok_account_count": 2,
                "persisted_report_account_count": 0,
            }
        },
        next_action={
            "action": "wait_for_post_close",
            "reason": "target_date_not_closed",
            "target_date": "2026-07-02",
            "command": None,
        },
        schedule_expectation={},
        scheduler_activity={"status": "pending_window"},
        post_evidence_persistence={
            "status": "ok",
            "acceptance_gate_impact": "none",
            "risk_center_daily_report": {
                "status": "ok",
                "ok_account_count": 2,
                "records": [
                    {
                        "account_id": 613,
                        "report_id": 1,
                        "report_date": "2026-07-01",
                    },
                    {
                        "account_id": 614,
                        "report_id": 2,
                        "report_date": "2026-07-01",
                    },
                ],
            },
        },
    )

    assert clarified_actions[1] == {
        "requirement": "risk_center_formal_evidence",
        "action": "wait_for_scheduled_risk_report_evidence",
        "reason": "post_evidence_risk_reports_persisted_waiting_for_scheduler_evidence",
        "account_count": 2,
        "persisted_report_account_count": 0,
        "advisory": True,
        "command": "python manage.py show_personal_readiness_status --json --strict-monitor",
        "current_database_status": "ok",
        "current_database_ok_account_count": 2,
        "current_database_report_count": 2,
        "current_database_reports": [
            {
                "account_id": 613,
                "report_id": 1,
                "report_date": "2026-07-01",
            },
            {
                "account_id": 614,
                "report_id": 2,
                "report_date": "2026-07-01",
            },
        ],
        "acceptance_gate_impact": "none",
    }


def test_personal_readiness_status_blocks_final_acceptance_without_weekly_scheduler_activity(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 4,
                "weekly_report_persistence_ok_account_count": 8,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_auto_advisor_weekly_scheduler_status",
        lambda: {
            "status": "ok",
            "enabled": True,
            "task": command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
            "schedule": {"day_of_week": "fri", "hour": "17", "minute": "30"},
            "run_metadata": {"last_run_at": None, "total_run_count": 0},
            "safety": {"status": "ok", "issues": []},
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["auto_advisor_weekly_activity"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "auto_advisor_weekly_activity_missing"
    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "auto_advisor_weekly_activity"
    }
    assert payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "auto_advisor_weekly_activity",
            "action": "verify_auto_advisor_weekly_scheduler_run",
            "reason": "weekly_scheduler_run_history_missing",
            "command": "python manage.py show_personal_readiness_status --json",
        }
    ]


def test_personal_readiness_status_blocks_final_acceptance_with_stale_weekly_activity(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 4,
                "weekly_report_persistence_ok_account_count": 8,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_auto_advisor_weekly_scheduler_status",
        lambda: {
            "status": "ok",
            "enabled": True,
            "task": command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
            "schedule": {"day_of_week": "fri", "hour": "17", "minute": "30"},
            "run_metadata": {"last_run_at": "2026-06-26T17:30:10+08:00", "total_run_count": 4},
            "safety": {"status": "ok", "issues": []},
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["auto_advisor_weekly_activity"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "auto_advisor_weekly_activity_missing"
    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert requirement["latest_run_date"] == "2026-06-26"
    assert requirement["window_start_date"] == "2026-07-01"
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "auto_advisor_weekly_activity"
    }


def test_personal_readiness_status_blocks_final_acceptance_with_insufficient_weekly_activity(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 3,
                "weekly_report_persistence_ok_account_count": 6,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_auto_advisor_weekly_scheduler_status",
        lambda: {
            "status": "ok",
            "enabled": True,
            "task": command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
            "schedule": {"day_of_week": "fri", "hour": "17", "minute": "30"},
            "run_metadata": {"last_run_at": "2026-07-17T17:30:10+08:00", "total_run_count": 2},
            "safety": {"status": "ok", "issues": []},
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["auto_advisor_weekly_activity"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "auto_advisor_weekly_activity_missing"
    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert requirement["total_run_count"] == 2
    assert requirement["expected_run_count"] == 3
    assert requirement["latest_run_date"] == "2026-07-17"
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "auto_advisor_weekly_activity"
    }


def test_personal_readiness_status_blocks_final_acceptance_with_stale_latest_weekly_run(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "accepted_evidence": [
                {
                    "target_date": f"2026-07-{day:02d}",
                    "evidence_mode": "formal",
                    "acceptance_candidate": True,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_record_count": 3,
                "weekly_report_persistence_ok_record_count": 3,
                "weekly_report_persistence_ok_account_count": 6,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "blocking_issues": [],
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-07-28T23:50:10+08:00",
                "total_run_count": 20,
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_auto_advisor_weekly_scheduler_status",
        lambda: {
            "status": "ok",
            "enabled": True,
            "task": command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
            "schedule": {"day_of_week": "fri", "hour": "17", "minute": "30"},
            "run_metadata": {"last_run_at": "2026-07-10T17:30:10+08:00", "total_run_count": 3},
            "safety": {"status": "ok", "issues": []},
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 28),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 28),
    )

    requirement = payload["acceptance_gate"]["requirements"]["auto_advisor_weekly_activity"]
    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "auto_advisor_weekly_activity_missing"
    assert requirement["ok"] is False
    assert requirement["status"] == "missing"
    assert requirement["total_run_count"] == 3
    assert requirement["expected_run_count"] == 3
    assert requirement["latest_run_date"] == "2026-07-10"
    assert requirement["latest_expected_run_date"] == "2026-07-17"
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "auto_advisor_weekly_activity"
    }


def test_personal_readiness_status_runs_daily_when_closed_target_evidence_is_missing(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "in_progress",
            "required_days": kwargs["required_days"],
            "accepted_days": 0,
            "remaining_days": 20,
            "next_required_date": "2026-07-01",
            "next_required_reason": "blocking_issue",
            "blocking_issues": [
                {
                    "target_date": "2026-07-01",
                    "reason": "evidence is missing",
                    "path": "",
                }
            ],
        },
    )
    monkeypatch.setattr(command_module, "_collect_scheduler_status", lambda: {"status": "ok"})
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 1),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 1),
    )

    assert payload["status"] == "blocked"
    assert payload["next_action"]["action"] == "run_daily"
    assert payload["next_action"]["reason"] == "blocking_issue"
    assert "--target-date 2026-07-01" in payload["next_command"]


def test_personal_readiness_status_marks_failed_evidence_as_inspect_action(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "in_progress",
            "required_days": kwargs["required_days"],
            "accepted_days": 0,
            "remaining_days": 20,
            "next_required_date": "2026-07-01",
            "next_required_reason": "blocking_issue",
            "blocking_issues": [
                {
                    "target_date": "2026-07-01",
                    "reason": "qlib_status is warning",
                    "path": "2026-07-01-personal-readiness.json",
                }
            ],
        },
    )
    monkeypatch.setattr(command_module, "_collect_scheduler_status", lambda: {"status": "ok"})
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 7, 1),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 1),
    )

    assert payload["status"] == "blocked"
    assert payload["next_action"]["action"] == "inspect_blocking_issue"
    assert payload["next_action"]["reason"] == "blocking_issue"
    assert "inspect_personal_readiness_evidence" in payload["next_command"]
    assert "--target-date 2026-07-01" in payload["next_command"]


def test_personal_readiness_status_reports_scheduler_configuration(monkeypatch):
    fake_task = SimpleNamespace(
        name=command_module.TASK_NAME,
        task=command_module.TASK_PATH,
        enabled=True,
        last_run_at=datetime.fromisoformat("2026-07-01T23:50:10+08:00"),
        total_run_count=3,
        date_changed=datetime.fromisoformat("2026-07-01T01:00:00+08:00"),
        kwargs='{"calendar_source": "auto"}',
        crontab=SimpleNamespace(
            minute="50",
            hour="23",
            day_of_week="mon-fri",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(command_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_scheduler_status()

    assert payload["status"] == "ok"
    assert payload["enabled"] is True
    assert payload["task"] == command_module.TASK_PATH
    assert payload["schedule"]["hour"] == "23"
    assert payload["schedule"]["minute"] == "50"
    assert payload["schedule"]["day_of_month"] == "*"
    assert payload["schedule"]["month_of_year"] == "*"
    assert payload["effective_args"] == []
    assert payload["effective_kwargs"]["allow_unclosed_target_date"] is False
    assert payload["effective_kwargs"]["repair_accounts"] is False
    assert payload["effective_kwargs"]["trigger_source"] == "scheduler"
    assert payload["effective_kwargs"]["persist_risk_report"] is True
    assert payload["run_controls"]["one_off"] is False
    assert payload["run_controls"]["expires"] is None
    assert payload["run_controls"]["expire_seconds"] is None
    assert payload["delivery_controls"]["queue"] is None
    assert payload["delivery_controls"]["exchange"] is None
    assert payload["delivery_controls"]["routing_key"] is None
    assert payload["delivery_controls"]["priority"] is None
    assert payload["delivery_controls"]["effective_headers"] == {}
    assert payload["run_metadata"] == {
        "last_run_at": "2026-07-01T23:50:10+08:00",
        "total_run_count": 3,
        "date_changed": "2026-07-01T01:00:00+08:00",
    }
    assert payload["safety"]["status"] == "ok"
    assert payload["safety"]["trigger_source"] == "scheduler"


def test_personal_readiness_status_warns_on_unsafe_scheduler_kwargs(monkeypatch):
    fake_task = SimpleNamespace(
        name=command_module.TASK_NAME,
        task=command_module.TASK_PATH,
        enabled=True,
        kwargs=(
            '{"allow_unclosed_target_date": true, "repair_accounts": true, '
            '"trigger_source": "manual", "target_date": "2026-07-01", '
            '"calendar_source": "weekday", "run_workspace_refresh": false, '
            '"include_weekly_advisor": false, "persist_risk_report": false, '
            '"max_qlib_staleness_days": 30}'
        ),
        crontab=SimpleNamespace(
            minute="50",
            hour="23",
            day_of_week="mon-fri",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(command_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_scheduler_status()

    issue_codes = {issue["code"] for issue in payload["safety"]["issues"]}
    assert payload["status"] == "warning"
    assert payload["effective_kwargs"]["allow_unclosed_target_date"] is True
    assert payload["effective_kwargs"]["repair_accounts"] is True
    assert payload["effective_kwargs"]["trigger_source"] == "manual"
    assert payload["effective_kwargs"]["target_date"] == "2026-07-01"
    assert payload["effective_kwargs"]["calendar_source"] == "weekday"
    assert payload["safety"]["calendar_source"] == "weekday"
    assert payload["safety"]["run_workspace_refresh"] is False
    assert payload["safety"]["include_weekly_advisor"] is False
    assert payload["safety"]["persist_risk_report"] is False
    assert payload["safety"]["max_qlib_staleness_days"] == 30
    assert "unclosed_target_date_override_enabled" in issue_codes
    assert "scheduled_account_repair_enabled" in issue_codes
    assert "scheduled_trigger_source_not_scheduler" in issue_codes
    assert "fixed_scheduler_target_date" in issue_codes
    assert "unexpected_scheduler_calendar_source" in issue_codes
    assert "scheduled_workspace_refresh_disabled" in issue_codes
    assert "scheduled_weekly_advisor_disabled" in issue_codes
    assert "scheduled_risk_report_persistence_disabled" in issue_codes
    assert "unsafe_scheduler_qlib_staleness_days" in issue_codes


def test_personal_readiness_status_collects_auto_advisor_weekly_scheduler(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "_collect_auto_advisor_weekly_scheduler_status",
        ORIGINAL_COLLECT_AUTO_ADVISOR_WEEKLY_SCHEDULER,
    )
    fake_task = SimpleNamespace(
        name=command_module.AUTO_ADVISOR_WEEKLY_TASK_NAME,
        task=command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
        enabled=True,
        args="[]",
        kwargs="{}",
        headers="{}",
        queue=None,
        exchange=None,
        routing_key=None,
        priority=None,
        one_off=False,
        start_time=None,
        expires=None,
        expire_seconds=None,
        last_run_at=datetime.fromisoformat("2026-06-26T17:30:10+08:00"),
        total_run_count=2,
        date_changed=datetime.fromisoformat("2026-07-01T01:00:00+08:00"),
        crontab=SimpleNamespace(
            minute="30",
            hour="17",
            day_of_week="fri",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.AUTO_ADVISOR_WEEKLY_TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(weekly_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_auto_advisor_weekly_scheduler_status()

    assert payload["status"] == "ok"
    assert payload["enabled"] is True
    assert payload["task"] == command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH
    assert payload["schedule"]["day_of_week"] == "fri"
    assert payload["schedule"]["hour"] == "17"
    assert payload["schedule"]["minute"] == "30"
    assert payload["safety"]["scope"]["all_active_accounts"] is True
    assert payload["safety"]["issues"] == []


def test_auto_advisor_weekly_scheduler_accepts_configured_post_close_time(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "_collect_auto_advisor_weekly_scheduler_status",
        ORIGINAL_COLLECT_AUTO_ADVISOR_WEEKLY_SCHEDULER,
    )
    fake_task = SimpleNamespace(
        name=command_module.AUTO_ADVISOR_WEEKLY_TASK_NAME,
        task=command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
        enabled=True,
        args="[]",
        kwargs="{}",
        headers="{}",
        queue=None,
        exchange=None,
        routing_key=None,
        priority=None,
        one_off=False,
        start_time=None,
        expires=None,
        expire_seconds=None,
        last_run_at=datetime.fromisoformat("2026-06-26T17:45:10+08:00"),
        total_run_count=2,
        date_changed=datetime.fromisoformat("2026-07-01T01:00:00+08:00"),
        crontab=SimpleNamespace(
            minute="45",
            hour="17",
            day_of_week="fri",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.AUTO_ADVISOR_WEEKLY_TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(weekly_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_auto_advisor_weekly_scheduler_status()

    assert payload["status"] == "ok"
    assert payload["schedule"]["hour"] == "17"
    assert payload["schedule"]["minute"] == "45"
    assert payload["safety"]["issues"] == []


def test_auto_advisor_weekly_scheduler_rejects_unsafe_pre_evidence_time():
    issue = weekly_module._build_auto_advisor_weekly_schedule_safety_issue(
        schedule={
            "minute": "0",
            "hour": "16",
            "day_of_week": "fri",
            "day_of_month": "*",
            "month_of_year": "*",
            "timezone": "Asia/Shanghai",
        }
    )

    assert issue == {
        "code": "unsafe_auto_advisor_weekly_time",
        "message": (
            "Scheduled weekly auto-advisor report should run after 16:00 "
            "Asia/Shanghai, got 16:00."
        ),
    }


def test_auto_advisor_weekly_scheduler_rejects_time_not_after_daily_evidence():
    issue = weekly_module._build_auto_advisor_weekly_schedule_safety_issue(
        schedule={
            "minute": "10",
            "hour": "16",
            "day_of_week": "fri",
            "day_of_month": "*",
            "month_of_year": "*",
            "timezone": "Asia/Shanghai",
        }
    )

    assert issue == {
        "code": "auto_advisor_weekly_not_after_daily_evidence",
        "message": (
            "Scheduled weekly auto-advisor report should run after "
            "personal readiness daily evidence (16:10), got 16:10."
        ),
    }


def test_personal_readiness_status_collects_quote_pre_readiness_scheduler(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "_collect_quote_pre_readiness_scheduler_status",
        ORIGINAL_COLLECT_QUOTE_PRE_READINESS_SCHEDULER,
    )
    fake_task = SimpleNamespace(
        name=command_module.QUOTE_PRE_READINESS_TASK_NAME,
        task=command_module.QUOTE_PRE_READINESS_TASK_PATH,
        enabled=True,
        args="[]",
        kwargs='{"quote_max_age_hours": 4.0, "asset_codes": ["510300.SH", "000300.SH"]}',
        headers="{}",
        queue=None,
        exchange=None,
        routing_key=None,
        priority=None,
        one_off=False,
        start_time=None,
        expires=None,
        expire_seconds=None,
        last_run_at=datetime.fromisoformat("2026-07-02T18:20:10+08:00"),
        total_run_count=1,
        date_changed=datetime.fromisoformat("2026-07-01T15:00:00+08:00"),
        crontab=SimpleNamespace(
            minute="20",
            hour="18",
            day_of_week="1,2,3,4,5",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.QUOTE_PRE_READINESS_TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(quote_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_quote_pre_readiness_scheduler_status()

    assert payload["status"] == "ok"
    assert payload["enabled"] is True
    assert payload["task"] == command_module.QUOTE_PRE_READINESS_TASK_PATH
    assert payload["schedule"]["day_of_week"] == "1,2,3,4,5"
    assert payload["schedule"]["hour"] == "18"
    assert payload["schedule"]["minute"] == "20"
    assert payload["safety"]["quote_max_age_hours"] == 4.0
    assert payload["safety"]["asset_codes"] == ["510300.SH", "000300.SH"]
    assert payload["safety"]["issues"] == []


def test_quote_pre_readiness_scheduler_allows_custom_post_close_time(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "_collect_quote_pre_readiness_scheduler_status",
        ORIGINAL_COLLECT_QUOTE_PRE_READINESS_SCHEDULER,
    )
    fake_task = SimpleNamespace(
        name=command_module.QUOTE_PRE_READINESS_TASK_NAME,
        task=command_module.QUOTE_PRE_READINESS_TASK_PATH,
        enabled=True,
        args="[]",
        kwargs='{"quote_max_age_hours": 4.0}',
        headers="{}",
        queue=None,
        exchange=None,
        routing_key=None,
        priority=None,
        one_off=False,
        start_time=None,
        expires=None,
        expire_seconds=None,
        last_run_at=None,
        total_run_count=0,
        date_changed=None,
        crontab=SimpleNamespace(
            minute="35",
            hour="15",
            day_of_week="1,2,3,4,5",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.QUOTE_PRE_READINESS_TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(quote_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_quote_pre_readiness_scheduler_status()

    assert payload["status"] == "ok"
    assert payload["schedule"]["hour"] == "15"
    assert payload["schedule"]["minute"] == "35"
    assert payload["safety"]["issues"] == []


def test_quote_pre_readiness_scheduler_warns_before_post_close(monkeypatch):
    monkeypatch.setattr(
        command_module,
        "_collect_quote_pre_readiness_scheduler_status",
        ORIGINAL_COLLECT_QUOTE_PRE_READINESS_SCHEDULER,
    )
    fake_task = SimpleNamespace(
        name=command_module.QUOTE_PRE_READINESS_TASK_NAME,
        task=command_module.QUOTE_PRE_READINESS_TASK_PATH,
        enabled=True,
        args="[]",
        kwargs='{"quote_max_age_hours": 4.0}',
        headers="{}",
        queue=None,
        exchange=None,
        routing_key=None,
        priority=None,
        one_off=False,
        start_time=None,
        expires=None,
        expire_seconds=None,
        last_run_at=None,
        total_run_count=0,
        date_changed=None,
        crontab=SimpleNamespace(
            minute="59",
            hour="14",
            day_of_week="1,2,3,4,5",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.QUOTE_PRE_READINESS_TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(quote_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_quote_pre_readiness_scheduler_status()

    assert payload["status"] == "warning"
    assert payload["safety"]["issues"][-1]["code"] == (
        "quote_pre_readiness_before_post_close"
    )


def test_personal_readiness_status_warns_when_quote_pre_readiness_scheduler_is_unsafe():
    status = command_module._rollup_status(
        validation={"status": "in_progress"},
        scheduler={"status": "ok"},
        auto_advisor_weekly_scheduler={"status": "ok"},
        quote_pre_readiness_scheduler={
            "status": "warning",
            "safety": {
                "issues": [{"code": "quote_pre_readiness_scheduler_disabled"}],
            },
        },
    )

    assert status == "warning"


def test_quote_pre_readiness_schedule_expectation_uses_next_required_date():
    scheduler = {
        "status": "ok",
        "name": command_module.QUOTE_PRE_READINESS_TASK_NAME,
        "schedule": {
            "minute": "20",
            "hour": "18",
            "day_of_week": "1,2,3,4,5",
            "day_of_month": "*",
            "month_of_year": "*",
            "timezone": "Asia/Shanghai",
        },
        "run_metadata": {"last_run_at": None, "total_run_count": 0},
        "safety": {"status": "ok", "issues": []},
    }

    payload = command_module._with_quote_pre_readiness_schedule_expectation(
        scheduler=scheduler,
        validation={"next_required_date": "2026-07-02"},
        next_action={"target_date": "2026-07-02"},
        now=datetime.fromisoformat("2026-07-01T23:25:00+08:00"),
    )

    expectation = payload["schedule_expectation"]
    assert payload["status"] == "ok"
    assert expectation["target_date"] == "2026-07-02"
    assert expectation["scheduled_for"] == "2026-07-02T18:20:00+08:00"
    assert expectation["due_status"] == "pending"


def test_quote_pre_readiness_schedule_expectation_warns_after_missing_grace():
    scheduler = {
        "status": "ok",
        "name": command_module.QUOTE_PRE_READINESS_TASK_NAME,
        "schedule": {
            "minute": "20",
            "hour": "18",
            "day_of_week": "1,2,3,4,5",
            "day_of_month": "*",
            "month_of_year": "*",
            "timezone": "Asia/Shanghai",
        },
        "run_metadata": {"last_run_at": "2026-07-01T18:20:00+08:00", "total_run_count": 1},
        "safety": {"status": "ok", "issues": []},
    }

    payload = command_module._with_quote_pre_readiness_schedule_expectation(
        scheduler=scheduler,
        validation={"next_required_date": "2026-07-02"},
        next_action={"target_date": "2026-07-02"},
        now=datetime.fromisoformat("2026-07-02T18:36:00+08:00"),
    )

    expectation = payload["schedule_expectation"]
    assert payload["status"] == "warning"
    assert expectation["due_status"] == "overdue"
    assert payload["safety"]["issues"][-1]["code"] == (
        "quote_pre_readiness_run_missing_after_grace"
    )


def test_quote_pre_readiness_schedule_expectation_marks_completed_run():
    scheduler = {
        "status": "ok",
        "name": command_module.QUOTE_PRE_READINESS_TASK_NAME,
        "schedule": {
            "minute": "20",
            "hour": "18",
            "day_of_week": "1,2,3,4,5",
            "day_of_month": "*",
            "month_of_year": "*",
            "timezone": "Asia/Shanghai",
        },
        "run_metadata": {"last_run_at": "2026-07-02T18:21:00+08:00", "total_run_count": 2},
        "safety": {"status": "ok", "issues": []},
    }

    payload = command_module._with_quote_pre_readiness_schedule_expectation(
        scheduler=scheduler,
        validation={"next_required_date": "2026-07-02"},
        next_action={"target_date": "2026-07-02"},
        now=datetime.fromisoformat("2026-07-02T18:36:00+08:00"),
    )

    expectation = payload["schedule_expectation"]
    assert payload["status"] == "ok"
    assert expectation["due_status"] == "completed"
    assert expectation["completed_at"] == "2026-07-02T18:21:00+08:00"


def test_quote_pre_readiness_activity_requirement_blocks_insufficient_dispatch_history():
    requirement = command_module._build_quote_pre_readiness_activity_requirement(
        validation={
            "status": "accepted",
            "required_days": 20,
            "accepted_evidence_quality": {
                "start_date": "2026-07-01",
                "end_date": "2026-07-28",
            },
        },
        quote_pre_readiness_scheduler={
            "run_metadata": {
                "last_run_at": "2026-07-28T18:20:00+08:00",
                "total_run_count": 19,
            }
        },
    )

    assert requirement["ok"] is False
    assert requirement["status"] == "insufficient_quote_pre_readiness_dispatch_history"
    assert requirement["required_dispatches"] == 20
    assert requirement["observed_dispatches"] == 19
    assert requirement["latest_run_date"] == "2026-07-28"


def test_quote_pre_readiness_activity_requirement_prefers_evidence_level_proof():
    requirement = command_module._build_quote_pre_readiness_activity_requirement(
        validation={
            "status": "accepted",
            "required_days": 20,
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_quote_pre_readiness_scheduler_ok_record_count": 20,
                "formal_quote_pre_readiness_scheduler_missing_record_count": 0,
                "formal_quote_pre_readiness_scheduler_blocked_record_count": 0,
                "start_date": "2026-07-01",
                "end_date": "2026-07-28",
            },
        },
        quote_pre_readiness_scheduler={
            "run_metadata": {
                "last_run_at": None,
                "total_run_count": 0,
            }
        },
    )

    assert requirement["ok"] is True
    assert requirement["status"] == "ok"
    assert requirement["evidence_quality_available"] is True
    assert requirement["formal_quote_pre_readiness_scheduler_ok_record_count"] == 20


def test_quote_pre_readiness_activity_requirement_blocks_missing_evidence_level_proof():
    requirement = command_module._build_quote_pre_readiness_activity_requirement(
        validation={
            "status": "accepted",
            "required_days": 20,
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_quote_pre_readiness_scheduler_ok_record_count": 19,
                "formal_quote_pre_readiness_scheduler_missing_record_count": 1,
                "formal_quote_pre_readiness_scheduler_blocked_record_count": 0,
                "start_date": "2026-07-01",
                "end_date": "2026-07-28",
            },
        },
        quote_pre_readiness_scheduler={
            "run_metadata": {
                "last_run_at": "2026-07-28T18:20:00+08:00",
                "total_run_count": 20,
            }
        },
    )

    assert requirement["ok"] is False
    assert requirement["status"] == "missing_quote_pre_readiness_evidence"
    assert requirement["formal_quote_pre_readiness_scheduler_missing_record_count"] == 1


def test_personal_readiness_status_blocks_acceptance_when_weekly_scheduler_is_unsafe(
    monkeypatch,
    tmp_path,
):
    evidence_path = tmp_path / "2026-06-30-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "target_date": "2026-06-30",
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 2,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "projected_completion_date": "2026-07-27",
            "projected_remaining_calendar_days": 0,
            "blocking_issues": [],
            "accepted_evidence": [
                {
                    "target_date": f"2026-06-{day:02d}",
                    "evidence_mode": "formal",
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_manifest": {},
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 4,
                "weekly_report_persistence_ok_account_count": 8,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "evidence_quality": {},
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "enabled": True,
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-06-20T23:50:00+08:00",
                "total_run_count": 20,
            },
            "safety": {"status": "ok", "issues": []},
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_auto_advisor_weekly_scheduler_status",
        lambda: {
            "status": "warning",
            "enabled": False,
            "task": command_module.AUTO_ADVISOR_WEEKLY_TASK_PATH,
            "schedule": {"day_of_week": "fri", "hour": "17", "minute": "30"},
            "run_metadata": {"last_run_at": None, "total_run_count": 0},
            "safety": {
                "status": "warning",
                "issues": [{"code": "auto_advisor_weekly_scheduler_disabled"}],
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 6, 30),
    )
    monkeypatch.setattr(
        command_module,
        "_resolve_status_date",
        lambda **kwargs: date(2026, 7, 1),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 6, 30),
    )

    assert payload["status"] == "warning"
    assert payload["acceptance_gate"]["accepted"] is False
    weekly_requirement = payload["acceptance_gate"]["requirements"]["auto_advisor_weekly_scheduler"]
    assert weekly_requirement["ok"] is False
    assert weekly_requirement["issue_count"] == 1
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "auto_advisor_weekly_scheduler"
    }
    assert payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "auto_advisor_weekly_scheduler",
            "action": "fix_auto_advisor_weekly_scheduler",
            "reason": "auto_advisor_weekly_scheduler_not_ok",
            "command": "python manage.py setup_auto_advisor_weekly_report",
        }
    ]


def test_personal_readiness_status_blocks_acceptance_when_quote_pre_readiness_scheduler_is_unsafe(
    monkeypatch,
    tmp_path,
):
    evidence_path = tmp_path / "2026-06-30-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "target_date": "2026-06-30",
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 2,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        command_module,
        "validate_personal_readiness_window",
        lambda **kwargs: {
            "status": "accepted",
            "required_days": kwargs["required_days"],
            "accepted_days": kwargs["required_days"],
            "remaining_days": 0,
            "next_required_date": None,
            "next_required_reason": "window_accepted",
            "projected_completion_date": "2026-07-27",
            "projected_remaining_calendar_days": 0,
            "blocking_issues": [],
            "accepted_evidence": [
                {
                    "target_date": f"2026-06-{day:02d}",
                    "evidence_mode": "formal",
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{day}",
                    "trigger_task_name": command_module.TASK_PATH,
                }
                for day in range(1, 21)
            ],
            "accepted_evidence_manifest": {},
            "accepted_evidence_quality": {
                "formal_record_count": 20,
                "formal_workspace_core_record_count": 20,
                "formal_workspace_core_ok_record_count": 20,
                "formal_workspace_core_missing_record_count": 0,
                "formal_qlib_record_count": 20,
                "formal_qlib_ok_record_count": 20,
                "formal_qlib_missing_record_count": 0,
                "formal_qlib_blocked_record_count": 0,
                "formal_alpha_workspace_record_count": 20,
                "formal_alpha_workspace_ok_record_count": 20,
                "formal_alpha_workspace_missing_record_count": 0,
                "formal_decision_data_record_count": 20,
                "formal_decision_data_ok_record_count": 20,
                "formal_decision_data_missing_record_count": 0,
                "formal_decision_data_blocked_record_count": 0,
                "formal_quote_freshness_record_count": 20,
                "formal_quote_freshness_ok_record_count": 20,
                "formal_quote_freshness_missing_record_count": 0,
                "formal_quote_freshness_stale_record_count": 0,
                "formal_quote_freshness_blocked_record_count": 0,
                "formal_risk_record_count": 20,
                "formal_risk_ok_record_count": 20,
                "formal_risk_missing_record_count": 0,
                "formal_risk_account_count": 40,
                "formal_risk_report_ok_account_count": 40,
                "formal_pre_trade_ok_account_count": 40,
                "formal_pre_trade_missing_account_count": 0,
                "formal_post_investment_ok_account_count": 40,
                "formal_post_investment_missing_account_count": 0,
                "weekly_report_persistence_ok_record_count": 4,
                "weekly_report_persistence_ok_account_count": 8,
                "weekly_report_persistence_missing_record_count": 0,
                "weekly_report_persistence_warning_record_count": 0,
            },
            "evidence_quality": {},
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_scheduler_status",
        lambda: {
            "status": "ok",
            "enabled": True,
            "task": command_module.TASK_PATH,
            "run_metadata": {
                "last_run_at": "2026-06-20T23:50:00+08:00",
                "total_run_count": 20,
            },
            "safety": {"status": "ok", "issues": []},
        },
    )
    monkeypatch.setattr(
        command_module,
        "_collect_quote_pre_readiness_scheduler_status",
        lambda: {
            "status": "warning",
            "enabled": True,
            "task": command_module.QUOTE_PRE_READINESS_TASK_PATH,
            "schedule": {"day_of_week": "1,2,3,4,5", "hour": "18", "minute": "20"},
            "effective_kwargs": {"quote_max_age_hours": 4.0},
            "run_metadata": {"last_run_at": "2026-07-20T18:20:00+08:00", "total_run_count": 20},
            "safety": {
                "status": "warning",
                "issues": [{"code": "quote_pre_readiness_run_missing_after_grace"}],
            },
        },
    )
    monkeypatch.setattr(
        command_module,
        "resolve_default_readiness_target_date",
        lambda: date(2026, 6, 30),
    )
    monkeypatch.setattr(
        command_module,
        "_resolve_status_date",
        lambda **kwargs: date(2026, 7, 1),
    )

    payload = command_module.build_personal_readiness_status(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
        expected_latest_date=date(2026, 6, 30),
    )

    assert payload["status"] == "warning"
    assert payload["monitor_gate"]["ok"] is False
    assert payload["monitor_gate"]["state"] == "operator_action_required"
    assert payload["monitor_gate"]["reason"] == "none"
    assert payload["monitor_gate"]["next_action"] == "none"
    assert payload["acceptance_gate"]["accepted"] is False
    assert payload["acceptance_gate"]["issue"] == "quote_pre_readiness_run_missing_after_grace"
    requirement = payload["acceptance_gate"]["requirements"]["quote_pre_readiness_scheduler"]
    assert requirement["ok"] is False
    assert requirement["issue_count"] == 1
    assert requirement["enabled"] is True
    assert requirement["task"] == command_module.QUOTE_PRE_READINESS_TASK_PATH
    assert requirement["hour"] == "18"
    assert requirement["minute"] == "20"
    assert requirement["quote_max_age_hours"] == 4.0
    assert {item["name"] for item in payload["acceptance_gate"]["failed_requirements"]} == {
        "quote_pre_readiness_scheduler"
    }
    assert payload["acceptance_gate"]["operator_actions"] == [
        {
            "requirement": "quote_pre_readiness_scheduler",
            "action": "fix_quote_pre_readiness_scheduler",
            "reason": "quote_pre_readiness_scheduler_not_ok",
            "command": "python manage.py setup_decision_quote_refresh",
        }
    ]


def test_personal_readiness_status_warns_when_scheduler_is_disabled(monkeypatch):
    fake_task = SimpleNamespace(
        name=command_module.TASK_NAME,
        task=command_module.TASK_PATH,
        enabled=False,
        kwargs='{"calendar_source": "auto"}',
        crontab=SimpleNamespace(
            minute="50",
            hour="23",
            day_of_week="mon-fri",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(command_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_scheduler_status()

    issue_codes = {issue["code"] for issue in payload["safety"]["issues"]}
    assert payload["status"] == "warning"
    assert payload["safety"]["enabled"] is False
    assert "scheduler_disabled" in issue_codes


def test_personal_readiness_status_warns_when_scheduler_runs_before_post_close(
    monkeypatch,
):
    fake_task = SimpleNamespace(
        name=command_module.TASK_NAME,
        task=command_module.TASK_PATH,
        enabled=True,
        kwargs='{"calendar_source": "auto"}',
        crontab=SimpleNamespace(
            minute="0",
            hour="14",
            day_of_week="mon-fri",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(command_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_scheduler_status()

    issue_codes = {issue["code"] for issue in payload["safety"]["issues"]}
    assert payload["status"] == "warning"
    assert "scheduler_before_post_close" in issue_codes


def test_personal_readiness_status_warns_when_scheduler_timezone_is_not_shanghai(
    monkeypatch,
):
    fake_task = SimpleNamespace(
        name=command_module.TASK_NAME,
        task=command_module.TASK_PATH,
        enabled=True,
        kwargs='{"calendar_source": "auto"}',
        crontab=SimpleNamespace(
            minute="50",
            hour="23",
            day_of_week="mon-fri",
            day_of_month="*",
            month_of_year="*",
            timezone="UTC",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(command_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_scheduler_status()

    issue_codes = {issue["code"] for issue in payload["safety"]["issues"]}
    assert payload["status"] == "warning"
    assert "unexpected_scheduler_timezone" in issue_codes


def test_personal_readiness_status_warns_when_scheduler_day_of_week_is_not_weekdays(
    monkeypatch,
):
    fake_task = SimpleNamespace(
        name=command_module.TASK_NAME,
        task=command_module.TASK_PATH,
        enabled=True,
        kwargs='{"calendar_source": "auto"}',
        crontab=SimpleNamespace(
            minute="50",
            hour="23",
            day_of_week="mon-thu",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(command_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_scheduler_status()

    issue_codes = {issue["code"] for issue in payload["safety"]["issues"]}
    assert payload["status"] == "warning"
    assert "unexpected_scheduler_day_of_week" in issue_codes


def test_personal_readiness_status_warns_when_scheduler_day_or_month_is_restricted(
    monkeypatch,
):
    fake_task = SimpleNamespace(
        name=command_module.TASK_NAME,
        task=command_module.TASK_PATH,
        enabled=True,
        kwargs='{"calendar_source": "auto"}',
        crontab=SimpleNamespace(
            minute="50",
            hour="23",
            day_of_week="mon-fri",
            day_of_month="1",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(command_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_scheduler_status()

    issue_codes = {issue["code"] for issue in payload["safety"]["issues"]}
    assert payload["status"] == "warning"
    assert "unexpected_scheduler_day_of_month" in issue_codes


def test_personal_readiness_status_warns_when_scheduler_has_run_limits(
    monkeypatch,
):
    fake_task = SimpleNamespace(
        name=command_module.TASK_NAME,
        task=command_module.TASK_PATH,
        enabled=True,
        one_off=True,
        expires="2026-07-10T00:00:00+08:00",
        expire_seconds=3600,
        kwargs='{"calendar_source": "auto"}',
        crontab=SimpleNamespace(
            minute="50",
            hour="23",
            day_of_week="mon-fri",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(command_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_scheduler_status()

    issue_codes = {issue["code"] for issue in payload["safety"]["issues"]}
    assert payload["status"] == "warning"
    assert payload["run_controls"]["one_off"] is True
    assert payload["run_controls"]["expires"] == "2026-07-10T00:00:00+08:00"
    assert payload["run_controls"]["expire_seconds"] == 3600
    assert "scheduler_one_off_enabled" in issue_codes
    assert "scheduler_expires_enabled" in issue_codes
    assert "scheduler_expire_seconds_enabled" in issue_codes


def test_personal_readiness_status_warns_when_scheduler_args_are_not_empty(
    monkeypatch,
):
    fake_task = SimpleNamespace(
        name=command_module.TASK_NAME,
        task=command_module.TASK_PATH,
        enabled=True,
        args='["2026-07-01"]',
        kwargs='{"calendar_source": "auto"}',
        crontab=SimpleNamespace(
            minute="50",
            hour="23",
            day_of_week="mon-fri",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(command_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_scheduler_status()

    issue_codes = {issue["code"] for issue in payload["safety"]["issues"]}
    assert payload["status"] == "warning"
    assert payload["effective_args"] == ["2026-07-01"]
    assert "unexpected_scheduler_args" in issue_codes
    assert (
        command_module._parse_scheduler_args('{"target_date": "2026-07-01"}')["error"]
        == "args_json_must_be_array"
    )
    assert command_module._parse_scheduler_args("not-json")["error"].startswith("invalid_json")


def test_personal_readiness_status_warns_when_scheduler_delivery_controls_are_custom(
    monkeypatch,
):
    fake_task = SimpleNamespace(
        name=command_module.TASK_NAME,
        task=command_module.TASK_PATH,
        enabled=True,
        queue="readiness",
        exchange="custom",
        routing_key="readiness.daily",
        priority=3,
        headers='{"x-readiness": true}',
        kwargs='{"calendar_source": "auto"}',
        crontab=SimpleNamespace(
            minute="50",
            hour="23",
            day_of_week="mon-fri",
            day_of_month="*",
            month_of_year="*",
            timezone="Asia/Shanghai",
        ),
    )

    class FakeQuery:
        @staticmethod
        def first():
            return fake_task

    class FakeManager:
        @staticmethod
        def filter(**kwargs):
            assert kwargs == {"name": command_module.TASK_NAME}
            return FakeQuery()

    class FakePeriodicTask:
        objects = FakeManager()

    monkeypatch.setattr(command_module, "PeriodicTask", FakePeriodicTask)

    payload = command_module._collect_scheduler_status()

    issue_codes = {issue["code"] for issue in payload["safety"]["issues"]}
    assert payload["status"] == "warning"
    assert payload["delivery_controls"]["queue"] == "readiness"
    assert payload["delivery_controls"]["effective_headers"] == {"x-readiness": True}
    assert "unexpected_scheduler_queue" in issue_codes
    assert "unexpected_scheduler_exchange" in issue_codes
    assert "unexpected_scheduler_routing_key" in issue_codes
    assert "unexpected_scheduler_priority" in issue_codes
    assert "unexpected_scheduler_headers" in issue_codes
    assert command_module._parse_scheduler_headers("[]")["error"] == "headers_json_must_be_object"
    assert command_module._parse_scheduler_headers("not-json")["error"].startswith("invalid_json")
