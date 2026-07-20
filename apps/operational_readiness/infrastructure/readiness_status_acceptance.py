"""Acceptance and schedule helpers for personal readiness status."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.operational_readiness.application import status_services
from apps.operational_readiness.infrastructure import (
    readiness_persistence_status,
    scheduler_status_utils,
)

MIN_POST_CLOSE_SCHEDULE_MINUTES = 15 * 60 + 30
EXPECTED_SCHEDULE_TIMEZONE = "Asia/Shanghai"
EXPECTED_SCHEDULE_DAY_OF_WEEK = "mon-fri"
DEFAULT_SCHEDULE_OVERDUE_GRACE_MINUTES = 30
QUOTE_PRE_READINESS_OVERDUE_GRACE_MINUTES = 15
STRICT_MONITOR_COMMAND = (
    "python manage.py show_personal_readiness_status --json "
    "--strict-monitor --require-local-scheduler-runtime"
)
_parse_single_crontab_number = scheduler_status_utils.parse_single_crontab_number


def _get_scheduler_issue(*, scheduler: dict[str, Any]) -> str | None:
    if scheduler.get("status") == "ok":
        return None
    safety_issues = (scheduler.get("safety") or {}).get("issues") or []
    if safety_issues:
        return str(safety_issues[0].get("code") or "scheduler_warning")
    status = str(scheduler.get("status") or "unknown")
    return f"scheduler_{status}"


def _build_acceptance_gate(
    *,
    validation: dict[str, Any],
    scheduler: dict[str, Any],
    auto_advisor_weekly_scheduler: dict[str, Any],
    quote_pre_readiness_scheduler: dict[str, Any],
    scheduler_runtime: dict[str, Any],
    latest_formal_evidence: dict[str, Any],
    post_evidence_persistence: dict[str, Any] | None,
    next_action: dict[str, Any],
    schedule_expectation: dict[str, Any],
    status_date: date,
    scheduler_activity: dict[str, Any],
) -> dict[str, Any]:
    issue = _resolve_acceptance_gate_issue(
        validation=validation,
        scheduler=scheduler,
        auto_advisor_weekly_scheduler=auto_advisor_weekly_scheduler,
        quote_pre_readiness_scheduler=quote_pre_readiness_scheduler,
        scheduler_runtime=scheduler_runtime,
        scheduler_activity=scheduler_activity,
    )
    projected_completion_date = _parse_optional_iso_date(
        validation.get("projected_completion_date")
    )
    projected_scheduler_completion_date = _parse_optional_iso_date(
        validation.get("projected_scheduler_completion_date")
    )
    requirements = _build_acceptance_requirements(
        validation=validation,
        scheduler=scheduler,
        auto_advisor_weekly_scheduler=auto_advisor_weekly_scheduler,
        quote_pre_readiness_scheduler=quote_pre_readiness_scheduler,
        scheduler_runtime=scheduler_runtime,
        scheduler_activity=scheduler_activity,
        post_evidence_persistence=post_evidence_persistence,
    )
    failed_requirements = _build_failed_acceptance_requirements(requirements=requirements)
    operator_actions = _build_acceptance_operator_actions(
        failed_requirements=failed_requirements,
        requirements=requirements,
        next_action=next_action,
        schedule_expectation=schedule_expectation,
        scheduler_activity=scheduler_activity,
        post_evidence_persistence=post_evidence_persistence,
    )
    return {
        "status": _rollup_status(
            validation=validation,
            scheduler=scheduler,
            auto_advisor_weekly_scheduler=auto_advisor_weekly_scheduler,
            quote_pre_readiness_scheduler=quote_pre_readiness_scheduler,
            scheduler_runtime=scheduler_runtime,
            scheduler_activity=scheduler_activity,
        ),
        "accepted": all(
            isinstance(payload, dict) and payload.get("ok") is True
            for payload in requirements.values()
        ),
        "requirements": requirements,
        "failed_requirements": failed_requirements,
        "operator_actions": operator_actions,
        "required_days": validation.get("required_days"),
        "accepted_days": validation.get("accepted_days"),
        "remaining_days": validation.get("remaining_days"),
        "latest_formal_date": latest_formal_evidence.get("target_date"),
        "latest_formal_evidence": latest_formal_evidence.get("formal_evidence"),
        "latest_formal_acceptance_candidate": latest_formal_evidence.get("acceptance_candidate"),
        "latest_formal_evidence_mode": latest_formal_evidence.get("evidence_mode"),
        "accepted_evidence_manifest": validation.get("accepted_evidence_manifest"),
        "accepted_evidence_quality": validation.get("accepted_evidence_quality"),
        "evidence_quality": validation.get("evidence_quality"),
        "next_required_date": validation.get("next_required_date"),
        "next_required_reason": validation.get("next_required_reason"),
        "projected_completion_date": validation.get("projected_completion_date"),
        "projected_remaining_calendar_days": validation.get("projected_remaining_calendar_days"),
        "projected_remaining_calendar_days_from_today": (
            max((projected_completion_date - status_date).days, 0)
            if projected_completion_date is not None
            else None
        ),
        "scheduler_clean_suffix_days": validation.get("scheduler_clean_suffix_days"),
        "scheduler_clean_remaining_days": validation.get("scheduler_clean_remaining_days"),
        "projected_scheduler_completion_date": validation.get(
            "projected_scheduler_completion_date"
        ),
        "projected_scheduler_remaining_calendar_days": validation.get(
            "projected_scheduler_remaining_calendar_days"
        ),
        "projected_scheduler_remaining_calendar_days_from_today": (
            max((projected_scheduler_completion_date - status_date).days, 0)
            if projected_scheduler_completion_date is not None
            else None
        ),
        "next_action": next_action.get("action"),
        "schedule_expectation": schedule_expectation,
        "scheduler_activity": scheduler_activity,
        "can_generate_next_evidence": next_action.get("action") == "run_daily",
        "issue": issue,
    }


def _build_acceptance_operator_actions(
    *,
    failed_requirements: list[dict[str, Any]],
    requirements: dict[str, Any],
    next_action: dict[str, Any],
    schedule_expectation: dict[str, Any],
    scheduler_activity: dict[str, Any],
    post_evidence_persistence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    failed_names = {str(item.get("name")) for item in failed_requirements}

    if "evidence_window" in failed_names:
        action = str(next_action.get("action") or "")
        actions.append(
            {
                "requirement": "evidence_window",
                "action": action or "review_status",
                "reason": next_action.get("reason"),
                "target_date": next_action.get("target_date"),
                "command": next_action.get("command"),
                "next_check_after": _resolve_operator_next_check_after(
                    action=action,
                    schedule_expectation=schedule_expectation,
                ),
            }
        )

    if "scheduler_safety" in failed_names:
        actions.append(
            {
                "requirement": "scheduler_safety",
                "action": "fix_scheduler",
                "reason": "scheduler_safety_not_ok",
                "command": "python manage.py setup_personal_readiness_daily",
            }
        )

    if "scheduler_activity" in failed_names:
        actions.append(
            _build_scheduler_activity_operator_action(scheduler_activity=scheduler_activity)
        )

    if "qlib_formal_evidence" in failed_names:
        actions.append(
            {
                "requirement": "qlib_formal_evidence",
                "action": "inspect_qlib_evidence",
                "reason": "formal_qlib_evidence_incomplete",
                "command": "python manage.py validate_personal_readiness_window --json",
            }
        )

    if "workspace_core_formal_evidence" in failed_names:
        actions.append(
            {
                "requirement": "workspace_core_formal_evidence",
                "action": "inspect_workspace_core_evidence",
                "reason": "formal_workspace_core_evidence_incomplete",
                "command": "python manage.py validate_personal_readiness_window --json",
            }
        )

    if "alpha_workspace_formal_evidence" in failed_names:
        actions.append(
            {
                "requirement": "alpha_workspace_formal_evidence",
                "action": "inspect_alpha_workspace_evidence",
                "reason": "formal_alpha_workspace_evidence_incomplete",
                "command": "python manage.py validate_personal_readiness_window --json",
            }
        )

    if "decision_data_formal_evidence" in failed_names:
        actions.append(
            {
                "requirement": "decision_data_formal_evidence",
                "action": "inspect_decision_data_evidence",
                "reason": "formal_decision_data_evidence_incomplete",
                "command": "python manage.py validate_personal_readiness_window --json",
            }
        )

    if "decision_quote_freshness_formal_evidence" in failed_names:
        actions.append(
            {
                "requirement": "decision_quote_freshness_formal_evidence",
                "action": "inspect_decision_quote_freshness_evidence",
                "reason": "formal_decision_quote_freshness_evidence_incomplete",
                "command": "python manage.py validate_personal_readiness_window --json",
            }
        )

    if "risk_center_formal_evidence" in failed_names:
        actions.append(
            {
                "requirement": "risk_center_formal_evidence",
                "action": "inspect_risk_center_evidence",
                "reason": "formal_risk_center_evidence_incomplete",
                "command": "python manage.py validate_personal_readiness_window --json",
            }
        )
    else:
        risk_advisory = status_services.build_risk_center_persistence_advisory_action(
            requirement=dict(requirements.get("risk_center_formal_evidence") or {})
        )
        if risk_advisory is not None:
            actions.append(
                readiness_persistence_status.apply_risk_advisory_persistence_status(
                    action=risk_advisory,
                    post_evidence_persistence=post_evidence_persistence,
                )
            )

    if "auto_advisor_weekly_scheduler" in failed_names:
        actions.append(
            {
                "requirement": "auto_advisor_weekly_scheduler",
                "action": "fix_auto_advisor_weekly_scheduler",
                "reason": "auto_advisor_weekly_scheduler_not_ok",
                "command": "python manage.py setup_auto_advisor_weekly_report",
            }
        )

    if "quote_pre_readiness_scheduler" in failed_names:
        actions.append(
            {
                "requirement": "quote_pre_readiness_scheduler",
                "action": "fix_quote_pre_readiness_scheduler",
                "reason": "quote_pre_readiness_scheduler_not_ok",
                "command": "python manage.py setup_decision_quote_refresh",
            }
        )

    if "quote_pre_readiness_activity" in failed_names:
        activity_requirement = dict(requirements.get("quote_pre_readiness_activity") or {})
        actions.append(
            {
                "requirement": "quote_pre_readiness_activity",
                "action": "verify_quote_pre_readiness_scheduler_run",
                "reason": activity_requirement.get("status")
                or "quote_pre_readiness_activity_not_ok",
                "command": "python manage.py show_personal_readiness_status --json",
            }
        )

    if "scheduler_runtime" in failed_names:
        runtime_requirement = dict(requirements.get("scheduler_runtime") or {})
        remediation_commands = list(runtime_requirement.get("remediation_commands") or [])
        actions.append(
            {
                "requirement": "scheduler_runtime",
                "action": "restore_local_scheduler_runtime",
                "reason": runtime_requirement.get("reason") or "local_scheduler_runtime_not_ok",
                "command": (
                    remediation_commands[0] if remediation_commands else STRICT_MONITOR_COMMAND
                ),
            }
        )

    if "auto_advisor_weekly_activity" in failed_names:
        actions.append(
            {
                "requirement": "auto_advisor_weekly_activity",
                "action": "verify_auto_advisor_weekly_scheduler_run",
                "reason": "weekly_scheduler_run_history_missing",
                "command": "python manage.py show_personal_readiness_status --json",
            }
        )

    if "auto_advisor_weekly_persistence" in failed_names:
        actions.append(
            {
                "requirement": "auto_advisor_weekly_persistence",
                "action": "verify_auto_advisor_weekly_outputs",
                "reason": "weekly_report_persistence_proof_missing",
                "command": (
                    "python manage.py collect_personal_readiness_evidence "
                    "--include-weekly-advisor --no-file --json"
                ),
            }
        )

    return actions


def _build_scheduler_activity_operator_action(
    *,
    scheduler_activity: dict[str, Any],
) -> dict[str, Any]:
    reason = str(scheduler_activity.get("status") or "scheduler_activity_not_ok")
    if reason in {
        "manual_formal_evidence_in_window",
        "legacy_evidence_in_accepted_window",
        "insufficient_scheduler_evidence",
        "insufficient_scheduler_task_provenance",
        "duplicate_scheduler_task_ids",
    }:
        return {
            "requirement": "scheduler_activity",
            "action": "inspect_scheduler_evidence_provenance",
            "reason": reason,
            "command": "python manage.py validate_personal_readiness_window --json",
        }
    return {
        "requirement": "scheduler_activity",
        "action": "verify_scheduler_dispatch_history",
        "reason": reason,
        "command": "python manage.py show_personal_readiness_status --json",
    }


def _resolve_operator_next_check_after(
    *,
    action: str,
    schedule_expectation: dict[str, Any],
) -> str | None:
    if action not in {"wait_for_post_close", "wait_for_scheduled_run"}:
        return None
    due_status = str(schedule_expectation.get("due_status") or "")
    if due_status in {"pending", "due_now"}:
        return schedule_expectation.get("scheduled_for")
    return schedule_expectation.get("grace_deadline")


def _build_failed_acceptance_requirements(
    *,
    requirements: dict[str, Any],
) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for name, payload in requirements.items():
        if not isinstance(payload, dict) or payload.get("ok") is True:
            continue
        failed.append(
            {
                "name": name,
                "status": payload.get("status"),
                "details": {
                    key: value for key, value in payload.items() if key not in {"ok", "status"}
                },
            }
        )
    return failed


def _build_acceptance_requirements(
    *,
    validation: dict[str, Any],
    scheduler: dict[str, Any],
    auto_advisor_weekly_scheduler: dict[str, Any],
    quote_pre_readiness_scheduler: dict[str, Any],
    scheduler_runtime: dict[str, Any],
    scheduler_activity: dict[str, Any],
    post_evidence_persistence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "evidence_window": {
            "ok": validation.get("status") == "accepted",
            "status": validation.get("status"),
            "accepted_days": validation.get("accepted_days"),
            "required_days": validation.get("required_days"),
            "remaining_days": validation.get("remaining_days"),
        },
        "scheduler_safety": {
            "ok": scheduler.get("status") == "ok",
            "status": scheduler.get("status"),
            "issue_count": len((scheduler.get("safety") or {}).get("issues") or []),
        },
        "scheduler_activity": {
            "ok": scheduler_activity.get("ok") is True,
            "status": scheduler_activity.get("status"),
            "observed_dispatches": scheduler_activity.get("observed_dispatches"),
            "required_dispatches": scheduler_activity.get("required_dispatches"),
            "scheduler_trigger_record_count": scheduler_activity.get(
                "scheduler_trigger_record_count"
            ),
            "scheduler_task_provenance_record_count": scheduler_activity.get(
                "scheduler_task_provenance_record_count"
            ),
            "unique_scheduler_task_id_count": scheduler_activity.get(
                "unique_scheduler_task_id_count"
            ),
            "duplicate_scheduler_task_id_count": scheduler_activity.get(
                "duplicate_scheduler_task_id_count"
            ),
            "missing_scheduler_task_provenance_record_count": scheduler_activity.get(
                "missing_scheduler_task_provenance_record_count"
            ),
            "manual_trigger_record_count": scheduler_activity.get("manual_trigger_record_count"),
            "legacy_record_count": scheduler_activity.get("legacy_record_count"),
        },
        "qlib_formal_evidence": _build_qlib_formal_evidence_requirement(validation=validation),
        "workspace_core_formal_evidence": _build_workspace_core_formal_evidence_requirement(
            validation=validation
        ),
        "alpha_workspace_formal_evidence": _build_alpha_workspace_formal_evidence_requirement(
            validation=validation
        ),
        "decision_data_formal_evidence": _build_decision_data_formal_evidence_requirement(
            validation=validation
        ),
        "decision_quote_freshness_formal_evidence": (
            _build_decision_quote_freshness_formal_evidence_requirement(validation=validation)
        ),
        "risk_center_formal_evidence": status_services.build_risk_center_formal_evidence_requirement(
            validation=validation
        ),
        "auto_advisor_weekly_scheduler": {
            "ok": auto_advisor_weekly_scheduler.get("status") == "ok",
            "status": auto_advisor_weekly_scheduler.get("status"),
            "issue_count": len(
                (auto_advisor_weekly_scheduler.get("safety") or {}).get("issues") or []
            ),
            "enabled": auto_advisor_weekly_scheduler.get("enabled"),
            "task": auto_advisor_weekly_scheduler.get("task"),
            "day_of_week": (
                (auto_advisor_weekly_scheduler.get("schedule") or {}).get("day_of_week")
            ),
            "hour": (auto_advisor_weekly_scheduler.get("schedule") or {}).get("hour"),
            "minute": (auto_advisor_weekly_scheduler.get("schedule") or {}).get("minute"),
            "last_run_at": (
                (auto_advisor_weekly_scheduler.get("run_metadata") or {}).get("last_run_at")
            ),
            "total_run_count": (
                (auto_advisor_weekly_scheduler.get("run_metadata") or {}).get("total_run_count")
            ),
        },
        "quote_pre_readiness_scheduler": _build_quote_pre_readiness_scheduler_requirement(
            quote_pre_readiness_scheduler=quote_pre_readiness_scheduler
        ),
        "quote_pre_readiness_activity": _build_quote_pre_readiness_activity_requirement(
            validation=validation,
            quote_pre_readiness_scheduler=quote_pre_readiness_scheduler,
        ),
        "scheduler_runtime": _build_scheduler_runtime_requirement(
            scheduler_runtime=scheduler_runtime
        ),
        "auto_advisor_weekly_activity": _build_auto_advisor_weekly_activity_requirement(
            validation=validation,
            auto_advisor_weekly_scheduler=auto_advisor_weekly_scheduler,
        ),
        "auto_advisor_weekly_persistence": _build_auto_advisor_weekly_persistence_requirement(
            validation=validation,
            post_evidence_persistence=post_evidence_persistence,
        ),
    }


def _build_scheduler_runtime_requirement(
    *,
    scheduler_runtime: dict[str, Any],
) -> dict[str, Any]:
    required = bool(scheduler_runtime.get("required"))
    status = str(scheduler_runtime.get("status") or "unknown")
    issues = list(scheduler_runtime.get("issues") or [])
    first_issue = issues[0] if issues else {}
    return {
        "ok": (not required) or status == "ok",
        "status": status if required else "not_required",
        "required": required,
        "issue_count": len(issues),
        "reason": first_issue.get("code") if isinstance(first_issue, dict) else None,
        "worker_process_count": scheduler_runtime.get("worker_process_count"),
        "beat_process_count": scheduler_runtime.get("beat_process_count"),
        "responsive_worker_count": scheduler_runtime.get("responsive_worker_count"),
        "covered_queues": scheduler_runtime.get("covered_queues"),
        "missing_queues": scheduler_runtime.get("missing_queues"),
        "registered_tasks_status": scheduler_runtime.get("registered_tasks_status"),
        "missing_registered_tasks": scheduler_runtime.get("missing_registered_tasks"),
        "remediation_commands": list(scheduler_runtime.get("remediation_commands") or []),
    }


def _build_quote_pre_readiness_scheduler_requirement(
    *,
    quote_pre_readiness_scheduler: dict[str, Any],
) -> dict[str, Any]:
    schedule = dict(quote_pre_readiness_scheduler.get("schedule") or {})
    run_metadata = dict(quote_pre_readiness_scheduler.get("run_metadata") or {})
    safety = dict(quote_pre_readiness_scheduler.get("safety") or {})
    schedule_expectation = dict(quote_pre_readiness_scheduler.get("schedule_expectation") or {})
    return {
        "ok": quote_pre_readiness_scheduler.get("status") == "ok",
        "status": quote_pre_readiness_scheduler.get("status"),
        "issue_count": len(safety.get("issues") or []),
        "enabled": quote_pre_readiness_scheduler.get("enabled"),
        "task": quote_pre_readiness_scheduler.get("task"),
        "day_of_week": schedule.get("day_of_week"),
        "hour": schedule.get("hour"),
        "minute": schedule.get("minute"),
        "last_run_at": run_metadata.get("last_run_at"),
        "total_run_count": run_metadata.get("total_run_count"),
        "due_status": schedule_expectation.get("due_status"),
        "scheduled_for": schedule_expectation.get("scheduled_for"),
        "grace_deadline": schedule_expectation.get("grace_deadline"),
        "quote_max_age_hours": (
            (quote_pre_readiness_scheduler.get("effective_kwargs") or {}).get("quote_max_age_hours")
        ),
    }


def _build_quote_pre_readiness_activity_requirement(
    *,
    validation: dict[str, Any],
    quote_pre_readiness_scheduler: dict[str, Any],
) -> dict[str, Any]:
    quality = dict(validation.get("accepted_evidence_quality") or {})
    evidence_quality_available = "formal_quote_pre_readiness_scheduler_ok_record_count" in quality
    formal_record_count = int(quality.get("formal_record_count") or 0)
    evidence_ok_count = int(
        quality.get("formal_quote_pre_readiness_scheduler_ok_record_count") or 0
    )
    evidence_missing_count = int(
        quality.get("formal_quote_pre_readiness_scheduler_missing_record_count") or 0
    )
    evidence_blocked_count = int(
        quality.get("formal_quote_pre_readiness_scheduler_blocked_record_count") or 0
    )
    run_metadata = dict(quote_pre_readiness_scheduler.get("run_metadata") or {})
    total_run_count = _parse_optional_positive_int(run_metadata.get("total_run_count"))
    last_run_at = run_metadata.get("last_run_at")
    latest_run_date = _parse_optional_iso_datetime_date(last_run_at)
    window_start_date, window_end_date = _resolve_accepted_window_dates(validation=validation)
    required_dispatches = int(validation.get("required_days") or 0)
    payload = {
        "ok": True,
        "status": "pending_window",
        "required_when": "evidence_window_accepted",
        "required_dispatches": None,
        "observed_dispatches": total_run_count,
        "last_run_at": last_run_at,
        "latest_run_date": latest_run_date.isoformat() if latest_run_date else None,
        "window_start_date": window_start_date.isoformat() if window_start_date else None,
        "window_end_date": window_end_date.isoformat() if window_end_date else None,
        "evidence_quality_available": evidence_quality_available,
        "formal_quote_pre_readiness_scheduler_ok_record_count": evidence_ok_count,
        "formal_quote_pre_readiness_scheduler_missing_record_count": evidence_missing_count,
        "formal_quote_pre_readiness_scheduler_blocked_record_count": evidence_blocked_count,
    }
    if validation.get("status") != "accepted":
        return payload

    payload["required_dispatches"] = required_dispatches
    if evidence_quality_available and formal_record_count > 0:
        if evidence_ok_count >= required_dispatches:
            payload["status"] = "ok"
            return payload
        if evidence_missing_count > 0:
            payload["status"] = "missing_quote_pre_readiness_evidence"
            payload["ok"] = False
            return payload
        if evidence_blocked_count > 0:
            payload["status"] = "blocked_quote_pre_readiness_evidence"
            payload["ok"] = False
            return payload
        payload["status"] = "insufficient_quote_pre_readiness_evidence"
        payload["ok"] = False
        return payload

    if total_run_count is None or total_run_count < required_dispatches:
        payload["status"] = "insufficient_quote_pre_readiness_dispatch_history"
        payload["ok"] = False
        return payload
    if latest_run_date is None:
        payload["status"] = "missing_quote_pre_readiness_last_run_at"
        payload["ok"] = False
        return payload
    if window_end_date is not None and latest_run_date < window_end_date:
        payload["status"] = "stale_quote_pre_readiness_last_run_at"
        payload["ok"] = False
        return payload
    payload["status"] = "ok"
    return payload


def _build_auto_advisor_weekly_activity_requirement(
    *,
    validation: dict[str, Any],
    auto_advisor_weekly_scheduler: dict[str, Any],
) -> dict[str, Any]:
    run_metadata = dict(auto_advisor_weekly_scheduler.get("run_metadata") or {})
    total_run_count = _parse_optional_positive_int(run_metadata.get("total_run_count"))
    last_run_at = run_metadata.get("last_run_at")
    latest_run_date = _parse_optional_iso_datetime_date(last_run_at)
    window_start_date, window_end_date = _resolve_accepted_window_dates(validation=validation)
    expected_run_count = status_services.count_weekly_schedule_dates(
        start_date=window_start_date,
        end_date=window_end_date,
    )
    latest_expected_run_date = status_services.latest_weekly_schedule_date(
        start_date=window_start_date,
        end_date=window_end_date,
    )
    payload = {
        "ok": True,
        "status": "pending_window",
        "required_when": "evidence_window_accepted",
        "last_run_at": last_run_at,
        "latest_run_date": latest_run_date.isoformat() if latest_run_date else None,
        "latest_expected_run_date": (
            latest_expected_run_date.isoformat() if latest_expected_run_date else None
        ),
        "window_start_date": window_start_date.isoformat() if window_start_date else None,
        "window_end_date": window_end_date.isoformat() if window_end_date else None,
        "expected_run_count": expected_run_count,
        "total_run_count": run_metadata.get("total_run_count"),
    }
    if auto_advisor_weekly_scheduler.get("status") != "ok":
        payload["status"] = "blocked_by_scheduler"
        return payload
    if validation.get("status") != "accepted":
        return payload
    payload["status"] = (
        "ok"
        if total_run_count is not None
        and latest_run_date is not None
        and total_run_count >= expected_run_count
        and (window_start_date is None or latest_run_date >= window_start_date)
        and (latest_expected_run_date is None or latest_run_date >= latest_expected_run_date)
        else "missing"
    )
    payload["ok"] = payload["status"] == "ok"
    return payload


def _build_qlib_formal_evidence_requirement(
    *,
    validation: dict[str, Any],
) -> dict[str, Any]:
    quality = dict(validation.get("accepted_evidence_quality") or {})
    record_count = int(quality.get("formal_record_count") or 0)
    qlib_record_count = int(quality.get("formal_qlib_record_count") or 0)
    ok_record_count = int(quality.get("formal_qlib_ok_record_count") or 0)
    missing_record_count = int(quality.get("formal_qlib_missing_record_count") or 0)
    blocked_record_count = int(quality.get("formal_qlib_blocked_record_count") or 0)
    payload = {
        "ok": True,
        "status": "pending_window",
        "required_when": "evidence_window_accepted",
        "formal_record_count": record_count,
        "qlib_record_count": qlib_record_count,
        "ok_record_count": ok_record_count,
        "missing_record_count": missing_record_count,
        "blocked_record_count": blocked_record_count,
    }
    if validation.get("status") != "accepted":
        return payload
    payload["status"] = (
        "ok"
        if record_count > 0
        and qlib_record_count == record_count
        and ok_record_count == record_count
        and missing_record_count == 0
        and blocked_record_count == 0
        else "missing"
    )
    payload["ok"] = payload["status"] == "ok"
    return payload


def _build_decision_data_formal_evidence_requirement(
    *,
    validation: dict[str, Any],
) -> dict[str, Any]:
    quality = dict(validation.get("accepted_evidence_quality") or {})
    record_count = int(quality.get("formal_record_count") or 0)
    decision_record_count = int(quality.get("formal_decision_data_record_count") or 0)
    ok_record_count = int(quality.get("formal_decision_data_ok_record_count") or 0)
    missing_record_count = int(quality.get("formal_decision_data_missing_record_count") or 0)
    blocked_record_count = int(quality.get("formal_decision_data_blocked_record_count") or 0)
    payload = {
        "ok": True,
        "status": "pending_window",
        "required_when": "evidence_window_accepted",
        "formal_record_count": record_count,
        "decision_data_record_count": decision_record_count,
        "ok_record_count": ok_record_count,
        "missing_record_count": missing_record_count,
        "blocked_record_count": blocked_record_count,
    }
    if validation.get("status") != "accepted":
        return payload
    payload["status"] = (
        "ok"
        if record_count > 0
        and decision_record_count == record_count
        and ok_record_count == record_count
        and missing_record_count == 0
        and blocked_record_count == 0
        else "missing"
    )
    payload["ok"] = payload["status"] == "ok"
    return payload


def _build_decision_quote_freshness_formal_evidence_requirement(
    *,
    validation: dict[str, Any],
) -> dict[str, Any]:
    quality = dict(validation.get("accepted_evidence_quality") or {})
    record_count = int(quality.get("formal_record_count") or 0)
    quote_record_count = int(quality.get("formal_quote_freshness_record_count") or 0)
    ok_record_count = int(quality.get("formal_quote_freshness_ok_record_count") or 0)
    missing_record_count = int(quality.get("formal_quote_freshness_missing_record_count") or 0)
    stale_record_count = int(quality.get("formal_quote_freshness_stale_record_count") or 0)
    blocked_record_count = int(quality.get("formal_quote_freshness_blocked_record_count") or 0)
    payload = {
        "ok": True,
        "status": "pending_window",
        "required_when": "evidence_window_accepted",
        "formal_record_count": record_count,
        "quote_freshness_record_count": quote_record_count,
        "ok_record_count": ok_record_count,
        "missing_record_count": missing_record_count,
        "stale_record_count": stale_record_count,
        "blocked_record_count": blocked_record_count,
    }
    if validation.get("status") != "accepted":
        return payload
    decision_data = _build_decision_data_formal_evidence_requirement(validation=validation)
    if decision_data.get("ok") is not True:
        payload["status"] = "blocked_by_decision_data"
        return payload
    payload["status"] = (
        "ok"
        if record_count > 0
        and quote_record_count == record_count
        and ok_record_count == record_count
        and missing_record_count == 0
        and stale_record_count == 0
        and blocked_record_count == 0
        else "missing"
    )
    payload["ok"] = payload["status"] == "ok"
    return payload


def _build_alpha_workspace_formal_evidence_requirement(
    *,
    validation: dict[str, Any],
) -> dict[str, Any]:
    quality = dict(validation.get("accepted_evidence_quality") or {})
    record_count = int(quality.get("formal_record_count") or 0)
    alpha_record_count = int(quality.get("formal_alpha_workspace_record_count") or 0)
    ok_record_count = int(quality.get("formal_alpha_workspace_ok_record_count") or 0)
    missing_record_count = int(quality.get("formal_alpha_workspace_missing_record_count") or 0)
    payload = {
        "ok": True,
        "status": "pending_window",
        "required_when": "evidence_window_accepted",
        "formal_record_count": record_count,
        "alpha_workspace_record_count": alpha_record_count,
        "ok_record_count": ok_record_count,
        "missing_record_count": missing_record_count,
    }
    if validation.get("status") != "accepted":
        return payload
    payload["status"] = (
        "ok"
        if record_count > 0
        and alpha_record_count == record_count
        and ok_record_count == record_count
        and missing_record_count == 0
        else "missing"
    )
    payload["ok"] = payload["status"] == "ok"
    return payload


def _build_workspace_core_formal_evidence_requirement(
    *,
    validation: dict[str, Any],
) -> dict[str, Any]:
    quality = dict(validation.get("accepted_evidence_quality") or {})
    record_count = int(quality.get("formal_record_count") or 0)
    workspace_record_count = int(quality.get("formal_workspace_core_record_count") or 0)
    ok_record_count = int(quality.get("formal_workspace_core_ok_record_count") or 0)
    missing_record_count = int(quality.get("formal_workspace_core_missing_record_count") or 0)
    payload = {
        "ok": True,
        "status": "pending_window",
        "required_when": "evidence_window_accepted",
        "formal_record_count": record_count,
        "workspace_core_record_count": workspace_record_count,
        "ok_record_count": ok_record_count,
        "missing_record_count": missing_record_count,
    }
    if validation.get("status") != "accepted":
        return payload
    payload["status"] = (
        "ok"
        if record_count > 0
        and workspace_record_count == record_count
        and ok_record_count == record_count
        and missing_record_count == 0
        else "missing"
    )
    payload["ok"] = payload["status"] == "ok"
    return payload


def _build_auto_advisor_weekly_persistence_requirement(
    *,
    validation: dict[str, Any],
    post_evidence_persistence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    window_start_date, window_end_date = _resolve_accepted_window_dates(validation=validation)
    return readiness_persistence_status.build_weekly_advisory_persistence_requirement(
        validation=validation,
        expected_record_count=status_services.count_weekly_schedule_dates(
            start_date=window_start_date,
            end_date=window_end_date,
        ),
        post_evidence_persistence=post_evidence_persistence,
    )


def _parse_optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _resolve_status_date(*, schedule_expectation: dict[str, Any]) -> date:
    raw_now = schedule_expectation.get("now")
    if raw_now:
        try:
            return datetime.fromisoformat(str(raw_now)).date()
        except ValueError:
            pass
    return datetime.now(ZoneInfo(EXPECTED_SCHEDULE_TIMEZONE)).date()


def _parse_optional_iso_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_optional_iso_datetime_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _parse_optional_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _resolve_accepted_window_dates(
    *,
    validation: dict[str, Any],
) -> tuple[date | None, date | None]:
    quality = dict(validation.get("accepted_evidence_quality") or {})
    start_date = _parse_optional_iso_date(quality.get("start_date"))
    end_date = _parse_optional_iso_date(quality.get("end_date"))
    if start_date is not None or end_date is not None:
        return start_date, end_date

    dates: list[date] = []
    for record in validation.get("accepted_evidence") or []:
        if not isinstance(record, dict):
            continue
        target_date = _parse_optional_iso_date(record.get("target_date"))
        if target_date is not None:
            dates.append(target_date)
    return (min(dates), max(dates)) if dates else (None, None)


def _build_schedule_expectation(
    *,
    validation: dict[str, Any],
    scheduler: dict[str, Any],
    next_action: dict[str, Any],
    now: datetime | None = None,
    schedule_overdue_grace_minutes: int = DEFAULT_SCHEDULE_OVERDUE_GRACE_MINUTES,
) -> dict[str, Any]:
    target_text = next_action.get("target_date") or validation.get("next_required_date")
    if not target_text:
        return {
            "status": "not_applicable",
            "reason": "no_next_required_date",
            "target_date": None,
        }

    if scheduler.get("status") != "ok":
        return {
            "status": "unavailable",
            "reason": "scheduler_not_ok",
            "target_date": str(target_text),
        }

    schedule = dict(scheduler.get("schedule") or {})
    hour = _parse_single_crontab_number(str(schedule.get("hour") or ""))
    minute = _parse_single_crontab_number(str(schedule.get("minute") or ""))
    timezone_name = str(schedule.get("timezone") or "")
    if hour is None or minute is None or not timezone_name:
        return {
            "status": "unavailable",
            "reason": "unverified_scheduler_time",
            "target_date": str(target_text),
        }

    try:
        target_date = date.fromisoformat(str(target_text))
        timezone = ZoneInfo(timezone_name)
        scheduled_for = datetime.combine(
            target_date,
            time(hour=hour, minute=minute),
            tzinfo=timezone,
        )
        current_time = (now or datetime.now(timezone)).astimezone(timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        return {
            "status": "unavailable",
            "reason": str(exc),
            "target_date": str(target_text),
        }

    seconds_delta = int((scheduled_for - current_time).total_seconds())
    grace_seconds = max(int(schedule_overdue_grace_minutes), 0) * 60
    if seconds_delta > 0:
        due_status = "pending"
    elif seconds_delta == 0:
        due_status = "due_now"
    elif abs(seconds_delta) <= grace_seconds:
        due_status = "grace_period"
    else:
        due_status = "overdue"
    grace_deadline = scheduled_for + timedelta(seconds=grace_seconds)

    return {
        "status": "scheduled",
        "target_date": target_date.isoformat(),
        "scheduled_for": scheduled_for.isoformat(),
        "grace_deadline": grace_deadline.isoformat(),
        "grace_minutes": max(int(schedule_overdue_grace_minutes), 0),
        "now": current_time.isoformat(),
        "due_status": due_status,
        "seconds_until_due": max(seconds_delta, 0),
        "seconds_overdue": abs(seconds_delta) if seconds_delta < 0 else 0,
        "seconds_until_grace_deadline": max(
            int((grace_deadline - current_time).total_seconds()),
            0,
        ),
        "timezone": timezone_name,
        "hour": hour,
        "minute": minute,
        "task_name": scheduler.get("name"),
    }


def _with_quote_pre_readiness_schedule_expectation(
    *,
    scheduler: dict[str, Any],
    validation: dict[str, Any],
    next_action: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    enriched = dict(scheduler)
    expectation = _build_schedule_expectation(
        validation=validation,
        scheduler=scheduler,
        next_action=next_action,
        now=now,
        schedule_overdue_grace_minutes=QUOTE_PRE_READINESS_OVERDUE_GRACE_MINUTES,
    )
    enriched["schedule_expectation"] = expectation
    if expectation.get("status") != "scheduled":
        return enriched

    scheduled_for = _parse_optional_iso_datetime(expectation.get("scheduled_for"))
    last_run_at = _parse_optional_iso_datetime(
        (scheduler.get("run_metadata") or {}).get("last_run_at")
    )
    if scheduled_for is not None and last_run_at is not None:
        comparable_last_run = (
            last_run_at.astimezone(scheduled_for.tzinfo)
            if scheduled_for.tzinfo is not None
            else last_run_at
        )
        if (
            comparable_last_run.date() == scheduled_for.date()
            and comparable_last_run >= scheduled_for
        ):
            expectation["due_status"] = "completed"
            expectation["completed_at"] = last_run_at.isoformat()
            expectation["seconds_overdue"] = 0
            enriched["schedule_expectation"] = expectation
            return enriched

    if expectation.get("due_status") != "overdue":
        return enriched

    safety = dict(enriched.get("safety") or {})
    issues = list(safety.get("issues") or [])
    issues.append(
        {
            "code": "quote_pre_readiness_run_missing_after_grace",
            "message": (
                "Pre-readiness quote refresh did not run after its grace deadline "
                f"for {expectation.get('target_date')}."
            ),
        }
    )
    safety["status"] = "warning"
    safety["issues"] = issues
    enriched["safety"] = safety
    enriched["status"] = "warning"
    enriched["schedule_expectation"] = expectation
    return enriched


def _resolve_acceptance_gate_issue(
    *,
    validation: dict[str, Any],
    scheduler: dict[str, Any],
    auto_advisor_weekly_scheduler: dict[str, Any],
    quote_pre_readiness_scheduler: dict[str, Any],
    scheduler_runtime: dict[str, Any],
    scheduler_activity: dict[str, Any],
) -> str | None:
    scheduler_issue = _get_scheduler_issue(scheduler=scheduler)
    if scheduler_issue:
        return scheduler_issue
    weekly_scheduler_issue = _get_scheduler_issue(scheduler=auto_advisor_weekly_scheduler)
    if weekly_scheduler_issue:
        return f"auto_advisor_weekly_{weekly_scheduler_issue}"
    quote_pre_readiness_issue = _get_scheduler_issue(scheduler=quote_pre_readiness_scheduler)
    if quote_pre_readiness_issue:
        return quote_pre_readiness_issue
    runtime_requirement = _build_scheduler_runtime_requirement(scheduler_runtime=scheduler_runtime)
    if runtime_requirement.get("ok") is not True:
        return str(runtime_requirement.get("reason") or "local_scheduler_runtime_not_ok")
    blocking_issues = validation.get("blocking_issues") or []
    if blocking_issues:
        return str(blocking_issues[0].get("reason") or "blocking_issue")
    if validation.get("status") == "accepted" and scheduler_activity.get("ok") is not True:
        return str(scheduler_activity.get("status") or "scheduler_activity_not_ok")
    qlib_evidence = _build_qlib_formal_evidence_requirement(validation=validation)
    if qlib_evidence.get("ok") is not True:
        return "qlib_formal_evidence_missing"
    workspace_core_evidence = _build_workspace_core_formal_evidence_requirement(
        validation=validation
    )
    if workspace_core_evidence.get("ok") is not True:
        return "workspace_core_formal_evidence_missing"
    alpha_workspace_evidence = _build_alpha_workspace_formal_evidence_requirement(
        validation=validation
    )
    if alpha_workspace_evidence.get("ok") is not True:
        return "alpha_workspace_formal_evidence_missing"
    decision_data_evidence = _build_decision_data_formal_evidence_requirement(validation=validation)
    if decision_data_evidence.get("ok") is not True:
        return "decision_data_formal_evidence_missing"
    quote_freshness_evidence = _build_decision_quote_freshness_formal_evidence_requirement(
        validation=validation
    )
    if quote_freshness_evidence.get("ok") is not True:
        return "decision_quote_freshness_formal_evidence_missing"
    risk_evidence = status_services.build_risk_center_formal_evidence_requirement(
        validation=validation
    )
    if risk_evidence.get("ok") is not True:
        return "risk_center_formal_evidence_missing"
    quote_pre_readiness_activity = _build_quote_pre_readiness_activity_requirement(
        validation=validation,
        quote_pre_readiness_scheduler=quote_pre_readiness_scheduler,
    )
    if quote_pre_readiness_activity.get("ok") is not True:
        return str(
            quote_pre_readiness_activity.get("status") or "quote_pre_readiness_activity_missing"
        )
    weekly_activity = _build_auto_advisor_weekly_activity_requirement(
        validation=validation,
        auto_advisor_weekly_scheduler=auto_advisor_weekly_scheduler,
    )
    if weekly_activity.get("ok") is not True:
        return "auto_advisor_weekly_activity_missing"
    weekly_persistence = _build_auto_advisor_weekly_persistence_requirement(validation=validation)
    if weekly_persistence.get("ok") is not True:
        return "auto_advisor_weekly_persistence_missing"
    return None


def _rollup_status(
    *,
    validation: dict[str, Any],
    scheduler: dict[str, Any],
    auto_advisor_weekly_scheduler: dict[str, Any] | None = None,
    quote_pre_readiness_scheduler: dict[str, Any] | None = None,
    scheduler_runtime: dict[str, Any] | None = None,
    scheduler_activity: dict[str, Any] | None = None,
) -> str:
    if scheduler.get("status") != "ok":
        return "warning"
    if (
        auto_advisor_weekly_scheduler is not None
        and auto_advisor_weekly_scheduler.get("status") != "ok"
    ):
        return "warning"
    if (
        quote_pre_readiness_scheduler is not None
        and quote_pre_readiness_scheduler.get("status") != "ok"
    ):
        return "warning"
    if (
        scheduler_runtime is not None
        and scheduler_runtime.get("required")
        and scheduler_runtime.get("status") != "ok"
    ):
        return "warning"
    if (
        validation.get("status") == "accepted"
        and scheduler_activity is not None
        and scheduler_activity.get("ok") is not True
    ):
        return "warning"
    if validation.get("status") == "accepted" and (
        _build_auto_advisor_weekly_activity_requirement(
            validation=validation,
            auto_advisor_weekly_scheduler=auto_advisor_weekly_scheduler or {},
        ).get("ok")
        is not True
    ):
        return "warning"
    if (
        validation.get("status") == "accepted"
        and _build_qlib_formal_evidence_requirement(validation=validation).get("ok") is not True
    ):
        return "warning"
    if (
        validation.get("status") == "accepted"
        and _build_workspace_core_formal_evidence_requirement(validation=validation).get("ok")
        is not True
    ):
        return "warning"
    if (
        validation.get("status") == "accepted"
        and _build_alpha_workspace_formal_evidence_requirement(validation=validation).get("ok")
        is not True
    ):
        return "warning"
    if (
        validation.get("status") == "accepted"
        and _build_decision_data_formal_evidence_requirement(validation=validation).get("ok")
        is not True
    ):
        return "warning"
    if (
        validation.get("status") == "accepted"
        and _build_decision_quote_freshness_formal_evidence_requirement(validation=validation).get(
            "ok"
        )
        is not True
    ):
        return "warning"
    if (
        validation.get("status") == "accepted"
        and status_services.build_risk_center_formal_evidence_requirement(
            validation=validation
        ).get("ok")
        is not True
    ):
        return "warning"
    if (
        validation.get("status") == "accepted"
        and _build_quote_pre_readiness_activity_requirement(
            validation=validation,
            quote_pre_readiness_scheduler=quote_pre_readiness_scheduler or {},
        ).get("ok")
        is not True
    ):
        return "warning"
    if (
        validation.get("status") == "accepted"
        and _build_auto_advisor_weekly_persistence_requirement(validation=validation).get("ok")
        is not True
    ):
        return "warning"
    if validation.get("status") == "accepted":
        return "accepted"
    if validation.get("blocking_issues"):
        return "blocked"
    return "in_progress"
