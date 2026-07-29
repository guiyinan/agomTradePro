"""
Windows 兼容的 Celery Beat 管理命令

使用方式:
    python manage.py celery_beat_windows
    python manage.py celery_beat_windows --loglevel=debug
"""

import re
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

_LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})
_SCHEDULER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*(?::[A-Za-z_][A-Za-z0-9_]*)?$")


class Command(BaseCommand):
    help = "Run Celery beat scheduler (Windows-compatible)"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--loglevel",
            type=str,
            default="info",
            help="Logging level (debug, info, warning, error, critical)",
        )
        parser.add_argument(
            "--scheduler",
            type=str,
            default="django_celery_beat.schedulers:DatabaseScheduler",
            help="Scheduler class to use",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from core.celery import app

        loglevel = options.get("loglevel")
        scheduler = options.get("scheduler")
        if not isinstance(loglevel, str) or loglevel.lower() not in _LOG_LEVELS:
            raise CommandError("Unsupported Celery log level")
        if not isinstance(scheduler, str) or not _SCHEDULER_PATTERN.fullmatch(scheduler):
            raise CommandError("Invalid Celery scheduler path")
        loglevel = loglevel.lower()

        self.stdout.write(
            self.style.SUCCESS(f"Starting Celery beat scheduler (loglevel={loglevel})")
        )
        self.stdout.write(self.style.WARNING(f"Scheduler: {scheduler}"))
        self.stdout.write(self.style.WARNING("Press Ctrl+C to stop"))

        app.start(
            [
                "beat",
                "--loglevel=" + loglevel,
                "--scheduler=" + scheduler,
            ]
        )
