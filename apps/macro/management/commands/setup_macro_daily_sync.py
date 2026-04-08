"""
Configure daily macro sync periodic tasks in django-celery-beat.

Usage:
    python manage.py setup_macro_daily_sync
    python manage.py setup_macro_daily_sync --hour 8 --minute 10
    python manage.py setup_macro_daily_sync --disable
"""

import json

from django.core.management.base import BaseCommand
from django.db import transaction
from django_celery_beat.models import (
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
    PeriodicTasks,
)


LEGACY_TASK_ALIASES = {
    "apps.macro.application.tasks.sync_and_calculate_regime": (
        "apps.regime.application.orchestration.sync_macro_then_refresh_regime"
    ),
    "apps.macro.application.tasks.generate_daily_regime_signal": (
        "apps.regime.application.orchestration.generate_daily_regime_signal"
    ),
    "apps.macro.application.tasks.recalculate_regime_with_daily_signal": (
        "apps.regime.application.orchestration.recalculate_regime_with_daily_signal"
    ),
}

MANAGED_TASK_NAMES = {
    "daily-sync-and-calculate",
    "check-data-freshness",
    "high-frequency-generate-signal",
    "high-frequency-recalculate-regime",
}


class Command(BaseCommand):
    help = "Create/update macro and regime periodic tasks for robust decision data freshness."

    def add_arguments(self, parser):
        parser.add_argument("--hour", type=int, default=8, help="Daily sync hour (0-23)")
        parser.add_argument("--minute", type=int, default=5, help="Daily sync minute (0-59)")
        parser.add_argument(
            "--disable",
            action="store_true",
            help="Create/update tasks but disable them",
        )

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
            # django-celery-beat >=2.5 supports timezone on CrontabSchedule.
            if any(f.name == "timezone" for f in CrontabSchedule._meta.fields):
                crontab_kwargs["timezone"] = "Asia/Shanghai"

            daily_crontab, _ = CrontabSchedule.objects.get_or_create(**crontab_kwargs)
            freshness_interval, _ = IntervalSchedule.objects.get_or_create(
                every=6,
                period=IntervalSchedule.HOURS,
            )
            weekday_crontab_kwargs = {
                "minute": "0",
                "hour": "17",
                "day_of_week": "1,2,3,4,5",
                "day_of_month": "*",
                "month_of_year": "*",
            }
            weekday_recalc_crontab_kwargs = {
                **weekday_crontab_kwargs,
                "minute": "5",
            }
            if any(f.name == "timezone" for f in CrontabSchedule._meta.fields):
                weekday_crontab_kwargs["timezone"] = "Asia/Shanghai"
                weekday_recalc_crontab_kwargs["timezone"] = "Asia/Shanghai"
            weekday_signal_crontab, _ = CrontabSchedule.objects.get_or_create(
                **weekday_crontab_kwargs
            )
            weekday_recalc_crontab, _ = CrontabSchedule.objects.get_or_create(
                **weekday_recalc_crontab_kwargs
            )

            sync_kwargs = {
                "source": "akshare",
                "indicator": None,
                "days_back": 60,
                "use_pit": True,
            }
            PeriodicTask.objects.update_or_create(
                name="daily-sync-and-calculate",
                defaults={
                    "task": "apps.regime.application.orchestration.sync_macro_then_refresh_regime",
                    "enabled": enabled,
                    "kwargs": json.dumps(sync_kwargs, ensure_ascii=True),
                    "description": "Daily macro sync + regime calculation for dashboard reliability",
                    "interval": None,
                    "solar": None,
                    "clocked": None,
                    "crontab": daily_crontab,
                },
            )

            PeriodicTask.objects.update_or_create(
                name="check-data-freshness",
                defaults={
                    "task": "apps.macro.application.tasks.check_data_freshness",
                    "enabled": enabled,
                    "kwargs": "{}",
                    "description": "Check macro freshness every 6 hours and alert on stale inputs",
                    "crontab": None,
                    "solar": None,
                    "clocked": None,
                    "interval": freshness_interval,
                },
            )

            PeriodicTask.objects.update_or_create(
                name="high-frequency-generate-signal",
                defaults={
                    "task": "apps.regime.application.orchestration.generate_daily_regime_signal",
                    "enabled": enabled,
                    "kwargs": "{}",
                    "description": "Generate daily regime signal from high-frequency indicators",
                    "interval": None,
                    "solar": None,
                    "clocked": None,
                    "crontab": weekday_signal_crontab,
                },
            )

            PeriodicTask.objects.update_or_create(
                name="high-frequency-recalculate-regime",
                defaults={
                    "task": "apps.regime.application.orchestration.recalculate_regime_with_daily_signal",
                    "enabled": enabled,
                    "kwargs": json.dumps({"use_pit": True}, ensure_ascii=True),
                    "description": "Recalculate regime with daily signal after high-frequency sync",
                    "interval": None,
                    "solar": None,
                    "clocked": None,
                    "crontab": weekday_recalc_crontab,
                },
            )

            for legacy_task, canonical_task in LEGACY_TASK_ALIASES.items():
                PeriodicTask.objects.filter(task=legacy_task).exclude(
                    name__in=MANAGED_TASK_NAMES
                ).update(
                    enabled=False,
                    description=(
                        f"Disabled legacy task path {legacy_task}; "
                        f"use {canonical_task} instead."
                    ),
                )

            PeriodicTasks.changed(PeriodicTask)

        status = "enabled" if enabled else "disabled"
        self.stdout.write(self.style.SUCCESS("Macro periodic tasks configured"))
        self.stdout.write(f"  - daily-sync-and-calculate: {status} @ {hour:02d}:{minute:02d}")
        self.stdout.write(f"  - check-data-freshness: {status} every 6 hours")
        self.stdout.write(f"  - high-frequency-generate-signal: {status} @ weekdays 17:00")
        self.stdout.write(
            f"  - high-frequency-recalculate-regime: {status} @ weekdays 17:05"
        )
