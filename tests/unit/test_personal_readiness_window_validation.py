from __future__ import annotations

import json
from datetime import date, timedelta
from hashlib import sha256

import pytest
from django.core.management import CommandError

from apps.task_monitor.management.commands import (
    validate_personal_readiness_window as command_module,
)


def test_validate_personal_readiness_window_counts_remaining_days(tmp_path):
    _write_evidence(tmp_path, date(2026, 6, 30), status="ok")
    evidence_path = tmp_path / "2026-06-30-personal-readiness.json"

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 1
    assert payload["remaining_days"] == 19
    assert payload["accepted_dates"] == ["2026-06-30"]
    accepted_evidence = payload["accepted_evidence"]
    assert len(accepted_evidence) == 1
    raw = evidence_path.read_bytes()
    assert accepted_evidence[0]["target_date"] == "2026-06-30"
    assert accepted_evidence[0]["path"] == str(evidence_path)
    assert accepted_evidence[0]["size_bytes"] == len(raw)
    assert accepted_evidence[0]["sha256"] == sha256(raw).hexdigest()
    assert accepted_evidence[0]["evidence_mode"] == "legacy_without_operation_context"
    assert accepted_evidence[0]["trigger_source"] is None
    assert accepted_evidence[0]["trigger_task_id"] is None
    assert accepted_evidence[0]["trigger_task_name"] is None
    manifest_payload = {
        "schema_version": "accepted-readiness-evidence-manifest.v1",
        "record_count": 1,
        "target_dates": ["2026-06-30"],
        "records": accepted_evidence,
    }
    expected_manifest_hash = sha256(
        json.dumps(
            manifest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert payload["accepted_evidence_manifest"] == {
        "schema_version": "accepted-readiness-evidence-manifest.v1",
        "record_count": 1,
        "target_dates": ["2026-06-30"],
        "sha256": expected_manifest_hash,
    }
    assert payload["accepted_evidence_quality"] == {
        "record_count": 1,
        "start_date": "2026-06-30",
        "end_date": "2026-06-30",
        "acceptance_candidate_record_count": 1,
        "formal_record_count": 0,
        "legacy_record_count": 1,
        "diagnostic_record_count": 0,
        "scheduler_trigger_record_count": 0,
        "manual_trigger_record_count": 0,
        "unknown_trigger_record_count": 1,
        "task_provenance_record_count": 0,
        "missing_task_provenance_record_count": 1,
        "formal_workspace_core_record_count": 0,
        "formal_workspace_core_ok_record_count": 0,
        "formal_workspace_core_missing_record_count": 0,
        "formal_qlib_record_count": 0,
        "formal_qlib_ok_record_count": 0,
        "formal_qlib_missing_record_count": 0,
        "formal_qlib_blocked_record_count": 0,
        "formal_alpha_workspace_record_count": 0,
        "formal_alpha_workspace_ok_record_count": 0,
        "formal_alpha_workspace_missing_record_count": 0,
        "formal_decision_data_record_count": 0,
        "formal_decision_data_ok_record_count": 0,
        "formal_decision_data_missing_record_count": 0,
        "formal_decision_data_blocked_record_count": 0,
        "formal_quote_freshness_record_count": 0,
        "formal_quote_freshness_ok_record_count": 0,
        "formal_quote_freshness_missing_record_count": 0,
        "formal_quote_freshness_stale_record_count": 0,
        "formal_quote_freshness_blocked_record_count": 0,
        "formal_quote_pre_readiness_scheduler_record_count": 0,
        "formal_quote_pre_readiness_scheduler_ok_record_count": 0,
        "formal_quote_pre_readiness_scheduler_missing_record_count": 0,
        "formal_quote_pre_readiness_scheduler_blocked_record_count": 0,
        "formal_risk_record_count": 0,
        "formal_risk_ok_record_count": 0,
        "formal_risk_missing_record_count": 0,
        "formal_risk_account_count": 0,
        "formal_risk_report_ok_account_count": 0,
        "formal_risk_persisted_report_account_count": 0,
        "formal_pre_trade_ok_account_count": 0,
        "formal_pre_trade_missing_account_count": 0,
        "formal_post_investment_ok_account_count": 0,
        "formal_post_investment_missing_account_count": 0,
        "weekly_report_record_count": 0,
        "weekly_report_persistence_ok_record_count": 0,
        "weekly_report_persistence_missing_record_count": 0,
        "weekly_report_persistence_warning_record_count": 0,
        "weekly_report_account_count": 0,
        "weekly_report_persistence_ok_account_count": 0,
        "weekly_report_persistence_missing_account_count": 0,
        "weekly_report_persistence_warning_account_count": 0,
        "scheduled_weekly_report_record_count": 0,
        "scheduled_weekly_report_persistence_ok_record_count": 0,
        "scheduled_weekly_report_persistence_missing_record_count": 0,
        "scheduled_weekly_report_persistence_warning_record_count": 0,
        "scheduled_weekly_report_account_count": 0,
        "scheduled_weekly_report_persistence_ok_account_count": 0,
        "scheduled_weekly_report_persistence_missing_account_count": 0,
        "scheduled_weekly_report_persistence_warning_account_count": 0,
        "evidence_modes": ["legacy_without_operation_context"],
        "trigger_sources": [],
        "trigger_task_names": [],
    }
    assert payload["next_required_date"] == "2026-07-01"
    assert payload["next_required_reason"] == "next_trading_day"
    assert payload["projected_completion_date"] == "2026-07-27"
    assert payload["projected_remaining_calendar_days"] == 27
    assert payload["scheduler_clean_suffix_days"] == 0
    assert payload["scheduler_clean_remaining_days"] == 20
    assert payload["projected_scheduler_completion_date"] == "2026-07-28"
    assert payload["projected_scheduler_remaining_calendar_days"] == 28


def test_validate_personal_readiness_window_accepts_required_trading_days(tmp_path):
    current = date(2026, 6, 1)
    written = 0
    while written < 20:
        if current.weekday() < 5:
            _write_evidence(
                tmp_path,
                current,
                status="ok",
                operation_context={
                    "mode": "formal",
                    "target_date_closed": True,
                    "latest_closed_date": current.isoformat(),
                    "allow_unclosed_target_date": False,
                    "trigger_source": "scheduler",
                    "trigger_task_id": f"task-{current.isoformat()}",
                    "trigger_task_name": (
                        "apps.task_monitor.application.tasks." "run_personal_readiness_daily_task"
                    ),
                },
            )
            written += 1
        current += timedelta(days=1)

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=20,
        calendar_source="weekday",
    )

    assert payload["status"] == "accepted"
    assert payload["accepted_days"] == 20
    assert payload["remaining_days"] == 0
    assert payload["accepted_evidence_quality"]["record_count"] == 20
    assert payload["accepted_evidence_quality"]["start_date"] == "2026-06-01"
    assert payload["accepted_evidence_quality"]["end_date"] == "2026-06-26"
    assert payload["accepted_evidence_quality"]["scheduler_trigger_record_count"] == 20
    assert payload["accepted_evidence_quality"]["task_provenance_record_count"] == 20
    assert payload["accepted_evidence_quality"]["missing_task_provenance_record_count"] == 0
    assert payload["accepted_evidence_quality"]["formal_workspace_core_record_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_workspace_core_ok_record_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_workspace_core_missing_record_count"] == 0
    assert payload["accepted_evidence_quality"]["formal_qlib_record_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_qlib_ok_record_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_qlib_missing_record_count"] == 0
    assert payload["accepted_evidence_quality"]["formal_qlib_blocked_record_count"] == 0
    assert payload["accepted_evidence_quality"]["formal_alpha_workspace_record_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_alpha_workspace_ok_record_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_alpha_workspace_missing_record_count"] == 0
    assert payload["accepted_evidence_quality"]["formal_decision_data_record_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_decision_data_ok_record_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_decision_data_missing_record_count"] == 0
    assert payload["accepted_evidence_quality"]["formal_decision_data_blocked_record_count"] == 0
    assert payload["accepted_evidence_quality"]["formal_quote_freshness_record_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_quote_freshness_ok_record_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_quote_freshness_missing_record_count"] == 0
    assert payload["accepted_evidence_quality"]["formal_quote_freshness_stale_record_count"] == 0
    assert payload["accepted_evidence_quality"]["formal_quote_freshness_blocked_record_count"] == 0
    assert (
        payload["accepted_evidence_quality"][
            "formal_quote_pre_readiness_scheduler_record_count"
        ]
        == 20
    )
    assert (
        payload["accepted_evidence_quality"][
            "formal_quote_pre_readiness_scheduler_ok_record_count"
        ]
        == 20
    )
    assert (
        payload["accepted_evidence_quality"][
            "formal_quote_pre_readiness_scheduler_missing_record_count"
        ]
        == 0
    )
    assert (
        payload["accepted_evidence_quality"][
            "formal_quote_pre_readiness_scheduler_blocked_record_count"
        ]
        == 0
    )
    assert payload["accepted_evidence_quality"]["formal_risk_record_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_risk_ok_record_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_risk_account_count"] == 20
    assert (
        payload["accepted_evidence_quality"]["formal_risk_persisted_report_account_count"]
        == 20
    )
    assert payload["accepted_evidence_quality"]["formal_pre_trade_ok_account_count"] == 20
    assert payload["accepted_evidence_quality"]["formal_post_investment_ok_account_count"] == 20
    assert payload["accepted_evidence_quality"]["trigger_task_names"] == [
        "apps.task_monitor.application.tasks.run_personal_readiness_daily_task"
    ]
    assert payload["accepted_evidence"][0]["trigger_task_id"] == "task-2026-06-01"
    assert payload["next_required_date"] is None
    assert payload["next_required_reason"] == "window_accepted"
    assert payload["projected_completion_date"] == "2026-06-26"
    assert payload["projected_remaining_calendar_days"] == 0
    assert payload["scheduler_clean_suffix_days"] == 20
    assert payload["scheduler_clean_remaining_days"] == 0
    assert payload["projected_scheduler_completion_date"] == "2026-06-26"
    assert payload["projected_scheduler_remaining_calendar_days"] == 0


def test_validate_personal_readiness_window_rejects_missing_day_gap(tmp_path):
    _write_evidence(tmp_path, date(2026, 6, 29), status="ok")
    _write_evidence(tmp_path, date(2026, 7, 1), status="ok")

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=2,
        calendar_source="weekday",
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 1
    assert payload["accepted_dates"] == ["2026-07-01"]
    assert payload["blocking_issues"][0]["target_date"] == "2026-06-30"
    assert payload["blocking_issues"][0]["reason"] == "evidence is missing"


def test_validate_personal_readiness_window_rejects_missing_expected_latest_date(tmp_path):
    _write_evidence(tmp_path, date(2026, 6, 30), status="ok")

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=2,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 1),
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 0
    assert payload["latest_target_date"] == "2026-07-01"
    assert payload["expected_latest_date"] == "2026-07-01"
    assert payload["blocking_issues"][0]["target_date"] == "2026-07-01"
    assert payload["blocking_issues"][0]["reason"] == "evidence is missing"
    assert payload["next_required_date"] == "2026-07-01"
    assert payload["next_required_reason"] == "blocking_issue"
    assert payload["projected_completion_date"] == "2026-07-02"
    assert payload["projected_remaining_calendar_days"] == 1


