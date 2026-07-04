"""UI-facing personal readiness monitor summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.task_monitor.management.commands.run_personal_readiness_daily import (
    resolve_default_readiness_target_date,
)
from apps.task_monitor.management.commands.show_personal_readiness_status import (
    DEFAULT_CALENDAR_SOURCE,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_REQUIRED_DAYS,
    build_personal_readiness_status,
)


def get_personal_readiness_monitor_summary(
    *,
    strict_runtime: bool = False,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Return the operator-facing daily readiness monitor payload."""

    payload = build_personal_readiness_status(
        output_dir=Path(DEFAULT_OUTPUT_DIR),
        required_days=DEFAULT_REQUIRED_DAYS,
        calendar_source=DEFAULT_CALENDAR_SOURCE,
        expected_latest_date=resolve_default_readiness_target_date(),
        require_local_scheduler_runtime=strict_runtime,
        include_current_macro_context=True,
        include_current_decision_data=True,
    )
    summary = _summarize_personal_readiness_payload(payload)
    if include_raw:
        summary["raw"] = payload
    return summary


def get_personal_readiness_monitor_placeholder() -> dict[str, Any]:
    """Return a lightweight placeholder for initial page rendering."""

    return {
        "status": "loading",
        "daily_state": {
            "code": "loading",
            "severity": "neutral",
            "title": "正在读取验收状态",
            "message": "页面加载后会读取最新 readiness monitor。",
        },
        "monitor_gate": {
            "ok": False,
            "state": "loading",
            "reason": None,
            "next_action": None,
            "next_check_after": None,
            "command": None,
        },
        "window": {
            "accepted": False,
            "accepted_days": 0,
            "required_days": DEFAULT_REQUIRED_DAYS,
            "remaining_days": DEFAULT_REQUIRED_DAYS,
            "latest_target_date": None,
            "next_required_date": None,
            "next_required_reason": None,
            "projected_completion_date": None,
            "projected_scheduler_completion_date": None,
        },
        "today": {
            "status_date": None,
            "latest_closed_date": None,
            "expected_latest_date": None,
            "latest_evidence_status": None,
            "latest_evidence_target_date": None,
            "latest_target_date": None,
        },
        "schedule": {
            "due_status": None,
            "scheduled_for": None,
            "grace_deadline": None,
            "next_check_after": None,
        },
        "next_action": {
            "action": None,
            "reason": None,
            "target_date": None,
            "command": None,
        },
        "scheduler_runtime": {
            "required": False,
            "status": "not_checked",
            "worker_process_count": None,
            "beat_process_count": None,
            "responsive_worker_count": None,
            "missing_queues": [],
            "missing_registered_tasks": [],
        },
        "decision_data": {
            "status": None,
            "readiness_status": None,
            "must_not_use_for_decision": False,
            "blocked_reasons": [],
        },
        "blocking_issues": [],
        "accepted_dates": [],
    }


