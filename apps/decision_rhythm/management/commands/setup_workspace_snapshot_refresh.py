"""Configure nightly decision workspace snapshot refresh tasks."""

import json

from django.core.management.base import BaseCommand
from django.db import transaction
from django_celery_beat.models import CrontabSchedule, PeriodicTask, PeriodicTasks


class Command(BaseCommand):
    help = "Create/update the nightly decision workspace snapshot refresh task."

    def add_arguments(self, parser):
        parser.add_argument("--hour", type=int, default=22, help="Nightly refresh hour (0-23)")
        parser.add_argument("--minute", type=int, default=45, help="Nightly refresh minute (0-59)")
        parser.add_argument("--disable", action="store_true", help="Disable the periodic task")

    def handle(self, *args, **options):
        hour = options["hour"]
        minute = options["minute"]
        enabled = not options["disable"]

        if hour < 0 or hour > 23:
            self.stderr.write(self.style.ERROR("--hour must be between 0 and 23"))
            return
        if minute < 0 or minute > 59:
            self.stderr.write(self.style.ERROR("--minute must be between 0 and 59"))
            return

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
