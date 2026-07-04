from pathlib import Path

from apps.task_monitor.application import readiness_monitor_service as service
from apps.task_monitor.application.readiness_monitor_service import (
    _summarize_personal_readiness_payload,
    get_personal_readiness_monitor_placeholder,
)


def test_readiness_monitor_placeholder_is_lightweight_loading_state():
    payload = get_personal_readiness_monitor_placeholder()

    assert payload["status"] == "loading"
    assert payload["daily_state"]["code"] == "loading"
    assert payload["scheduler_runtime"]["status"] == "not_checked"
    assert payload["window"]["accepted_days"] == 0


def test_readiness_monitor_summary_marks_latest_closed_day_accepted(monkeypatch):
    _stub_data_coverage(monkeypatch)
    _stub_operator_surfaces(monkeypatch)

    summary = _summarize_personal_readiness_payload(
        {
            "status": "in_progress",
            "expected_latest_date": "2026-07-03",
            "latest_closed_date": "2026-07-03",
            "status_date": "2026-07-04",
            "validation": {
                "accepted_days": 4,
                "required_days": 20,
                "remaining_days": 16,
                "next_required_date": "2026-07-06",
                "latest_target_date": "2026-07-03",
                "blocking_issues": [],
                "accepted_dates": ["2026-07-03"],
            },
            "latest_evidence": {
                "status": "ok",
                "target_date": "2026-07-03",
            },
            "acceptance_gate": {
                "accepted": False,
                "projected_completion_date": "2026-07-27",
            },
            "schedule_expectation": {
                "due_status": "pending",
                "scheduled_for": "2026-07-06T16:10:00+08:00",
            },
            "monitor_gate": {
                "ok": True,
                "state": "wait_for_post_close",
                "next_check_after": "2026-07-06T16:10:00+08:00",
            },
            "next_action": {"action": "wait_for_post_close"},
            "scheduler_runtime": {"required": False, "status": "not_checked"},
            "current_decision_data": {"status": "blocked"},
        }
    )

    assert summary["daily_state"]["code"] == "latest_closed_day_accepted"
    assert summary["daily_state"]["severity"] == "ok"
    assert summary["window"]["accepted_days"] == 4
    assert summary["window"]["remaining_days"] == 16
    assert summary["schedule"]["next_check_after"] == "2026-07-06T16:10:00+08:00"
    assert summary["data_coverage"]["status"] == "ok"
    assert summary["operator_surfaces"]["ai_capability"]["mcp_tools"]["total"] == 365


def test_readiness_monitor_summary_marks_operator_attention(monkeypatch):
    _stub_data_coverage(monkeypatch)
    _stub_operator_surfaces(monkeypatch)

    summary = _summarize_personal_readiness_payload(
        {
            "status": "blocked",
            "expected_latest_date": "2026-07-03",
            "latest_closed_date": "2026-07-03",
            "validation": {
                "accepted_days": 3,
                "required_days": 20,
                "remaining_days": 17,
                "next_required_date": "2026-07-03",
                "blocking_issues": [
                    {"target_date": "2026-07-03", "reason": "evidence is missing"}
                ],
                "accepted_dates": [],
            },
            "latest_evidence": {"status": "missing", "target_date": None},
            "acceptance_gate": {"accepted": False},
            "schedule_expectation": {"due_status": "overdue"},
            "monitor_gate": {
                "ok": False,
                "state": "schedule_overdue",
                "reason": "scheduled_evidence_missing_after_grace",
                "command": "python manage.py show_personal_readiness_status --json",
            },
            "next_action": {"action": "inspect_missed_scheduled_run"},
            "scheduler_runtime": {"required": True, "status": "ok"},
            "current_decision_data": {"status": "ok"},
        }
    )

    assert summary["daily_state"]["code"] == "needs_attention"
    assert summary["daily_state"]["severity"] == "danger"
    assert "scheduled_evidence_missing_after_grace" in summary["daily_state"]["message"]
    assert summary["monitor_gate"]["ok"] is False


def test_strict_readiness_monitor_summary_uses_short_cache(monkeypatch):
    fake_cache = _FakeCache()
    calls = []
    _stub_data_coverage(monkeypatch)
    _stub_operator_surfaces(monkeypatch)

    def fake_build_personal_readiness_status(**kwargs):
        calls.append(kwargs)
        return _readiness_status_payload(accepted_days=len(calls))

    monkeypatch.setattr(service, "cache", fake_cache)
    monkeypatch.setattr(
        service,
        "build_personal_readiness_status",
        fake_build_personal_readiness_status,
    )
    monkeypatch.setattr(
        service,
        "resolve_default_readiness_target_date",
        lambda: "2026-07-03",
    )

    first = service.get_personal_readiness_monitor_summary(strict_runtime=True)
    second = service.get_personal_readiness_monitor_summary(strict_runtime=True)

    assert first["window"]["accepted_days"] == 1
    assert second["window"]["accepted_days"] == 1
    assert len(calls) == 1
    assert calls[0]["require_local_scheduler_runtime"] is True
    assert calls[0]["output_dir"] == Path(service.DEFAULT_OUTPUT_DIR)
    assert fake_cache.set_calls[0][2] == service.STRICT_RUNTIME_CACHE_TTL_SECONDS


