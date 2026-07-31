"""Configure the production sentiment refresh schedule."""

from __future__ import annotations

import importlib
import json
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

TASK_NAME = "sentiment-refresh-current-index"
TASK_PATH = "sentiment.refresh_current_sentiment_index"
DEFAULT_MINUTE = "15"
DEFAULT_HOURS = "9-11,13-15,18,23"
DEFAULT_DAY_OF_WEEK = "mon-fri"
DEFAULT_EXPIRE_SECONDS = 3300


class Command(BaseCommand):
    """Create or update the market-hours sentiment refresh task."""

    help = "Create/update the current sentiment news-sync and index-refresh task."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register explicit scheduling controls."""

        parser.add_argument("--disable", action="store_true")

    def handle(self, *args: object, **options: Any) -> None:
        """Persist one idempotent database-backed periodic task."""

        del args
        disabled = options.get("disable")
        if not isinstance(disabled, bool):
            raise CommandError("--disable must be a boolean flag")

        timezone_name = getattr(settings, "TIME_ZONE", None)
        if not isinstance(timezone_name, str) or not timezone_name.strip():
            raise CommandError("TIME_ZONE must be a non-empty string")

        beat_models = importlib.import_module("django_celery_beat.models")
        crontab_model = beat_models.CrontabSchedule
        periodic_task_model = beat_models.PeriodicTask
        periodic_tasks_model = beat_models.PeriodicTasks

        crontab_kwargs: dict[str, object] = {
            "minute": DEFAULT_MINUTE,
            "hour": DEFAULT_HOURS,
            "day_of_week": DEFAULT_DAY_OF_WEEK,
            "day_of_month": "*",
            "month_of_year": "*",
        }
        if any(field.name == "timezone" for field in crontab_model._meta.fields):
            crontab_kwargs["timezone"] = timezone_name.strip()

        with transaction.atomic():
            crontab, _ = crontab_model.objects.get_or_create(**crontab_kwargs)
            periodic_task_model.objects.update_or_create(
                name=TASK_NAME,
                defaults={
                    "task": TASK_PATH,
                    "enabled": not disabled,
                    "kwargs": json.dumps({}, ensure_ascii=True, allow_nan=False),
                    "description": (
                        "Refresh configured broad-market news, then calculate a "
                        "freshness-aware sentiment index during decision windows."
                    ),
                    "interval": None,
                    "solar": None,
                    "clocked": None,
                    "crontab": crontab,
                    "expires": None,
                    "expire_seconds": DEFAULT_EXPIRE_SECONDS,
                },
            )
            periodic_tasks_model.changed(periodic_task_model)

        status = "disabled" if disabled else "enabled"
        self.stdout.write(
            self.style.SUCCESS(
                f"{TASK_NAME}: {status} {DEFAULT_DAY_OF_WEEK} "
                f"{DEFAULT_HOURS}:{DEFAULT_MINUTE} ({timezone_name.strip()})"
            )
        )