def test_validate_personal_readiness_window_reports_missing_expected_date_without_records(
    tmp_path,
):
    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
        expected_latest_date=date(2026, 7, 1),
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 0
    assert payload["blocking_issues"][0]["target_date"] == "2026-07-01"
    assert payload["blocking_issues"][0]["reason"] == "evidence is missing"
    assert payload["next_required_date"] == "2026-07-01"
    assert payload["next_required_reason"] == "blocking_issue"
    assert payload["projected_completion_date"] == "2026-07-01"
    assert payload["projected_remaining_calendar_days"] == 0


def test_validate_personal_readiness_window_uses_injected_trading_calendar(tmp_path):
    _write_evidence(tmp_path, date(2026, 6, 29), status="ok")
    _write_evidence(tmp_path, date(2026, 7, 1), status="ok")

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=2,
        trading_calendar={date(2026, 6, 29), date(2026, 7, 1)},
    )

    assert payload["status"] == "accepted"
    assert payload["calendar_source"] == "injected"
    assert payload["accepted_days"] == 2
    assert payload["accepted_dates"] == ["2026-06-29", "2026-07-01"]
    assert payload["blocking_issues"] == []


def test_validate_personal_readiness_window_reports_calendar_source(tmp_path):
    _write_evidence(tmp_path, date(2026, 6, 30), status="ok")

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
    )

    assert payload["status"] == "accepted"
    assert payload["calendar_source"] == "weekday"
    assert payload["calendar_day_count"] is None


