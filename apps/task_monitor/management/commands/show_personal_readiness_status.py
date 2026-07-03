from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django_celery_beat.models import PeriodicTask

from apps.task_monitor.application import readiness_status_services as status_services
from apps.task_monitor.management import (
    auto_advisor_weekly_scheduler_status as weekly_status,
)
from apps.task_monitor.management import (
    quote_pre_readiness_scheduler_status,
    readiness_persistence_status,
    scheduler_status_utils,
)
from apps.task_monitor.management.commands.run_personal_readiness_daily import (
    resolve_default_readiness_target_date,
)
from apps.task_monitor.management.commands.setup_personal_readiness_daily import (
    DEFAULT_TASK_KWARGS,
    TASK_NAME,
    TASK_PATH,
)
from apps.task_monitor.management.commands.validate_personal_readiness_window import (
    DEFAULT_CALENDAR_SOURCE,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_REQUIRED_DAYS,
    validate_personal_readiness_window,
)
from apps.task_monitor.management.readiness_runtime import collect_local_scheduler_runtime

MIN_POST_CLOSE_SCHEDULE_MINUTES = 15 * 60 + 30
EXPECTED_SCHEDULE_TIMEZONE, EXPECTED_SCHEDULE_DAY_OF_WEEK = "Asia/Shanghai", "mon-fri"
EXPECTED_SCHEDULE_DAY_OF_MONTH = EXPECTED_SCHEDULE_MONTH_OF_YEAR = "*"
DEFAULT_SCHEDULE_OVERDUE_GRACE_MINUTES, QUOTE_PRE_READINESS_OVERDUE_GRACE_MINUTES = 30, 15
STRICT_MONITOR_COMMAND = "python manage.py show_personal_readiness_status --json --strict-monitor --require-local-scheduler-runtime"
AUTO_ADVISOR_WEEKLY_TASK_NAME, AUTO_ADVISOR_WEEKLY_TASK_PATH = weekly_status.AUTO_ADVISOR_WEEKLY_TASK_NAME, weekly_status.AUTO_ADVISOR_WEEKLY_TASK_PATH
_collect_auto_advisor_weekly_scheduler_status = weekly_status.collect_auto_advisor_weekly_scheduler_status
QUOTE_PRE_READINESS_TASK_NAME, QUOTE_PRE_READINESS_TASK_PATH = quote_pre_readiness_scheduler_status.QUOTE_PRE_READINESS_TASK_NAME, quote_pre_readiness_scheduler_status.QUOTE_PRE_READINESS_TASK_PATH
_collect_quote_pre_readiness_scheduler_status = (
    quote_pre_readiness_scheduler_status.collect_quote_pre_readiness_scheduler_status
)
_parse_scheduler_kwargs = scheduler_status_utils.parse_scheduler_kwargs
_parse_scheduler_args = scheduler_status_utils.parse_scheduler_args
_parse_scheduler_headers = scheduler_status_utils.parse_scheduler_headers
_collect_scheduler_run_controls = scheduler_status_utils.collect_scheduler_run_controls
_optional_isoformat = scheduler_status_utils.optional_isoformat
_collect_scheduler_delivery_controls = scheduler_status_utils.collect_scheduler_delivery_controls
_collect_scheduler_run_metadata = scheduler_status_utils.collect_scheduler_run_metadata
_build_delivery_control_safety_issues = scheduler_status_utils.build_delivery_control_safety_issues
_build_run_control_safety_issues = scheduler_status_utils.build_run_control_safety_issues
_parse_single_crontab_number = scheduler_status_utils.parse_single_crontab_number