def test_non_strict_readiness_monitor_summary_does_not_use_strict_cache(monkeypatch):
    fake_cache = _FakeCache()
    calls = []
    _stub_data_coverage(monkeypatch)
    _stub_operator_surfaces(monkeypatch)

    def fake_build_personal_readiness_status(**kwargs):
        calls.append(kwargs)
        return _readiness_status_payload(accepted_days=len(calls))

    monkeypatch.setattr(service, "cache", fake_cache)
    monkeypatch.setattr(
        service,
        "build_personal_readiness_status",
        fake_build_personal_readiness_status,
    )
    monkeypatch.setattr(
        service,
        "resolve_default_readiness_target_date",
        lambda: "2026-07-03",
    )

    first = service.get_personal_readiness_monitor_summary(strict_runtime=False)
    second = service.get_personal_readiness_monitor_summary(strict_runtime=False)

    assert first["window"]["accepted_days"] == 1
    assert second["window"]["accepted_days"] == 2
    assert len(calls) == 2
    assert fake_cache.set_calls == []


def test_raw_strict_readiness_monitor_summary_bypasses_cache(monkeypatch):
    fake_cache = _FakeCache()
    calls = []
    _stub_data_coverage(monkeypatch)
    _stub_operator_surfaces(monkeypatch)

    def fake_build_personal_readiness_status(**kwargs):
        calls.append(kwargs)
        return _readiness_status_payload(accepted_days=len(calls))

    monkeypatch.setattr(service, "cache", fake_cache)
    monkeypatch.setattr(
        service,
        "build_personal_readiness_status",
        fake_build_personal_readiness_status,
    )
    monkeypatch.setattr(
        service,
        "resolve_default_readiness_target_date",
        lambda: "2026-07-03",
    )

    first = service.get_personal_readiness_monitor_summary(
        strict_runtime=True,
        include_raw=True,
    )
    second = service.get_personal_readiness_monitor_summary(
        strict_runtime=True,
        include_raw=True,
    )

    assert first["window"]["accepted_days"] == 1
    assert second["window"]["accepted_days"] == 2
    assert "raw" in first
    assert len(calls) == 2
    assert fake_cache.set_calls == []


class _FakeCache:
    def __init__(self):
        self.values = {}
        self.set_calls = []

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, timeout=None):
        self.values[key] = value
        self.set_calls.append((key, value, timeout))


def _stub_data_coverage(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_active_stock_fact_coverage_payload",
        lambda: {
            "status": "ok",
            "universe": "active_stock",
            "asset_count": 304,
            "universe_quality": {
                "status": "ok",
                "minimum_active_a_share_count": 4000,
                "minimum_star_market_count": 200,
                "minimum_bse_count": 50,
                "exchange_counts": {"SSE": 2200, "SZSE": 3000, "BSE": 200},
                "board_counts": {
                    "star_market": 580,
                    "chinext": 1400,
                    "bse": 200,
                    "sh_main": 1600,
                    "sz_main": 1700,
                },
                "issues": [],
            },
            "domains": {
                "price": {
                    "covered_count": 304,
                    "missing_count": 0,
                    "latest_date": "2026-07-03",
                    "status": "ok",
                },
                "valuation": {
                    "covered_count": 304,
                    "missing_count": 0,
                    "latest_date": "2026-07-03",
                    "status": "ok",
                },
                "financial": {
                    "covered_count": 304,
                    "missing_count": 0,
                    "latest_date": "2026-03-31",
                    "status": "ok",
                },
            },
        },
    )


def _stub_operator_surfaces(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_ai_capability_surface_status_payload",
        lambda: {
            "status": "ok",
            "catalog": {"total": 510, "enabled": 480, "disabled": 30},
            "mcp_tools": {
                "total": 365,
                "routing_enabled": 340,
                "terminal_enabled": 330,
                "chat_enabled": 320,
                "agent_enabled": 340,
                "requires_confirmation": 45,
                "latest_sync_at": "2026-07-04T08:00:00+00:00",
                "status": "ok",
            },
            "terminal_capabilities": {
                "total": 18,
                "routing_enabled": 17,
                "terminal_enabled": 18,
                "chat_enabled": 18,
                "agent_enabled": 18,
                "requires_confirmation": 2,
                "latest_sync_at": "2026-07-04T08:00:00+00:00",
                "status": "ok",
            },
        },
    )
    monkeypatch.setattr(
        service,
        "get_terminal_surface_status_payload",
        lambda: {
            "status": "ok",
            "terminal_commands": {
                "active": 18,
                "terminal_enabled": 18,
                "requires_mcp": 6,
                "api_type": 14,
                "prompt_type": 4,
                "status": "ok",
            },
            "tui_metadata": {
                "status": "ok",
                "version": "2026.07",
                "schema_version": "tui-metadata.v3",
                "modules": 12,
                "screens": 37,
                "actions": 180,
                "default_screen": "command-center.overview",
                "coverage_summary": {},
            },
        },
    )


def _readiness_status_payload(*, accepted_days: int) -> dict:
    return {
        "status": "in_progress",
        "expected_latest_date": "2026-07-03",
        "latest_closed_date": "2026-07-03",
        "status_date": "2026-07-04",
        "validation": {
            "accepted_days": accepted_days,
            "required_days": 20,
            "remaining_days": 20 - accepted_days,
            "next_required_date": "2026-07-06",
            "latest_target_date": "2026-07-03",
            "blocking_issues": [],
            "accepted_dates": ["2026-07-03"],
        },
        "latest_evidence": {
            "status": "ok",
            "target_date": "2026-07-03",
        },
        "acceptance_gate": {
            "accepted": False,
            "projected_completion_date": "2026-07-27",
        },
        "schedule_expectation": {
            "due_status": "pending",
            "scheduled_for": "2026-07-06T16:10:00+08:00",
        },
        "monitor_gate": {
            "ok": True,
            "state": "wait_for_post_close",
            "next_check_after": "2026-07-06T16:10:00+08:00",
        },
        "next_action": {"action": "wait_for_post_close"},
        "scheduler_runtime": {
            "required": True,
            "status": "ok",
            "worker_process_count": 2,
            "beat_process_count": 1,
        },
        "current_decision_data": {"status": "blocked"},
    }