def test_validate_personal_readiness_window_auto_uses_qlib_calendar(monkeypatch, tmp_path):
    _write_evidence(tmp_path, date(2026, 6, 29), status="ok")
    _write_evidence(tmp_path, date(2026, 7, 1), status="ok")
    monkeypatch.setattr(
        command_module,
        "_load_qlib_trading_calendar",
        lambda: [date(2026, 6, 29), date(2026, 7, 1)],
    )

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=2,
    )

    assert payload["status"] == "accepted"
    assert payload["calendar_source"] == "qlib"
    assert payload["calendar_day_count"] == 2
    assert payload["accepted_dates"] == ["2026-06-29", "2026-07-01"]


def test_validate_personal_readiness_window_next_required_falls_back_after_qlib_calendar_end(
    monkeypatch,
    tmp_path,
):
    _write_evidence(tmp_path, date(2026, 6, 30), status="ok")
    monkeypatch.setattr(
        command_module,
        "_load_qlib_trading_calendar",
        lambda: [date(2026, 6, 30)],
    )

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=20,
    )

    assert payload["calendar_source"] == "qlib"
    assert payload["accepted_dates"] == ["2026-06-30"]
    assert payload["next_required_date"] == "2026-07-01"
    assert payload["next_required_reason"] == "next_trading_day"


