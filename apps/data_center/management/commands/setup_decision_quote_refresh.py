"""Configure periodic refresh tasks for decision-grade quote snapshots."""

from __future__ import annotations

import importlib
import json
import math
from typing import Any, cast

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

TASK_NAME_INTRADAY = "decision-quote-intraday-refresh"
TASK_NAME_POST_CLOSE = "decision-quote-post-close-refresh"
TASK_NAME_PRE_READINESS = "decision-quote-pre-readiness-refresh"
TASK_NAME_FRESHNESS = "decision-quote-freshness-check"
REFRESH_TASK = "apps.data_center.application.tasks.refresh_decision_quote_snapshots_task"
INTRADAY_HOUR = 9
INTRADAY_MINUTE = 45
POST_CLOSE_HOUR = 15
POST_CLOSE_MINUTE = 20
DEFAULT_PRE_READINESS_HOUR = 15
DEFAULT_PRE_READINESS_MINUTE = 35
FRESHNESS_INTERVAL_HOURS = 6

_beat_models = importlib.import_module("django_celery_beat.models")
CrontabSchedule: Any = _beat_models.CrontabSchedule
IntervalSchedule: Any = _beat_models.IntervalSchedule
PeriodicTask: Any = _beat_models.PeriodicTask
PeriodicTasks: Any = _beat_models.PeriodicTasks


def _required_int(options: dict[str, object], key: str) -> int:
    """Read a real integer management-command option."""

    value = options.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommandError(f"--{key.replace('_', '-')} must be an integer")
    return value


def _required_bool(options: dict[str, object], key: str) -> bool:
    """Read a real boolean management-command option."""

    value = options.get(key)
    if not isinstance(value, bool):
        raise CommandError(f"--{key.replace('_', '-')} must be a boolean")
    return value


def _resolve_asset_codes(raw_option: object) -> list[str]:
    """Resolve explicit codes or the typed settings list, preserving order."""

    if raw_option is not None and raw_option != "":
        if not isinstance(raw_option, str):
            raise CommandError("--asset-codes must be a comma-separated string")
        raw_codes: object = raw_option.split(",")
    else:
        raw_codes = getattr(settings, "DECISION_READINESS_ASSET_CODES", None)
    if not isinstance(raw_codes, list | tuple) or any(
        not isinstance(code, str) for code in raw_codes
    ):
        raise CommandError("DECISION_READINESS_ASSET_CODES must be a string list")
    codes = list(dict.fromkeys(code.strip().upper() for code in raw_codes if code.strip()))
    if not codes:
        raise CommandError("at least one decision readiness asset code is required")
    return codes


