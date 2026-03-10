import json

from django.core.management.base import BaseCommand
from django.db import transaction
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = "Create/update periodic tasks for equity valuation sync and quality validation."

    def add_arguments(self, parser):
        parser.add_argument("--hour", type=int, default=18)
        parser.add_argument("--minute", type=int, default=30)
        parser.add_argument("--disable", action="store_true")

    def handle(self, *args, **options):
        enabled = not options["disable"]
        hour = options["hour"]
        minute = options["minute"]

        with transaction.atomic():
            crontab_kwargs = {
                "minute": str(minute),
                "hour": str(hour),
                "day_of_week": "*",
                "day_of_month": "*",
                "month_of_year": "*",
            }
            if any(f.name == "timezone" for f in CrontabSchedule._meta.fields):
                crontab_kwargs["timezone"] = "Asia/Shanghai"

            daily_crontab, _ = CrontabSchedule.objects.get_or_create(**crontab_kwargs)
            freshness_interval, _ = IntervalSchedule.objects.get_or_create(
                every=6, period=IntervalSchedule.HOURS
            )

            sync_task, _ = PeriodicTask.objects.get_or_create(name="equity-valuation-daily-sync")
            sync_task.task = "apps.equity.application.tasks_valuation_sync.sync_validate_scan_equity_valuation_task"
            sync_task.enabled = enabled
            sync_task.kwargs = json.dumps({
                "days_back": 1,
                "primary_source": "akshare",
                "fallback_source": "tushare",
                "universe": "all_active",
                "lookback_days": 756,
            })
            sync_task.description = "Daily equity valuation sync + validate + repair scan"
            sync_task.interval = None
            sync_task.solar = None
            sync_task.clocked = None
            sync_task.crontab = daily_crontab
            sync_task.save()

            validate_task, _ = PeriodicTask.objects.get_or_create(name="equity-valuation-quality-validate")
            validate_task.task = "apps.equity.application.tasks_valuation_sync.validate_equity_valuation_quality_task"
            validate_task.enabled = enabled
            validate_task.kwargs = json.dumps({"primary_source": "akshare"})
            validate_task.description = "Standalone quality validation for local equity valuation data"
            validate_task.interval = None
            validate_task.solar = None
            validate_task.clocked = None
            validate_task.crontab = daily_crontab
            validate_task.save()

            freshness_task, _ = PeriodicTask.objects.get_or_create(name="equity-valuation-freshness-check")
            freshness_task.task = "apps.equity.application.tasks_valuation_sync.validate_equity_valuation_quality_task"
            freshness_task.enabled = enabled
            freshness_task.kwargs = json.dumps({"primary_source": "akshare"})
            freshness_task.description = "Periodic valuation freshness and gate check"
            freshness_task.crontab = None
            freshness_task.solar = None
            freshness_task.clocked = None
            freshness_task.interval = freshness_interval
            freshness_task.save()

        status = "enabled" if enabled else "disabled"
        self.stdout.write(self.style.SUCCESS("Equity valuation periodic tasks configured"))
        self.stdout.write(f"  - equity-valuation-daily-sync: {status} @ {hour:02d}:{minute:02d}")
        self.stdout.write(f"  - equity-valuation-quality-validate: {status} @ {hour:02d}:{minute:02d}")
        self.stdout.write("  - equity-valuation-freshness-check: every 6 hours")