def test_validate_personal_readiness_window_auto_falls_back_when_qlib_calendar_stale(
    monkeypatch,
    tmp_path,
):
    _write_evidence(tmp_path, date(2026, 6, 30), status="ok")
    monkeypatch.setattr(
        command_module,
        "_load_qlib_trading_calendar",
        lambda: [date(2026, 6, 30)],
    )

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=2,
        expected_latest_date=date(2026, 7, 1),
    )

    assert payload["calendar_source"] == "weekday_fallback"
    assert payload["blocking_issues"][0]["target_date"] == "2026-07-01"
    assert payload["blocking_issues"][0]["reason"] == "evidence is missing"


def test_validate_personal_readiness_window_records_blocking_issue(tmp_path):
    _write_evidence(
        tmp_path,
        date(2026, 6, 30),
        status="ok",
        workspace_status="warning",
    )

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 0
    assert payload["blocking_issues"][0]["reason"] == "workspace_status is warning"


def test_validate_personal_readiness_window_rejects_diagnostic_evidence(tmp_path):
    _write_evidence(
        tmp_path,
        date(2026, 7, 1),
        status="ok",
        operation_context={
            "mode": "diagnostic_unclosed_target",
            "target_date_closed": False,
            "latest_closed_date": "2026-06-30",
            "allow_unclosed_target_date": True,
        },
    )

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 0
    assert payload["blocking_issues"][0]["target_date"] == "2026-07-01"
    assert (
        payload["blocking_issues"][0]["reason"]
        == "operation_context mode is diagnostic_unclosed_target"
    )