def _summarize_personal_readiness_payload(payload: dict[str, Any]) -> dict[str, Any]:
    validation = dict(payload.get("validation") or {})
    monitor_gate = dict(payload.get("monitor_gate") or {})
    latest_evidence = dict(payload.get("latest_evidence") or {})
    acceptance_gate = dict(payload.get("acceptance_gate") or {})
    schedule_expectation = dict(payload.get("schedule_expectation") or {})
    next_action = dict(payload.get("next_action") or {})
    scheduler_runtime = dict(payload.get("scheduler_runtime") or {})
    current_decision_data = dict(payload.get("current_decision_data") or {})
    latest_target_date = str(
        latest_evidence.get("target_date")
        or validation.get("latest_target_date")
        or payload.get("expected_latest_date")
        or ""
    )

    daily_state = _classify_daily_state(
        payload=payload,
        validation=validation,
        monitor_gate=monitor_gate,
        latest_evidence=latest_evidence,
        acceptance_gate=acceptance_gate,
        schedule_expectation=schedule_expectation,
        next_action=next_action,
    )

    return {
        "status": payload.get("status"),
        "daily_state": daily_state,
        "monitor_gate": {
            "ok": bool(monitor_gate.get("ok")),
            "state": monitor_gate.get("state"),
            "reason": monitor_gate.get("reason"),
            "next_action": monitor_gate.get("next_action"),
            "next_check_after": monitor_gate.get("next_check_after"),
            "command": monitor_gate.get("command"),
        },
        "window": {
            "accepted": bool(acceptance_gate.get("accepted")),
            "accepted_days": validation.get("accepted_days"),
            "required_days": validation.get("required_days"),
            "remaining_days": validation.get("remaining_days"),
            "latest_target_date": validation.get("latest_target_date"),
            "next_required_date": validation.get("next_required_date"),
            "next_required_reason": validation.get("next_required_reason"),
            "projected_completion_date": acceptance_gate.get("projected_completion_date"),
            "projected_scheduler_completion_date": acceptance_gate.get(
                "projected_scheduler_completion_date"
            ),
        },
        "today": {
            "status_date": payload.get("status_date"),
            "latest_closed_date": payload.get("latest_closed_date"),
            "expected_latest_date": payload.get("expected_latest_date"),
            "latest_evidence_status": latest_evidence.get("status"),
            "latest_evidence_target_date": latest_evidence.get("target_date"),
            "latest_target_date": latest_target_date,
        },
        "schedule": {
            "due_status": schedule_expectation.get("due_status"),
            "scheduled_for": schedule_expectation.get("scheduled_for"),
            "grace_deadline": schedule_expectation.get("grace_deadline"),
            "next_check_after": monitor_gate.get("next_check_after"),
        },
        "next_action": {
            "action": next_action.get("action"),
            "reason": next_action.get("reason"),
            "target_date": next_action.get("target_date"),
            "command": next_action.get("command"),
        },
        "scheduler_runtime": {
            "required": bool(scheduler_runtime.get("required")),
            "status": scheduler_runtime.get("status"),
            "worker_process_count": scheduler_runtime.get("worker_process_count"),
            "beat_process_count": scheduler_runtime.get("beat_process_count"),
            "responsive_worker_count": scheduler_runtime.get("responsive_worker_count"),
            "missing_queues": list(scheduler_runtime.get("missing_queues") or []),
            "missing_registered_tasks": list(
                scheduler_runtime.get("missing_registered_tasks") or []
            ),
        },
        "decision_data": {
            "status": current_decision_data.get("status"),
            "readiness_status": current_decision_data.get("readiness_status"),
            "must_not_use_for_decision": bool(
                current_decision_data.get("must_not_use_for_decision")
            ),
            "blocked_reasons": list(current_decision_data.get("blocked_reasons") or []),
        },
        "blocking_issues": list(validation.get("blocking_issues") or []),
        "accepted_dates": list(validation.get("accepted_dates") or []),
    }


def _classify_daily_state(
    *,
    payload: dict[str, Any],
    validation: dict[str, Any],
    monitor_gate: dict[str, Any],
    latest_evidence: dict[str, Any],
    acceptance_gate: dict[str, Any],
    schedule_expectation: dict[str, Any],
    next_action: dict[str, Any],
) -> dict[str, Any]:
    if acceptance_gate.get("accepted"):
        return {
            "code": "window_accepted",
            "severity": "ok",
            "title": "20 日验收窗口已完成",
            "message": "连续运行证据窗口已经满足正式验收要求。",
        }

    if not monitor_gate.get("ok"):
        return {
            "code": "needs_attention",
            "severity": "danger",
            "title": "需要处理",
            "message": _build_attention_message(
                monitor_gate=monitor_gate,
                next_action=next_action,
            ),
        }

    latest_evidence_target = latest_evidence.get("target_date")
    expected_latest_date = payload.get("expected_latest_date")
    next_required_date = validation.get("next_required_date")
    latest_closed_date = payload.get("latest_closed_date")

    if (
        latest_evidence.get("status") == "ok"
        and latest_evidence_target == expected_latest_date
        and next_required_date
        and latest_closed_date
        and str(next_required_date) > str(latest_closed_date)
    ):
        return {
            "code": "latest_closed_day_accepted",
            "severity": "ok",
            "title": "最新收盘日已验收",
            "message": "当前最新已收盘交易日已有有效证据，等待下一交易日收盘。",
        }

    action = str(next_action.get("action") or "")
    due_status = str(schedule_expectation.get("due_status") or "")
    if action == "wait_for_post_close":
        return {
            "code": "waiting_post_close",
            "severity": "neutral",
            "title": "等待收盘",
            "message": "下一个验收目标交易日尚未收盘。",
        }
    if action == "wait_for_scheduled_run" or due_status in {"pending", "grace_period"}:
        return {
            "code": "waiting_scheduled_run",
            "severity": "warn",
            "title": "等待自动证据",
            "message": "目标交易日已进入调度窗口，等待 Celery beat 生成证据。",
        }
    return {
        "code": "monitor_ok",
        "severity": "ok",
        "title": "监视器正常",
        "message": "当前没有需要人工处理的 readiness 问题。",
    }


def _build_attention_message(
    *,
    monitor_gate: dict[str, Any],
    next_action: dict[str, Any],
) -> str:
    command = monitor_gate.get("command") or next_action.get("command")
    reason = monitor_gate.get("reason") or next_action.get("reason") or "unknown"
    if command:
        return f"{reason}: {command}"
    return str(reason)
