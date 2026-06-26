"""Configure periodic quote refresh tasks for decision-grade data."""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django_celery_beat.models import (
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
    PeriodicTasks,
)

from apps.data_center.application.use_cases import DEFAULT_DECISION_ASSET_CODES

TASK_NAME_INTRADAY = "decision-quote-intraday-refresh"
TASK_NAME_POST_CLOSE = "decision-quote-post-close-refresh"
TASK_NAME_FRESHNESS = "decision-quote-freshness-check"


class Command(BaseCommand):
    help = "Create/update periodic tasks for decision quote snapshot refresh."

    def add_arguments(self, parser):
        parser.add_argument("--asset-codes", default="")
        parser.add_argument("--quote-max-age-hours", type=float, default=None)
        parser.add_argument("--disable", action="store_true")

    def handle(self, *args, **options):
        enabled = not bool(options.get("disable"))
        configured_asset_codes = getattr(
            settings, "DECISION_READINESS_ASSET_CODES", DEFAULT_DECISION_ASSET_CODES
        )
        raw_asset_codes = options.get("asset_codes") or ",".join(configured_asset_codes)
        asset_codes = [
            item.strip().upper()
            for item in str(raw_asset_codes or "").split(",")
            if item.strip()
        ]
        quote_max_age_hours = float(
            options.get("quote_max_age_hours")
            or getattr(settings, "DECISION_QUOTE_MAX_AGE_HOURS", 4.0)
        )
        kwargs = {
            "quote_max_age_hours": quote_max_age_hours,
        }
        if asset_codes:
            kwargs["asset_codes"] = asset_codes

        with transaction.atomic():
            intraday_crontab = self._get_crontab(hour=9, minute=45, day_of_week="1,2,3,4,5")
            post_close_crontab = self._get_crontab(hour=15, minute=20, day_of_week="1,2,3,4,5")
            freshness_interval, _ = IntervalSchedule.objects.get_or_create(
                every=6,
                period=IntervalSchedule.HOURS,
            )

            self._upsert_task(
                name=TASK_NAME_INTRADAY,
                enabled=enabled,
                kwargs=kwargs,
                description="Intraday refresh of decision-grade quote snapshots.",
                crontab=intraday_crontab,
            )
            self._upsert_task(
                name=TASK_NAME_POST_CLOSE,
                enabled=enabled,
                kwargs=kwargs,
                description="Post-close refresh of decision-grade quote snapshots.",
                crontab=post_close_crontab,
            )
            PeriodicTask.objects.update_or_create(
                name=TASK_NAME_FRESHNESS,
                defaults={
                    "task": "apps.data_center.application.tasks.refresh_decision_quote_snapshots_task",
                    "enabled": enabled,
                    "kwargs": json.dumps(kwargs, ensure_ascii=True),
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
        self.stdout.write(f"  - {TASK_NAME_FRESHNESS}: {status} every 6 hours")

    @staticmethod
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

    @staticmethod
    def _upsert_task(*, name: str, enabled: bool, kwargs: dict, description: str, crontab):
        PeriodicTask.objects.update_or_create(
            name=name,
            defaults={
                "task": "apps.data_center.application.tasks.refresh_decision_quote_snapshots_task",
                "enabled": enabled,
                "kwargs": json.dumps(kwargs, ensure_ascii=True),
                "description": description,
                "interval": None,
                "crontab": crontab,
                "solar": None,
                "clocked": None,
            },
        )