def test_validate_personal_readiness_window_rejects_formal_missing_pre_trade(tmp_path):
    _write_evidence(
        tmp_path,
        date(2026, 7, 1),
        status="ok",
        operation_context={
            "mode": "formal",
            "target_date_closed": True,
            "latest_closed_date": "2026-07-01",
            "allow_unclosed_target_date": False,
        },
        include_pre_trade=False,
    )

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 0
    assert payload["blocking_issues"][0]["target_date"] == "2026-07-01"
    assert payload["blocking_issues"][0]["reason"] == "account 1 pre-trade risk status is missing"


def test_validate_personal_readiness_window_rejects_formal_missing_decision_data(tmp_path):
    _write_evidence(
        tmp_path,
        date(2026, 7, 1),
        status="ok",
        operation_context={
            "mode": "formal",
            "target_date_closed": True,
            "latest_closed_date": "2026-07-01",
            "allow_unclosed_target_date": False,
        },
    )
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    payload_data = json.loads(evidence_path.read_text(encoding="utf-8"))
    del payload_data["system"]["checks"]["decision_data"]
    evidence_path.write_text(json.dumps(payload_data), encoding="utf-8")

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 0
    assert payload["blocking_issues"][0]["target_date"] == "2026-07-01"
    assert payload["blocking_issues"][0]["reason"] == (
        "decision_data readiness evidence is missing"
    )
    quality = payload["evidence_quality"]
    assert quality["formal_decision_data_record_count"] == 1
    assert quality["formal_decision_data_missing_record_count"] == 1
    assert quality["formal_decision_data_ok_record_count"] == 0


def test_validate_personal_readiness_window_rejects_formal_missing_qlib_evidence(tmp_path):
    _write_evidence(
        tmp_path,
        date(2026, 7, 1),
        status="ok",
        operation_context={
            "mode": "formal",
            "target_date_closed": True,
            "latest_closed_date": "2026-07-01",
            "allow_unclosed_target_date": False,
        },
    )
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    payload_data = json.loads(evidence_path.read_text(encoding="utf-8"))
    del payload_data["qlib"]
    evidence_path.write_text(json.dumps(payload_data), encoding="utf-8")

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 0
    assert payload["blocking_issues"][0]["target_date"] == "2026-07-01"
    assert payload["blocking_issues"][0]["reason"] == "qlib readiness evidence is missing"
    quality = payload["evidence_quality"]
    assert quality["formal_qlib_record_count"] == 1
    assert quality["formal_qlib_missing_record_count"] == 1
    assert quality["formal_qlib_ok_record_count"] == 0


def test_validate_personal_readiness_window_rejects_formal_missing_alpha_workspace(tmp_path):
    _write_evidence(
        tmp_path,
        date(2026, 7, 1),
        status="ok",
        operation_context={
            "mode": "formal",
            "target_date_closed": True,
            "latest_closed_date": "2026-07-01",
            "allow_unclosed_target_date": False,
        },
    )
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    payload_data = json.loads(evidence_path.read_text(encoding="utf-8"))
    del payload_data["system"]["checks"]["alpha_workspace_consistency"]
    evidence_path.write_text(json.dumps(payload_data), encoding="utf-8")

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 0
    assert payload["blocking_issues"][0]["target_date"] == "2026-07-01"
    assert payload["blocking_issues"][0]["reason"] == (
        "alpha_workspace_consistency evidence is missing"
    )
    quality = payload["evidence_quality"]
    assert quality["formal_alpha_workspace_record_count"] == 1
    assert quality["formal_alpha_workspace_missing_record_count"] == 1
    assert quality["formal_alpha_workspace_ok_record_count"] == 0


