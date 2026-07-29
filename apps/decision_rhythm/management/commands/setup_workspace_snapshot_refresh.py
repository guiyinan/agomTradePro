"""Configure nightly decision workspace snapshot refresh tasks."""

import json
from argparse import ArgumentParser
from importlib import import_module
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Create/update the nightly decision workspace snapshot refresh task."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--hour", type=int, default=22, help="Nightly refresh hour (0-23)")
        parser.add_argument("--minute", type=int, default=45, help="Nightly refresh minute (0-59)")
        parser.add_argument("--disable", action="store_true", help="Disable the periodic task")

    def handle(self, *args: Any, **options: Any) -> None:
        hour = options.get("hour")
        minute = options.get("minute")
        disabled = options.get("disable")

        if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
            raise CommandError("--hour must be between 0 and 23")
        if isinstance(minute, bool) or not isinstance(minute, int) or not 0 <= minute <= 59:
            raise CommandError("--minute must be between 0 and 59")
        if not isinstance(disabled, bool):
            raise CommandError("--disable must be boolean")

        enabled = not disabled
        beat_models = import_module("django_celery_beat.models")
        CrontabSchedule = beat_models.CrontabSchedule
        PeriodicTask = beat_models.PeriodicTask
        PeriodicTasks = beat_models.PeriodicTasks

        with transaction.atomic():
            crontab_kwargs = {
                "minute": str(minute),
                "hour": str(hour),
                "day_of_week": "*",
                "day_of_month": "*",
                "month_of_year": "*",
            }
            if any(field.name == "timezone" for field in CrontabSchedule._meta.fields):
                crontab_kwargs["timezone"] = "Asia/Shanghai"

            nightly_crontab, _ = CrontabSchedule.objects.get_or_create(**crontab_kwargs)

            PeriodicTask.objects.update_or_create(
                name="decision-workspace-nightly-snapshot-refresh",
                defaults={
                    "task": "apps.decision_rhythm.application.tasks.refresh_decision_workspace_snapshots",
                    "enabled": enabled,
                    "kwargs": json.dumps(
                        {
                            "source": "akshare",
                            "days_back": 60,
                            "use_pit": True,
                        },
                        ensure_ascii=True,
                    ),
                    "description": (
                        "Nightly precompute of Step 1-3 workspace snapshots "
                        "(regime, pulse, action recommendation, rotation)."
                    ),
                    "interval": None,
                    "solar": None,
                    "clocked": None,
                    "crontab": nightly_crontab,
                },
            )

            PeriodicTasks.changed(PeriodicTask)

        status = "enabled" if enabled else "disabled"
        self.stdout.write(self.style.SUCCESS("Decision workspace snapshot task configured"))
        self.stdout.write(
            f"  - decision-workspace-nightly-snapshot-refresh: {status} @ {hour:02d}:{minute:02d}"
        )
