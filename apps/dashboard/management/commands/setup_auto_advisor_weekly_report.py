"""Configure personal auto-advisor weekly report generation."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_celery_beat.models import CrontabSchedule, PeriodicTask, PeriodicTasks

PERSONAL_READINESS_DAILY_TASK_NAME = "personal-readiness-daily-evidence"
DEFAULT_PERSONAL_READINESS_DAILY_MINUTES = 16 * 60 + 10


class Command(BaseCommand):
    help = "Create/update the weekly auto-advisor report periodic task."

    def add_arguments(self, parser):
        parser.add_argument("--hour", type=int, default=17, help="Report hour (0-23)")
        parser.add_argument("--minute", type=int, default=30, help="Report minute (0-59)")
        parser.add_argument(
            "--day-of-week",
            default="fri",
            help="Celery beat day_of_week value, for example fri or 5",
        )
        parser.add_argument("--user-id", type=int, default=None, help="Optional user id")
        parser.add_argument(
            "--account-ids",
            default="",
            help="Optional comma-separated account ids used with --user-id",
        )
        parser.add_argument(
            "--clear-scope",
            action="store_true",
            help="Clear existing user/account scope and run for all active accounts",
        )
        parser.add_argument("--disable", action="store_true", help="Disable the periodic task")

    def handle(self, *args, **options):
        hour = int(options["hour"])
        minute = int(options["minute"])
        day_of_week = str(options["day_of_week"] or "fri").strip()
        enabled = not bool(options["disable"])

        if hour < 0 or hour > 23:
            self.stderr.write(self.style.ERROR("--hour must be between 0 and 23"))
            return
        if minute < 0 or minute > 59:
            self.stderr.write(self.style.ERROR("--minute must be between 0 and 59"))
            return
        if not day_of_week:
            self.stderr.write(self.style.ERROR("--day-of-week cannot be empty"))
            return
        daily_evidence_minutes = _resolve_daily_evidence_minutes()
        if hour * 60 + minute <= daily_evidence_minutes:
            raise CommandError(
                "Weekly auto-advisor report time must be later than "
                f"personal readiness daily evidence time "
                f"({_format_minutes(daily_evidence_minutes)})."
            )

        with transaction.atomic():
            existing_task = PeriodicTask.objects.filter(
                name="dashboard-auto-advisor-weekly-report"
            ).first()
            kwargs = _resolve_task_kwargs(
                existing_task=existing_task,
                user_id=options.get("user_id"),
                account_ids_text=str(options.get("account_ids") or ""),
                clear_scope=bool(options.get("clear_scope")),
            )
            crontab = _get_crontab(hour=hour, minute=minute, day_of_week=day_of_week)
            PeriodicTask.objects.update_or_create(
                name="dashboard-auto-advisor-weekly-report",
                defaults={
                    "task": "dashboard.generate_auto_advisor_weekly_reports",
                    "enabled": enabled,
                    "kwargs": json.dumps(kwargs, ensure_ascii=True),
                    "description": "Weekly personal auto-advisor report generation",
                    "interval": None,
                    "solar": None,
                    "clocked": None,
                    "crontab": crontab,
                },
            )
            PeriodicTasks.changed(PeriodicTask)

        status = "enabled" if enabled else "disabled"
        scope = _describe_scope(kwargs)
        self.stdout.write(self.style.SUCCESS("Auto-advisor weekly report task configured"))
        self.stdout.write(
            f"  - dashboard-auto-advisor-weekly-report: {status} {day_of_week} "
            f"{hour:02d}:{minute:02d} ({scope})"
        )


def _resolve_task_kwargs(
    *,
    existing_task: PeriodicTask | None,
    user_id: int | None,
    account_ids_text: str,
    clear_scope: bool,
) -> dict:
    if clear_scope:
        return {}
    if user_id is not None or account_ids_text.strip():
        return _build_task_kwargs(user_id=user_id, account_ids_text=account_ids_text)
    return _load_existing_task_kwargs(existing_task)


def _build_task_kwargs(*, user_id: int | None, account_ids_text: str) -> dict:
    kwargs: dict[str, object] = {}
    if user_id is not None:
        kwargs["user_id"] = int(user_id)
    try:
        account_ids = [
            int(value.strip())
            for value in account_ids_text.split(",")
            if value.strip()
        ]
    except ValueError as exc:
        raise CommandError("--account-ids must be comma-separated integers") from exc
    if account_ids and user_id is None:
        raise CommandError("--account-ids requires --user-id")
    if account_ids:
        kwargs["account_ids"] = account_ids
    return kwargs


def _load_existing_task_kwargs(existing_task: PeriodicTask | None) -> dict:
    if existing_task is None:
        return {}
    try:
        payload = json.loads(existing_task.kwargs or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _describe_scope(kwargs: dict) -> str:
    if "user_id" not in kwargs:
        return "all active accounts"
    account_ids = kwargs.get("account_ids")
    if isinstance(account_ids, list) and account_ids:
        return f"user_id={kwargs['user_id']}, account_ids={account_ids}"
    return f"user_id={kwargs['user_id']}"


def _resolve_daily_evidence_minutes() -> int:
    try:
        task = PeriodicTask.objects.filter(name=PERSONAL_READINESS_DAILY_TASK_NAME).first()
    except Exception:
        return DEFAULT_PERSONAL_READINESS_DAILY_MINUTES
    crontab = getattr(task, "crontab", None) if task is not None else None
    hour = _parse_single_crontab_number(str(getattr(crontab, "hour", "") or ""))
    minute = _parse_single_crontab_number(str(getattr(crontab, "minute", "") or ""))
    if hour is None or minute is None:
        return DEFAULT_PERSONAL_READINESS_DAILY_MINUTES
    return hour * 60 + minute


def _parse_single_crontab_number(value: str) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _format_minutes(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _get_crontab(*, hour: int, minute: int, day_of_week: str):
    crontab_kwargs = {
        "minute": str(minute),
        "hour": str(hour),
        "day_of_week": day_of_week,
        "day_of_month": "*",
        "month_of_year": "*",
    }
    if any(field.name == "timezone" for field in CrontabSchedule._meta.fields):
        crontab_kwargs["timezone"] = "Asia/Shanghai"
    return CrontabSchedule.objects.get_or_create(**crontab_kwargs)[0]