def test_validate_personal_readiness_window_rejects_formal_missing_workspace_core(tmp_path):
    _write_evidence(
        tmp_path,
        date(2026, 7, 1),
        status="ok",
        operation_context={
            "mode": "formal",
            "target_date_closed": True,
            "latest_closed_date": "2026-07-01",
            "allow_unclosed_target_date": False,
        },
    )
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    payload_data = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload_data.pop("workspace")
    evidence_path.write_text(json.dumps(payload_data), encoding="utf-8")

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 0
    assert payload["blocking_issues"][0]["target_date"] == "2026-07-01"
    assert payload["blocking_issues"][0]["reason"] == "workspace core evidence status is missing"
    quality = payload["evidence_quality"]
    assert quality["formal_workspace_core_record_count"] == 1
    assert quality["formal_workspace_core_missing_record_count"] == 1
    assert quality["formal_workspace_core_ok_record_count"] == 0


def test_validate_personal_readiness_window_rejects_formal_missing_post_investment(
    tmp_path,
):
    _write_evidence(
        tmp_path,
        date(2026, 7, 1),
        status="ok",
        operation_context={
            "mode": "formal",
            "target_date_closed": True,
            "latest_closed_date": "2026-07-01",
            "allow_unclosed_target_date": False,
        },
        include_post_investment=False,
    )

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 0
    assert payload["blocking_issues"][0]["target_date"] == "2026-07-01"
    assert (
        payload["blocking_issues"][0]["reason"] == "account 1 post-investment risk passed is None"
    )


def test_validate_personal_readiness_window_reports_formal_missing_persisted_risk_report(
    tmp_path,
):
    _write_evidence(
        tmp_path,
        date(2026, 7, 1),
        status="ok",
        operation_context={
            "mode": "formal",
            "target_date_closed": True,
            "latest_closed_date": "2026-07-01",
            "allow_unclosed_target_date": False,
        },
        include_risk_report_id=False,
    )

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
    )

    assert payload["status"] == "accepted"
    assert payload["accepted_days"] == 1
    quality = payload["evidence_quality"]
    assert quality["formal_risk_report_ok_account_count"] == 1
    assert quality["formal_risk_persisted_report_account_count"] == 0
    assert quality["formal_risk_ok_record_count"] == 0


def test_validate_personal_readiness_window_reports_evidence_quality(tmp_path):
    _write_evidence(tmp_path, date(2026, 6, 30), status="ok")
    _write_evidence(
        tmp_path,
        date(2026, 7, 1),
        status="ok",
        operation_context={
            "mode": "diagnostic_unclosed_target",
            "target_date_closed": False,
            "latest_closed_date": "2026-06-30",
            "allow_unclosed_target_date": True,
        },
    )
    _write_evidence(tmp_path, date(2026, 7, 4), status="ok")

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
    )

    quality = payload["evidence_quality"]
    assert quality["record_count"] == 3
    assert quality["trading_record_count"] == 2
    assert quality["non_trading_record_count"] == 1
    assert quality["accepted_record_count"] == 2
    assert quality["rejected_record_count"] == 1
    assert quality["acceptance_candidate_record_count"] == 2
    assert quality["formal_record_count"] == 0
    assert quality["legacy_record_count"] == 2
    assert quality["diagnostic_record_count"] == 1
    assert quality["task_provenance_record_count"] == 0
    assert quality["missing_task_provenance_record_count"] == 3
    assert quality["non_trading_dates"] == ["2026-07-04"]
    assert quality["rejected_dates"] == [
        {
            "target_date": "2026-07-01",
            "reason": "operation_context mode is diagnostic_unclosed_target",
            "evidence_mode": "diagnostic_unclosed_target",
        }
    ]


