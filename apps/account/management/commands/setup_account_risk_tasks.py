import json

from django.core.management.base import BaseCommand
from django.db import transaction
from django_celery_beat.models import CrontabSchedule, PeriodicTask, PeriodicTasks


class Command(BaseCommand):
    help = "Create/update account stop-loss and take-profit periodic tasks."

    def add_arguments(self, parser):
        parser.add_argument("--disable", action="store_true")

    def handle(self, *args, **options):
        enabled = not options["disable"]

        crontab_kwargs = {
            "minute": "*/30",
            "hour": "10-15",
            "day_of_week": "1,2,3,4,5",
            "day_of_month": "*",
            "month_of_year": "*",
        }
        if any(field.name == "timezone" for field in CrontabSchedule._meta.fields):
            crontab_kwargs["timezone"] = "Asia/Shanghai"

        with transaction.atomic():
            intraday_crontab, _ = CrontabSchedule.objects.get_or_create(**crontab_kwargs)
            PeriodicTask.objects.update_or_create(
                name="account-check-stop-loss-take-profit-intraday",
                defaults={
                    "task": "apps.account.application.tasks.check_stop_loss_and_take_profit_task",
                    "enabled": enabled,
                    "kwargs": json.dumps({}, ensure_ascii=True),
                    "description": "Intraday account stop-loss and take-profit execution check",
                    "interval": None,
                    "solar": None,
                    "clocked": None,
                    "crontab": intraday_crontab,
                },
            )
            PeriodicTasks.changed(PeriodicTask)

        status = "enabled" if enabled else "disabled"
        self.stdout.write(self.style.SUCCESS("Account risk periodic tasks configured"))
        self.stdout.write(f"  - account-check-stop-loss-take-profit-intraday: {status} weekdays 10-15 */30")