def _resolve_quote_max_age(raw_option: object) -> float:
    """Resolve a finite positive quote-age threshold without truthy fallback."""

    value = (
        getattr(settings, "DECISION_QUOTE_MAX_AGE_HOURS", None)
        if raw_option is None
        else raw_option
    )
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CommandError("quote max age must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise CommandError("quote max age must be finite and positive")
    return parsed


class Command(BaseCommand):
    """Create or update all decision quote refresh tasks atomically."""

    help = "Create/update periodic tasks for decision quote snapshot refresh."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register scheduler configuration options."""

        parser.add_argument("--asset-codes", default=None)
        parser.add_argument("--quote-max-age-hours", type=float, default=None)
        parser.add_argument(
            "--pre-readiness-hour",
            type=int,
            default=DEFAULT_PRE_READINESS_HOUR,
        )
        parser.add_argument(
            "--pre-readiness-minute",
            type=int,
            default=DEFAULT_PRE_READINESS_MINUTE,
        )
        parser.add_argument("--disable", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        """Validate the full schedule before writing any Beat rows."""

        del args
        enabled = not _required_bool(options, "disable")
        pre_readiness_hour = _required_int(options, "pre_readiness_hour")
        pre_readiness_minute = _required_int(options, "pre_readiness_minute")
        if not 0 <= pre_readiness_hour <= 23:
            raise CommandError("--pre-readiness-hour must be between 0 and 23")
        if not 0 <= pre_readiness_minute <= 59:
            raise CommandError("--pre-readiness-minute must be between 0 and 59")
        if pre_readiness_hour * 60 + pre_readiness_minute <= (
            POST_CLOSE_HOUR * 60 + POST_CLOSE_MINUTE
        ):
            raise CommandError("pre-readiness refresh must run after post-close refresh")

        asset_codes = _resolve_asset_codes(options.get("asset_codes"))
        quote_max_age_hours = _resolve_quote_max_age(options.get("quote_max_age_hours"))
        timezone_name: object = getattr(settings, "TIME_ZONE", None)
        if not isinstance(timezone_name, str) or not timezone_name.strip():
            raise CommandError("TIME_ZONE must be a non-empty string")
        task_kwargs: dict[str, object] = {
            "quote_max_age_hours": quote_max_age_hours,
            "asset_codes": asset_codes,
        }

        with transaction.atomic():
            intraday_crontab = self._get_crontab(
                hour=INTRADAY_HOUR,
                minute=INTRADAY_MINUTE,
                day_of_week="1,2,3,4,5",
                timezone_name=timezone_name.strip(),
            )
            post_close_crontab = self._get_crontab(
                hour=POST_CLOSE_HOUR,
                minute=POST_CLOSE_MINUTE,
                day_of_week="1,2,3,4,5",
                timezone_name=timezone_name.strip(),
            )
            pre_readiness_crontab = self._get_crontab(
                hour=pre_readiness_hour,
                minute=pre_readiness_minute,
                day_of_week="1,2,3,4,5",
                timezone_name=timezone_name.strip(),
            )
            freshness_interval, _ = IntervalSchedule.objects.get_or_create(
                every=FRESHNESS_INTERVAL_HOURS,
                period=IntervalSchedule.HOURS,
            )
            self._upsert_task(
                name=TASK_NAME_INTRADAY,
                enabled=enabled,
                task_kwargs=task_kwargs,
                description="Intraday refresh of decision-grade quote snapshots.",
                crontab=intraday_crontab,
            )
            self._upsert_task(
                name=TASK_NAME_POST_CLOSE,
                enabled=enabled,
                task_kwargs=task_kwargs,
                description="Post-close refresh of decision-grade quote snapshots.",
                crontab=post_close_crontab,
            )
            self._upsert_task(
                name=TASK_NAME_PRE_READINESS,
                enabled=enabled,
                task_kwargs=task_kwargs,
                description="Pre-readiness refresh of decision-grade quote snapshots.",
                crontab=pre_readiness_crontab,
            )
            PeriodicTask.objects.update_or_create(
                name=TASK_NAME_FRESHNESS,
                defaults={
                    "task": REFRESH_TASK,
                    "enabled": enabled,
                    "kwargs": json.dumps(task_kwargs, ensure_ascii=True, allow_nan=False),
                    "description": "Periodic decision quote freshness check and repair.",
                    "interval": freshness_interval,
                    "crontab": None,
                    "solar": None,
                    "clocked": None,
                },
            )
            PeriodicTasks.changed(PeriodicTask)

        status = "enabled" if enabled else "disabled"
        self.stdout.write(self.style.SUCCESS("Decision quote refresh tasks configured"))
        self.stdout.write(f"  - {TASK_NAME_INTRADAY}: {status} @ weekdays 09:45")
        self.stdout.write(f"  - {TASK_NAME_POST_CLOSE}: {status} @ weekdays 15:20")
        self.stdout.write(
            f"  - {TASK_NAME_PRE_READINESS}: "
            f"{status} @ weekdays {pre_readiness_hour:02d}:{pre_readiness_minute:02d}"
        )
        self.stdout.write(
            f"  - {TASK_NAME_FRESHNESS}: {status} every {FRESHNESS_INTERVAL_HOURS} hours"
        )

    @staticmethod
    def _get_crontab(
        *,
        hour: int,
        minute: int,
        day_of_week: str,
        timezone_name: str,
    ) -> object:
        """Return the exact crontab row for one configured schedule."""

        crontab_kwargs: dict[str, object] = {
            "minute": str(minute),
            "hour": str(hour),
            "day_of_week": day_of_week,
            "day_of_month": "*",
            "month_of_year": "*",
        }
        if any(field.name == "timezone" for field in CrontabSchedule._meta.fields):
            crontab_kwargs["timezone"] = timezone_name
        schedule = CrontabSchedule.objects.get_or_create(**crontab_kwargs)[0]
        return cast(object, schedule)

    @staticmethod
    def _upsert_task(
        *,
        name: str,
        enabled: bool,
        task_kwargs: dict[str, object],
        description: str,
        crontab: object,
    ) -> None:
        """Upsert one crontab-backed decision quote task."""

        PeriodicTask.objects.update_or_create(
            name=name,
            defaults={
                "task": REFRESH_TASK,
                "enabled": enabled,
                "kwargs": json.dumps(task_kwargs, ensure_ascii=True, allow_nan=False),
                "description": description,
                "interval": None,
                "crontab": crontab,
                "solar": None,
                "clocked": None,
            },
        )