def test_validate_personal_readiness_window_reports_weekly_persistence_quality(tmp_path):
    operation_context = {
        "mode": "formal",
        "target_date_closed": True,
        "allow_unclosed_target_date": False,
        "trigger_source": "scheduler",
        "trigger_task_id": "task-1",
        "trigger_task_name": "apps.task_monitor.application.tasks.run_personal_readiness_daily_task",
    }
    _write_evidence(
        tmp_path,
        date(2026, 6, 30),
        status="ok",
        operation_context=operation_context,
        auto_advisor={
            "status": "ok",
            "weekly_report": {"status": "ok"},
            "weekly_report_persistence": {
                "status": "ok",
                "matched_report": {"id": 1},
                "delivered_notification_count": 1,
            },
        },
    )
    _write_evidence(
        tmp_path,
        date(2026, 7, 1),
        status="ok",
        operation_context={**operation_context, "trigger_task_id": "task-2"},
        auto_advisor={
            "status": "ok",
            "weekly_report": {"status": "ok"},
            "weekly_report_persistence": {
                "status": "warning",
                "reason": "no persisted weekly report found for 2026-07-01",
            },
        },
    )

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=2,
        calendar_source="weekday",
    )

    assert payload["status"] == "accepted"
    quality = payload["accepted_evidence_quality"]
    assert quality["weekly_report_record_count"] == 2
    assert quality["weekly_report_persistence_ok_record_count"] == 1
    assert quality["weekly_report_persistence_warning_record_count"] == 1
    assert quality["weekly_report_persistence_missing_record_count"] == 0
    assert quality["weekly_report_account_count"] == 2
    assert quality["weekly_report_persistence_ok_account_count"] == 1
    assert quality["weekly_report_persistence_warning_account_count"] == 1
    assert quality["scheduled_weekly_report_record_count"] == 0
    assert quality["scheduled_weekly_report_persistence_ok_record_count"] == 0
    assert quality["scheduled_weekly_report_persistence_warning_record_count"] == 0
    assert quality["scheduled_weekly_report_account_count"] == 0
    assert payload["evidence_quality"]["weekly_report_record_count"] == 2
    assert payload["evidence_quality"]["scheduled_weekly_report_record_count"] == 0
    assert (
        payload["evidence_quality"]["scheduled_weekly_report_persistence_warning_record_count"]
        == 0
    )


def test_validate_personal_readiness_window_reports_missing_quote_pre_readiness_scheduler_evidence(
    tmp_path,
):
    operation_context = {
        "mode": "formal",
        "target_date_closed": True,
        "latest_closed_date": "2026-06-30",
        "allow_unclosed_target_date": False,
        "trigger_source": "scheduler",
        "trigger_task_id": "task-1",
        "trigger_task_name": "apps.task_monitor.application.tasks.run_personal_readiness_daily_task",
    }
    _write_evidence(
        tmp_path,
        date(2026, 6, 30),
        status="ok",
        operation_context=operation_context,
        include_quote_pre_readiness_scheduler=False,
    )

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=1,
        calendar_source="weekday",
    )

    quality = payload["accepted_evidence_quality"]
    assert quality["formal_quote_pre_readiness_scheduler_record_count"] == 1
    assert quality["formal_quote_pre_readiness_scheduler_ok_record_count"] == 0
    assert quality["formal_quote_pre_readiness_scheduler_missing_record_count"] == 1
    assert quality["formal_quote_pre_readiness_scheduler_blocked_record_count"] == 0


def test_validate_personal_readiness_window_rejects_failed_day_in_current_streak(tmp_path):
    _write_evidence(tmp_path, date(2026, 6, 29), status="ok")
    _write_evidence(
        tmp_path,
        date(2026, 6, 30),
        status="ok",
        qlib_status="warning",
    )
    _write_evidence(tmp_path, date(2026, 7, 1), status="ok")

    payload = command_module.validate_personal_readiness_window(
        output_dir=tmp_path,
        required_days=2,
        calendar_source="weekday",
    )

    assert payload["status"] == "in_progress"
    assert payload["accepted_days"] == 1
    assert payload["accepted_dates"] == ["2026-07-01"]
    assert payload["blocking_issues"][0]["target_date"] == "2026-06-30"
    assert payload["blocking_issues"][0]["reason"] == "qlib_status is warning"


