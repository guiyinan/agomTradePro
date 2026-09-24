"""Configure the complete-market refresh independently of readiness probe quotes."""

from __future__ import annotations

import importlib
import json
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

_models = importlib.import_module("django_celery_beat.models")
CrontabSchedule: Any = _models.CrontabSchedule
PeriodicTask: Any = _models.PeriodicTask


class Command(BaseCommand):
    """Maintain one full-market schedule; execution retains the audit authority gate."""

    help = "Configure weekday full-market publications before Alpha feature refresh."

    def add_arguments(self, parser: CommandParser) -> None:
        """Expose schedule and bounded source batch options."""
        parser.add_argument("--hour", type=int, default=16)
        parser.add_argument("--minute", type=int, default=30)
        parser.add_argument("--source", choices=("akshare", "tushare"), default=None)
        parser.add_argument("--quote-source", choices=("akshare", "tushare"), default="akshare")
        parser.add_argument("--valuation-source", choices=("akshare", "tushare"), default="tushare")
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--disable", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        """Validate before atomically upserting the schedule and its task."""
        for name, lower, upper in (("hour", 0, 23), ("minute", 0, 59), ("batch_size", 1, 200)):
            value = options[name]
            if type(value) is not int or not lower <= value <= upper:
                raise CommandError(f"Invalid {name}")
        source = options["source"]
        quote_source = options["quote_source"]
        valuation_source = options["valuation_source"]
        if source is not None and (type(source) is not str or source not in {"akshare", "tushare"}):
            raise CommandError("Invalid source")
        if type(quote_source) is not str or quote_source not in {"akshare", "tushare"}:
            raise CommandError("Invalid quote source")
        if type(valuation_source) is not str or valuation_source not in {"akshare", "tushare"}:
            raise CommandError("Invalid valuation source")
        if source is not None:
            quote_source = valuation_source = source
        if type(options["disable"]) is not bool:
            raise CommandError("Invalid disable flag")
        with transaction.atomic():
            schedule, _ = CrontabSchedule.objects.get_or_create(
                minute=str(options["minute"]),
                hour=str(options["hour"]),
                day_of_week="1,2,3,4,5",
                day_of_month="*",
                month_of_year="*",
                timezone=settings.TIME_ZONE,
            )
            PeriodicTask.objects.update_or_create(
                name="full-market-current-publications",
                defaults={
                    "task": "data_center.refresh_full_market_publications",
                    "crontab": schedule,
                    "interval": None,
                    "solar": None,
                    "clocked": None,
                    "one_off": False,
                    "enabled": not options["disable"],
                    "args": "[]",
                    "kwargs": json.dumps(
                        {
                            "quote_source": quote_source,
                            "valuation_source": valuation_source,
                            "batch_size": options["batch_size"],
                        }
                    ),
                    "description": "Full active market facts and canonical publication; fails closed without valid audit authority.",
                },
            )
        self.stdout.write(
            "Full-market publication schedule configured; audit authority is required."
        )