class Command(BaseCommand):
    help = "Show personal readiness window, evidence, and scheduler status."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--output-dir",
            default=DEFAULT_OUTPUT_DIR,
            help=f"Evidence directory. Default: {DEFAULT_OUTPUT_DIR}",
        )
        parser.add_argument(
            "--required-days",
            type=int,
            default=DEFAULT_REQUIRED_DAYS,
            help=f"Required accepted trading-day records. Default: {DEFAULT_REQUIRED_DAYS}",
        )
        parser.add_argument(
            "--calendar-source",
            choices=("auto", "qlib", "weekday"),
            default=DEFAULT_CALENDAR_SOURCE,
            help="Trading calendar source. Default: auto.",
        )
        parser.add_argument(
            "--expected-latest-date",
            default=None,
            help="Expected latest readiness date in YYYY-MM-DD format.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="print_json",
            help="Print full JSON result.",
        )
        parser.add_argument(
            "--strict-monitor",
            action="store_true",
            help=(
                "Exit with CommandError for operator-action states such as missed "
                "closed-date evidence, failed evidence, or unsafe scheduler config."
            ),
        )
        parser.add_argument(
            "--require-local-scheduler-runtime",
            action="store_true",
            help=(
                "Require local Celery beat and worker processes in the monitor gate. "
                "Use for local continuous-run trials; production process checks are deployment-specific."
            ),
        )
        parser.add_argument(
            "--local-runtime-ping-timeout",
            type=float,
            default=5.0,
            help="Celery inspect ping timeout when local scheduler runtime is required.",
        )
        parser.add_argument(
            "--strict-acceptance",
            action="store_true",
            help=(
                "Exit with CommandError unless the 20-trading-day acceptance gate "
                "is fully accepted, including scheduler safety/activity and local runtime proof."
            ),
        )
        parser.add_argument(
            "--schedule-overdue-grace-minutes",
            type=int,
            default=DEFAULT_SCHEDULE_OVERDUE_GRACE_MINUTES,
            help=(
                "Grace window before a scheduled but missing readiness run is "
                f"treated as overdue. Default: {DEFAULT_SCHEDULE_OVERDUE_GRACE_MINUTES}."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        payload = build_personal_readiness_status(
            output_dir=Path(str(options["output_dir"])),
            required_days=int(options["required_days"]),
            calendar_source=str(options["calendar_source"]),
            expected_latest_date=_parse_date(options.get("expected_latest_date"))
            or resolve_default_readiness_target_date(),
            schedule_overdue_grace_minutes=int(options["schedule_overdue_grace_minutes"]),
            require_local_scheduler_runtime=bool(
                options.get("require_local_scheduler_runtime") or options.get("strict_acceptance")
            ),
            local_runtime_ping_timeout=float(options["local_runtime_ping_timeout"]),
            include_current_macro_context=True, include_current_decision_data=True,
        )

        if options.get("print_json"):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            if options.get("strict_monitor"):
                _raise_for_strict_monitor(payload)
            if options.get("strict_acceptance"):
                _raise_for_strict_acceptance(payload)
            return

        validation = payload["validation"]
        scheduler = payload["scheduler"]
        latest = payload["latest_evidence"]
        self.stdout.write(
            self.style.SUCCESS(
                "Personal readiness status: "
                f"{validation['accepted_days']}/{validation['required_days']} accepted, "
                f"remaining={validation['remaining_days']}, "
                f"next={validation['next_required_date']}"
            )
        )
        self.stdout.write(
            "  scheduler: {status} enabled={enabled} task={task}".format(
                status=scheduler["status"],
                enabled=scheduler.get("enabled"),
                task=scheduler.get("task"),
            )
        )
        safety_issues = (scheduler.get("safety") or {}).get("issues") or []
        if safety_issues:
            self.stdout.write(self.style.WARNING(f"  scheduler safety: {safety_issues[0]['code']}"))
        runtime = payload.get("scheduler_runtime") or {}
        if runtime.get("required"):
            self.stdout.write(
                "  scheduler runtime: {status} beat={beat} worker={worker}".format(
                    status=runtime.get("status"),
                    beat=runtime.get("beat_process_count"),
                    worker=runtime.get("worker_process_count"),
                )
            )
        self.stdout.write(
            "  latest evidence: {target_date} status={status}".format(
                target_date=latest.get("target_date") or "-",
                status=latest.get("status") or "missing",
            )
        )
        acceptance_gate = payload["acceptance_gate"]
        projected_completion = acceptance_gate.get("projected_completion_date")
        if projected_completion:
            self.stdout.write(
                "  projected completion: {date} ({days} calendar days from today)".format(
                    date=projected_completion,
                    days=acceptance_gate.get("projected_remaining_calendar_days_from_today"),
                )
            )
        if validation["blocking_issues"]:
            first = validation["blocking_issues"][0]
            self.stdout.write(
                self.style.WARNING(f"  blocking: {first['target_date']} {first['reason']}")
            )
        next_action = payload["next_action"]
        self.stdout.write(f"  next action: {next_action['action']}")
        if next_action.get("command"):
            self.stdout.write(f"  next command: {next_action['command']}")
        if options.get("strict_monitor"):
            _raise_for_strict_monitor(payload)
        if options.get("strict_acceptance"):
            _raise_for_strict_acceptance(payload)


def build_personal_readiness_status(
    *,
    output_dir: Path,
    required_days: int = DEFAULT_REQUIRED_DAYS,
    calendar_source: str = DEFAULT_CALENDAR_SOURCE,
    expected_latest_date: date,
    schedule_overdue_grace_minutes: int = DEFAULT_SCHEDULE_OVERDUE_GRACE_MINUTES,
    require_local_scheduler_runtime: bool = False,
    local_runtime_ping_timeout: float = 5.0,
    include_current_macro_context: bool = False, include_current_decision_data: bool = False,
) -> dict[str, Any]:
    """Build a read-only operational summary for the personal readiness run."""

    validation = validate_personal_readiness_window(
        output_dir=output_dir,
        required_days=required_days,
        calendar_source=calendar_source,
        expected_latest_date=expected_latest_date,
    )
    scheduler = _collect_scheduler_status()
    auto_advisor_weekly_scheduler = _collect_auto_advisor_weekly_scheduler_status()
    quote_pre_readiness_scheduler = _collect_quote_pre_readiness_scheduler_status()
    scheduler_runtime = collect_local_scheduler_runtime(
        required=require_local_scheduler_runtime,
        worker_ping_timeout=local_runtime_ping_timeout,
    )
    latest_closed_date = resolve_default_readiness_target_date()
    latest_evidence = _collect_latest_evidence(output_dir=output_dir)
    latest_formal_evidence = _collect_latest_evidence(
        output_dir=output_dir,
        formal_candidate_only=True,
    )
    post_evidence_persistence = readiness_persistence_status.collect_post_evidence_persistence(
        output_dir=output_dir,
    )
    account_readiness = status_services.build_account_readiness_summary()
    next_action = _resolve_next_action(
        validation=validation,
        scheduler=scheduler,
        output_dir=output_dir,
        expected_latest_date=expected_latest_date,
        latest_closed_date=latest_closed_date,
    )
    schedule_expectation = _build_schedule_expectation(
        validation=validation,
        scheduler=scheduler,
        next_action=next_action,
        schedule_overdue_grace_minutes=schedule_overdue_grace_minutes,
    )
    quote_pre_readiness_scheduler = _with_quote_pre_readiness_schedule_expectation(
        scheduler=quote_pre_readiness_scheduler,
        validation=validation,
        next_action=next_action,
    )
    next_action = _normalize_next_action_for_schedule(
        next_action=next_action,
        schedule_expectation=schedule_expectation,
    )
    scheduler_activity = status_services.build_scheduler_activity(
        validation=validation,
        scheduler=scheduler,
    )
    status = _rollup_status(
        validation=validation,
        scheduler=scheduler,
        auto_advisor_weekly_scheduler=auto_advisor_weekly_scheduler,
        quote_pre_readiness_scheduler=quote_pre_readiness_scheduler,
        scheduler_runtime=scheduler_runtime,
        scheduler_activity=scheduler_activity,
    )
    monitor_gate = _build_monitor_gate(
        status=status,
        next_action=next_action,
        schedule_expectation=schedule_expectation,
        scheduler_runtime=scheduler_runtime,
        post_evidence_persistence=post_evidence_persistence,
    )
    status_date = _resolve_status_date(schedule_expectation=schedule_expectation)
    return {
        "status": status,
        "expected_latest_date": expected_latest_date.isoformat(),
        "latest_closed_date": latest_closed_date.isoformat(),
        "status_date": status_date.isoformat(),
        "validation": validation,
        "scheduler": scheduler,
        "auto_advisor_weekly_scheduler": auto_advisor_weekly_scheduler,
        "quote_pre_readiness_scheduler": quote_pre_readiness_scheduler,
        "scheduler_runtime": scheduler_runtime,
        "latest_evidence": latest_evidence,
        "latest_formal_evidence": latest_formal_evidence,
        "current_macro_context": status_services.build_current_macro_context(target_date=latest_closed_date) if include_current_macro_context else None,
        "current_decision_data": status_services.build_current_decision_data_from_settings() if include_current_decision_data else None,
        "account_readiness": account_readiness,
        "post_evidence_persistence": post_evidence_persistence,
        "acceptance_gate": _build_acceptance_gate(
            validation=validation,
            scheduler=scheduler,
            auto_advisor_weekly_scheduler=auto_advisor_weekly_scheduler,
            quote_pre_readiness_scheduler=quote_pre_readiness_scheduler,
            scheduler_runtime=scheduler_runtime,
            latest_formal_evidence=latest_formal_evidence,
            post_evidence_persistence=post_evidence_persistence,
            next_action=next_action,
            schedule_expectation=schedule_expectation,
            status_date=status_date,
            scheduler_activity=scheduler_activity,
        ),
        "schedule_expectation": schedule_expectation,
        "monitor_gate": monitor_gate,
        "next_action": next_action,
        "next_command": next_action.get("command"),
    }


def _resolve_next_action(
    *,
    validation: dict[str, Any],
    scheduler: dict[str, Any],
    output_dir: Path,
    expected_latest_date: date,
    latest_closed_date: date,
) -> dict[str, Any]:
    scheduler_issue = _get_scheduler_issue(scheduler=scheduler)
    if scheduler_issue:
        return {
            "action": "fix_scheduler",
            "reason": scheduler_issue,
            "target_date": None,
            "latest_closed_date": latest_closed_date.isoformat(),
            "command": "python manage.py setup_personal_readiness_daily",
        }

    if validation.get("status") == "accepted":
        return {
            "action": "none",
            "reason": "window_accepted",
            "target_date": None,
            "command": None,
        }

    target_text = validation.get("next_required_date") or expected_latest_date.isoformat()
    target_date = date.fromisoformat(str(target_text))
    if target_date > latest_closed_date:
        return {
            "action": "wait_for_post_close",
            "reason": "target_date_not_closed",
            "target_date": target_date.isoformat(),
            "latest_closed_date": latest_closed_date.isoformat(),
            "command": None,
        }

    blocking_issues = validation.get("blocking_issues") or []
    has_missing_evidence = not blocking_issues or _is_missing_evidence_blocker(blocking_issues[0])
    action = "run_daily" if has_missing_evidence else "inspect_blocking_issue"
    command = (
        "python manage.py run_personal_readiness_daily "
        f"--target-date {target_date.isoformat()} --json"
    )
    if not has_missing_evidence:
        command = (
            "python manage.py inspect_personal_readiness_evidence "
            f"--output-dir {_format_command_arg(str(output_dir))} "
            f"--target-date {target_date.isoformat()} --json"
        )
    return {
        "action": action,
        "reason": validation.get("next_required_reason") or "ready",
        "target_date": target_date.isoformat(),
        "latest_closed_date": latest_closed_date.isoformat(),
        "command": command,
    }


def _normalize_next_action_for_schedule(
    *,
    next_action: dict[str, Any],
    schedule_expectation: dict[str, Any],
) -> dict[str, Any]:
    if next_action.get("action") != "run_daily":
        return next_action
    if schedule_expectation.get("status") != "scheduled":
        return next_action
    normalized = dict(next_action)
    if schedule_expectation.get("due_status") == "overdue":
        normalized["action"] = "inspect_missed_scheduled_run"
        normalized["reason"] = "scheduled_evidence_missing_after_grace"
        normalized["command"] = STRICT_MONITOR_COMMAND
        normalized["scheduled_for"] = schedule_expectation.get("scheduled_for")
        normalized["grace_deadline"] = schedule_expectation.get("grace_deadline")
        return normalized
    if schedule_expectation.get("due_status") not in {"pending", "due_now", "grace_period"}:
        return next_action
    normalized["action"] = "wait_for_scheduled_run"
    normalized["reason"] = "scheduled_evidence_pending"
    normalized["command"] = None
    normalized["scheduled_for"] = schedule_expectation.get("scheduled_for")
    normalized["grace_deadline"] = schedule_expectation.get("grace_deadline")
    return normalized


def _is_missing_evidence_blocker(issue: dict[str, Any]) -> bool:
    return str(issue.get("reason") or "") == "evidence is missing"


def _format_command_arg(value: str) -> str:
    if any(char.isspace() for char in value):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _raise_for_strict_monitor(payload: dict[str, Any]) -> None:
    monitor_gate = dict(payload.get("monitor_gate") or {})
    if monitor_gate:
        if monitor_gate.get("ok") is True:
            return
        raise CommandError(
            "Personal readiness monitor requires attention: "
            f"{monitor_gate.get('state') or 'unknown'} "
            f"({monitor_gate.get('reason') or 'unknown'})"
        )

    # Backward-compatible fallback for callers that build partial payloads in tests.
    next_action = dict(payload.get("next_action") or {})
    action = str(next_action.get("action") or "")
    schedule_expectation = dict(payload.get("schedule_expectation") or {})
    if schedule_expectation.get("due_status") == "overdue":
        raise CommandError(
            "Personal readiness monitor schedule is overdue: "
            f"{schedule_expectation.get('scheduled_for')}"
        )
    if action in {"wait_for_post_close", "wait_for_scheduled_run", "none"}:
        return
    if action:
        raise CommandError(
            "Personal readiness monitor requires operator action: "
            f"{action} ({next_action.get('reason') or 'unknown'})"
        )
    status = str(payload.get("status") or "unknown")
    if status in {"warning", "blocked"}:
        raise CommandError(f"Personal readiness monitor is {status}")


def _build_monitor_gate(
    *,
    status: str,
    next_action: dict[str, Any],
    schedule_expectation: dict[str, Any],
    scheduler_runtime: dict[str, Any] | None = None,
    post_evidence_persistence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action = str(next_action.get("action") or "")
    due_status = str(schedule_expectation.get("due_status") or "")
    if (runtime := dict(scheduler_runtime or {})).get("required") and runtime.get("status") != "ok":
        issues = list(runtime.get("issues") or [])
        first_issue = issues[0] if issues else {}
        remediation_commands = list(runtime.get("remediation_commands") or [])
        return {
            "ok": False,
            "state": "local_scheduler_runtime_unavailable",
            "reason": first_issue.get("code") or "local_scheduler_runtime_not_ok",
            "next_action": action or None,
            "command": remediation_commands[0] if remediation_commands else STRICT_MONITOR_COMMAND,
            "remediation_commands": remediation_commands,
            "due_status": due_status or None,
        }
    if due_status == "overdue":
        return {
            "ok": False,
            "state": "schedule_overdue",
            "reason": "scheduled_evidence_missing_after_grace",
            "next_action": action,
            "scheduled_for": schedule_expectation.get("scheduled_for"),
            "grace_deadline": schedule_expectation.get("grace_deadline"),
            "seconds_overdue": schedule_expectation.get("seconds_overdue"),
            "command": next_action.get("command"),
        }
    if post_evidence_gate := readiness_persistence_status.build_post_evidence_monitor_gate(
        post_evidence_persistence, due_status or None, STRICT_MONITOR_COMMAND
    ):
        return post_evidence_gate
    if action in {"wait_for_post_close", "wait_for_scheduled_run", "none"} and status != "warning":
        return {
            "ok": True,
            "state": action,
            "reason": next_action.get("reason"),
            "next_action": action,
            "next_check_after": schedule_expectation.get(
                "scheduled_for" if due_status in {"pending", "due_now"} else "grace_deadline"
            ),
            "due_status": due_status or None,
        }
    if action:
        return {
            "ok": False,
            "state": "operator_action_required",
            "reason": action,
            "next_action": action,
            "command": next_action.get("command"),
            "due_status": due_status or None,
        }
    if status in {"warning", "blocked"}:
        return {
            "ok": False,
            "state": status,
            "reason": "readiness_status_not_ok",
            "next_action": action or None,
            "due_status": due_status or None,
        }
    return {
        "ok": True,
        "state": status or "unknown",
        "reason": "monitor_ok",
        "next_action": action or None,
        "due_status": due_status or None,
    }


def _raise_for_strict_acceptance(payload: dict[str, Any]) -> None:
    gate = dict(payload.get("acceptance_gate") or {})
    if gate.get("accepted") is True:
        return
    accepted_days = gate.get("accepted_days")
    required_days = gate.get("required_days")
    remaining_days = gate.get("remaining_days")
    issue = gate.get("issue") or gate.get("next_action") or "not_accepted"
    failed_requirements = [
        str(item.get("name"))
        for item in list(gate.get("failed_requirements") or [])
        if isinstance(item, dict) and item.get("name")
    ]
    failed_suffix = (
        f", failed_requirements={','.join(failed_requirements)}" if failed_requirements else ""
    )
    raise CommandError(
        "Personal readiness acceptance gate is not accepted: "
        f"{accepted_days}/{required_days} days accepted, "
        f"remaining={remaining_days}, issue={issue}{failed_suffix}"
    )


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
                "reason": runtime_requirement.get("reason")
                or "local_scheduler_runtime_not_ok",
                "command": remediation_commands[0] if remediation_commands else STRICT_MONITOR_COMMAND,
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
    schedule_expectation = dict(
        quote_pre_readiness_scheduler.get("schedule_expectation") or {}
    )
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
            (quote_pre_readiness_scheduler.get("effective_kwargs") or {}).get(
                "quote_max_age_hours"
            )
        ),
    }


def _build_quote_pre_readiness_activity_requirement(
    *,
    validation: dict[str, Any],
    quote_pre_readiness_scheduler: dict[str, Any],
) -> dict[str, Any]:
    quality = dict(validation.get("accepted_evidence_quality") or {})
    evidence_quality_available = (
        "formal_quote_pre_readiness_scheduler_ok_record_count" in quality
    )
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


def _resolve_accepted_window_dates(*, validation: dict[str, Any]) -> tuple[date | None, date | None]:
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
        if comparable_last_run >= scheduled_for:
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
    quote_pre_readiness_issue = _get_scheduler_issue(
        scheduler=quote_pre_readiness_scheduler
    )
    if quote_pre_readiness_issue:
        return quote_pre_readiness_issue
    runtime_requirement = _build_scheduler_runtime_requirement(
        scheduler_runtime=scheduler_runtime
    )
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
            quote_pre_readiness_activity.get("status")
            or "quote_pre_readiness_activity_missing"
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


def _collect_scheduler_status() -> dict[str, Any]:
    try:
        task = PeriodicTask.objects.filter(name=TASK_NAME).first()
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    if task is None:
        return {
            "status": "missing",
            "name": TASK_NAME,
            "task": TASK_PATH,
            "enabled": False,
        }

    crontab = task.crontab
    schedule = (
        {
            "minute": crontab.minute,
            "hour": crontab.hour,
            "day_of_week": crontab.day_of_week,
            "day_of_month": crontab.day_of_month,
            "month_of_year": crontab.month_of_year,
            "timezone": str(getattr(crontab, "timezone", "") or ""),
        }
        if crontab is not None
        else None
    )
    parsed_kwargs = _parse_scheduler_kwargs(task.kwargs)
    parsed_args = _parse_scheduler_args(getattr(task, "args", None))
    parsed_headers = _parse_scheduler_headers(getattr(task, "headers", None))
    effective_kwargs = dict(DEFAULT_TASK_KWARGS)
    effective_kwargs.update(parsed_kwargs.get("kwargs", {}))
    run_controls = _collect_scheduler_run_controls(task)
    delivery_controls = _collect_scheduler_delivery_controls(
        task, effective_headers=parsed_headers.get("headers", {})
    )
    run_metadata = _collect_scheduler_run_metadata(task)
    safety = _build_scheduler_safety(
        task_path=task.task,
        enabled=bool(task.enabled),
        kwargs_error=parsed_kwargs.get("error"),
        args_error=parsed_args.get("error"),
        args=parsed_args.get("args", []),
        headers_error=parsed_headers.get("error"),
        effective_kwargs=effective_kwargs,
        schedule=schedule,
        run_controls=run_controls,
        delivery_controls=delivery_controls,
    )
    return {
        "status": "ok" if safety["status"] == "ok" else "warning",
        "name": task.name,
        "task": task.task,
        "enabled": bool(task.enabled),
        "args": getattr(task, "args", "[]"),
        "effective_args": parsed_args.get("args", []),
        "kwargs": task.kwargs,
        "effective_kwargs": effective_kwargs,
        "run_controls": run_controls,
        "delivery_controls": delivery_controls,
        "run_metadata": run_metadata,
        "safety": safety,
        "schedule": schedule,
    }


def _build_scheduler_safety(
    *,
    task_path: str,
    enabled: bool,
    kwargs_error: Any,
    effective_kwargs: dict[str, Any],
    schedule: dict[str, str] | None,
    args_error: Any = None,
    args: list[Any] | None = None,
    headers_error: Any = None,
    run_controls: dict[str, Any] | None = None,
    delivery_controls: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if not enabled:
        issues.append(
            {
                "code": "scheduler_disabled",
                "message": "Scheduled readiness evidence collection is disabled.",
            }
        )
    if task_path != TASK_PATH:
        issues.append(
            {
                "code": "unexpected_task_path",
                "message": f"Expected {TASK_PATH}, got {task_path}",
            }
        )
    if kwargs_error:
        issues.append(
            {
                "code": "invalid_scheduler_kwargs",
                "message": str(kwargs_error),
            }
        )
    if args_error:
        issues.append(
            {
                "code": "invalid_scheduler_args",
                "message": str(args_error),
            }
        )
    if args:
        issues.append(
            {
                "code": "unexpected_scheduler_args",
                "message": "Scheduled readiness evidence must not use positional args.",
            }
        )
    if headers_error:
        issues.append(
            {
                "code": "invalid_scheduler_headers",
                "message": str(headers_error),
            }
        )
    kwargs_safety = status_services.build_scheduler_kwargs_safety(effective_kwargs=effective_kwargs)
    issues.extend(kwargs_safety["issues"])
    run_control_issues = _build_run_control_safety_issues(run_controls=run_controls or {})
    issues.extend(run_control_issues)
    delivery_control_issues = _build_delivery_control_safety_issues(
        delivery_controls=delivery_controls or {}
    )
    issues.extend(delivery_control_issues)
    schedule_issue = _build_schedule_safety_issue(schedule=schedule)
    if schedule_issue:
        issues.append(schedule_issue)
    return {
        "status": "warning" if issues else "ok",
        "enabled": enabled,
        "allow_unclosed_target_date": kwargs_safety["allow_unclosed_target_date"],
        "repair_accounts": kwargs_safety["repair_accounts"],
        "trigger_source": kwargs_safety["trigger_source"],
        "calendar_source": kwargs_safety["calendar_source"],
        "run_workspace_refresh": kwargs_safety["run_workspace_refresh"],
        "include_weekly_advisor": kwargs_safety["include_weekly_advisor"],
        "persist_risk_report": kwargs_safety["persist_risk_report"],
        "max_qlib_staleness_days": kwargs_safety["max_qlib_staleness_days"],
        "issues": issues,
    }


def _build_schedule_safety_issue(schedule: dict[str, str] | None) -> dict[str, str] | None:
    if schedule is None:
        return {
            "code": "missing_scheduler_crontab",
            "message": "Scheduled readiness evidence has no crontab schedule.",
        }
    timezone = str(schedule.get("timezone") or "")
    if timezone != EXPECTED_SCHEDULE_TIMEZONE:
        return {
            "code": "unexpected_scheduler_timezone",
            "message": (
                "Scheduled readiness evidence should use "
                f"{EXPECTED_SCHEDULE_TIMEZONE}, got {timezone or 'missing'}."
            ),
        }
    day_of_week = str(schedule.get("day_of_week") or "")
    if day_of_week != EXPECTED_SCHEDULE_DAY_OF_WEEK:
        return {
            "code": "unexpected_scheduler_day_of_week",
            "message": (
                "Scheduled readiness evidence should run on "
                f"{EXPECTED_SCHEDULE_DAY_OF_WEEK}, got {day_of_week or 'missing'}."
            ),
        }
    day_of_month = str(schedule.get("day_of_month") or "")
    if day_of_month != EXPECTED_SCHEDULE_DAY_OF_MONTH:
        return {
            "code": "unexpected_scheduler_day_of_month",
            "message": (
                "Scheduled readiness evidence should run every day-of-month, "
                f"got {day_of_month or 'missing'}."
            ),
        }
    month_of_year = str(schedule.get("month_of_year") or "")
    if month_of_year != EXPECTED_SCHEDULE_MONTH_OF_YEAR:
        return {
            "code": "unexpected_scheduler_month_of_year",
            "message": (
                "Scheduled readiness evidence should run every month, "
                f"got {month_of_year or 'missing'}."
            ),
        }
    hour = _parse_single_crontab_number(str(schedule.get("hour") or ""))
    minute = _parse_single_crontab_number(str(schedule.get("minute") or ""))
    if hour is None or minute is None:
        return {
            "code": "unverified_scheduler_time",
            "message": "Scheduled readiness evidence time is not a single verifiable clock time.",
        }
    scheduled_minutes = hour * 60 + minute
    if scheduled_minutes < MIN_POST_CLOSE_SCHEDULE_MINUTES:
        return {
            "code": "scheduler_before_post_close",
            "message": "Scheduled readiness evidence should run after 15:30 Asia/Shanghai.",
        }
    return None


def _collect_latest_evidence(
    *,
    output_dir: Path,
    formal_candidate_only: bool = False,
) -> dict[str, Any]:
    root = Path(settings.BASE_DIR) / output_dir if not output_dir.is_absolute() else output_dir
    latest_payload: dict[str, Any] | None = None
    latest_date: date | None = None
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            target_date = date.fromisoformat(str(payload["target_date"]))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        operation_context = dict(payload.get("operation_context") or {})
        if formal_candidate_only and not _is_acceptance_candidate(
            operation_context=operation_context
        ):
            continue
        if latest_date is None or target_date > latest_date:
            latest_date = target_date
            latest_payload = payload

    if latest_payload is None:
        return {"status": "missing", "target_date": None}

    return _summarize_evidence_payload(latest_payload)


def _summarize_evidence_payload(payload: dict[str, Any]) -> dict[str, Any]:
    summary = dict(payload.get("summary") or {})
    operation_context = dict(payload.get("operation_context") or {})
    classification = _classify_evidence(operation_context=operation_context)
    return {
        "status": payload.get("status"),
        "target_date": payload.get("target_date"),
        "operation_context": operation_context or None,
        "formal_evidence": classification["formal_evidence"],
        "acceptance_candidate": classification["acceptance_candidate"],
        "evidence_mode": classification["evidence_mode"],
        "trigger_source": classification["trigger_source"],
        "trigger_task_id": classification["trigger_task_id"],
        "trigger_task_name": classification["trigger_task_name"],
        "summary": {
            "system_status": summary.get("system_status"),
            "qlib_status": summary.get("qlib_status"),
            "qlib_readiness": status_services.summarize_evidence_qlib_readiness(payload),
            "workspace_status": summary.get("workspace_status"),
            "target_count": summary.get("target_count"),
            "decision_data": status_services.summarize_evidence_decision_data(payload),
            "macro_context": status_services.summarize_evidence_macro_context(payload),
            "alpha_workspace_consistency": status_services.summarize_evidence_alpha_workspace(
                payload
            ),
            "workspace_components": status_services.summarize_evidence_workspace_components(
                payload
            ),
        },
    }


def _classify_evidence(*, operation_context: dict[str, Any]) -> dict[str, Any]:
    if not operation_context:
        return {
            "formal_evidence": None,
            "acceptance_candidate": True,
            "evidence_mode": "legacy_without_operation_context",
            "trigger_source": None,
            "trigger_task_id": None,
            "trigger_task_name": None,
        }
    formal_evidence = _is_formal_evidence(operation_context=operation_context)
    return {
        "formal_evidence": formal_evidence,
        "acceptance_candidate": formal_evidence is True,
        "evidence_mode": operation_context.get("mode") or "unknown",
        "trigger_source": operation_context.get("trigger_source"),
        "trigger_task_id": operation_context.get("trigger_task_id"),
        "trigger_task_name": operation_context.get("trigger_task_name"),
    }


def _is_acceptance_candidate(*, operation_context: dict[str, Any]) -> bool:
    return bool(_classify_evidence(operation_context=operation_context)["acceptance_candidate"])


def _is_formal_evidence(*, operation_context: dict[str, Any]) -> bool | None:
    if not operation_context:
        return None
    return (
        operation_context.get("mode") == "formal"
        and operation_context.get("target_date_closed") is True
        and operation_context.get("allow_unclosed_target_date") is not True
    )


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
        and status_services.build_risk_center_formal_evidence_requirement(validation=validation).get(
            "ok"
        )
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


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError("expected-latest-date must be YYYY-MM-DD") from exc