def test_validate_personal_readiness_window_strict_raises_when_incomplete(monkeypatch, tmp_path):
    _write_evidence(tmp_path, date(2026, 6, 30), status="ok")
    command = command_module.Command()
    monkeypatch.setattr(command_module, "settings", type("Settings", (), {"BASE_DIR": tmp_path})())

    with pytest.raises(CommandError):
        command.handle(
            output_dir=str(tmp_path),
            required_days=20,
            calendar_source="weekday",
            strict=True,
            print_json=False,
        )


def _write_evidence(
    root,
    target_date: date,
    *,
    status: str,
    system_status: str = "ok",
    qlib_status: str = "ok",
    workspace_status: str = "ok",
    operation_context: dict | None = None,
    include_pre_trade: bool = True,
    include_post_investment: bool = True,
    include_risk_report_id: bool = True,
    auto_advisor: dict | None = None,
    include_quote_pre_readiness_scheduler: bool = True,
) -> None:
    risk_report = {"status": "ok"}
    if operation_context is not None and include_risk_report_id:
        risk_report["report_id"] = f"risk-{target_date.isoformat()}"
    if operation_context is not None and include_pre_trade:
        risk_report["pre_trade_check"] = {"status": "ok"}
    if operation_context is not None and include_post_investment:
        risk_report["post_investment_check"] = {"passed": True}
    payload = {
        "status": status,
        "target_date": target_date.isoformat(),
        "summary": {
            "system_status": system_status,
            "qlib_status": qlib_status,
            "workspace_status": workspace_status,
            "target_count": 1,
        },
        "accounts": [
            {
                "account_id": 1,
                "status": "ok",
                "risk_center_daily_report": risk_report,
                "auto_advisor": auto_advisor or {"status": "ok"},
            }
        ],
    }
    if operation_context is not None:
        payload["operation_context"] = operation_context
        payload["qlib"] = {
            "status": "ok",
            "check_only": True,
            "command": "build_qlib_data --check-only",
        }
        payload["workspace"] = {
            "status": "ok",
            "result": {
                "components": {
                    "regime_snapshot": {"status": "success"},
                    "pulse_snapshot": {"status": "success", "is_reliable": True},
                    "action_recommendation": {"status": "success"},
                }
            },
        }
        payload["system"] = {
            "status": "ok",
            "checks": {
                "decision_data": {
                    "status": "ok",
                    "readiness_status": "ok",
                    "must_not_use_for_decision": False,
                    "quotes": {
                        "510300.SH": {
                            "status": "ok",
                            "is_stale": False,
                            "freshness_status": "fresh",
                            "must_not_use_for_decision": False,
                        },
                        "000300.SH": {
                            "status": "ok",
                            "is_stale": False,
                            "freshness_status": "fresh",
                            "must_not_use_for_decision": False,
                        },
                    },
                },
                "alpha_workspace_consistency": {"status": "ok"},
            },
        }
        if include_quote_pre_readiness_scheduler:
            payload["scheduler_evidence"] = {
                "quote_pre_readiness_scheduler": {
                    "status": "ok",
                    "enabled": True,
                    "schedule": {
                        "hour": "19",
                        "minute": "20",
                        "day_of_week": "1,2,3,4,5",
                        "day_of_month": "*",
                        "month_of_year": "*",
                        "timezone": "Asia/Shanghai",
                    },
                    "run_metadata": {
                        "last_run_at": f"{target_date.isoformat()}T19:20:00+08:00",
                        "total_run_count": 1,
                    },
                    "safety": {"status": "ok", "issues": []},
                }
            }
    path = root / f"{target_date.isoformat()}-personal-readiness.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
