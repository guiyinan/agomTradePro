from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
from apps.task_monitor.management.readiness_status_acceptance import (
    DEFAULT_SCHEDULE_OVERDUE_GRACE_MINUTES,
    EXPECTED_SCHEDULE_DAY_OF_WEEK,
    EXPECTED_SCHEDULE_TIMEZONE,
    MIN_POST_CLOSE_SCHEDULE_MINUTES,
    QUOTE_PRE_READINESS_OVERDUE_GRACE_MINUTES,
    STRICT_MONITOR_COMMAND,
    _build_acceptance_gate,
    _build_acceptance_operator_actions,
    _build_auto_advisor_weekly_persistence_requirement,
    _build_quote_pre_readiness_activity_requirement,
    _build_schedule_expectation,
    _build_scheduler_runtime_requirement,
    _get_scheduler_issue,
    _resolve_status_date,
    _rollup_status,
    _with_quote_pre_readiness_schedule_expectation,
)
from apps.task_monitor.management.readiness_status_evidence import (
    _collect_latest_evidence,
)

EXPECTED_SCHEDULE_DAY_OF_MONTH = EXPECTED_SCHEDULE_MONTH_OF_YEAR = "*"
AUTO_ADVISOR_WEEKLY_TASK_NAME = weekly_status.AUTO_ADVISOR_WEEKLY_TASK_NAME
AUTO_ADVISOR_WEEKLY_TASK_PATH = weekly_status.AUTO_ADVISOR_WEEKLY_TASK_PATH
_collect_auto_advisor_weekly_scheduler_status = (
    weekly_status.collect_auto_advisor_weekly_scheduler_status
)
QUOTE_PRE_READINESS_TASK_NAME = quote_pre_readiness_scheduler_status.QUOTE_PRE_READINESS_TASK_NAME
QUOTE_PRE_READINESS_TASK_PATH = quote_pre_readiness_scheduler_status.QUOTE_PRE_READINESS_TASK_PATH
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
                "Use for local continuous-run trials; production process checks are "
                "deployment-specific."
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
                "is fully accepted, including scheduler safety/activity and local "
                "runtime proof."
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
            include_current_macro_context=True,
            include_current_decision_data=True,
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
    include_current_macro_context: bool = False,
    include_current_decision_data: bool = False,
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
    current_schedule_time = datetime.now(ZoneInfo(EXPECTED_SCHEDULE_TIMEZONE))
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
        now=current_schedule_time,
        schedule_overdue_grace_minutes=schedule_overdue_grace_minutes,
    )
    quote_pre_readiness_scheduler = _with_quote_pre_readiness_schedule_expectation(
        scheduler=quote_pre_readiness_scheduler,
        validation=validation,
        next_action=next_action,
        now=current_schedule_time,
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
        "current_macro_context": (
            status_services.build_current_macro_context(target_date=latest_closed_date)
            if include_current_macro_context
            else None
        ),
        "current_decision_data": (
            status_services.build_current_decision_data_from_settings()
            if include_current_decision_data
            else None
        ),
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
        post_evidence_persistence,
        due_status or None,
        STRICT_MONITOR_COMMAND,
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
        task,
        effective_headers=parsed_headers.get("headers", {}),
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
    kwargs_safety = status_services.build_scheduler_kwargs_safety(
        effective_kwargs=effective_kwargs
    )
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


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError("expected-latest-date must be YYYY-MM-DD") from exc
