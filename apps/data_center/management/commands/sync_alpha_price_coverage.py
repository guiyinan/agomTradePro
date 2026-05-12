from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.data_center.infrastructure.alpha_price_coverage_sync import (
    AlphaPriceCoverageSyncService,
)
from core.integration.alpha_cache import get_alpha_cache_earliest_trade_date


class Command(BaseCommand):
    help = "Backfill asset master rows and local price bars for Alpha cache assets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=str,
            default="",
            help="Optional cache intended_trade_date lower bound (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default="",
            help="Optional cache intended_trade_date upper bound (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--extra-code",
            nargs="*",
            default=[],
            help="Optional additional asset codes to sync together with Alpha cache codes.",
        )
        parser.add_argument(
            "--no-remote",
            action="store_true",
            help="Do not fetch missing asset names from EastMoney during master backfill.",
        )

    def handle(self, *args, **options):
        start_date = self._parse_start_date(options["start_date"])
        end_date = self._parse_end_date(options["end_date"])

        report = AlphaPriceCoverageSyncService().sync_from_alpha_cache(
            start_date=start_date,
            end_date=end_date,
            include_remote=not options["no_remote"],
            extra_codes=options["extra_code"],
        )

        self.stdout.write(self.style.SUCCESS("Alpha price coverage sync completed"))
        self.stdout.write(str(report.to_dict()))

    @staticmethod
    def _parse_start_date(raw_value: str):
        if raw_value:
            return date.fromisoformat(raw_value)
        earliest = get_alpha_cache_earliest_trade_date()
        if earliest is not None:
            return earliest
        return timezone.now().date() - timedelta(days=30)

    @staticmethod
    def _parse_end_date(raw_value: str):
        if raw_value:
            return date.fromisoformat(raw_value)
        return timezone.now().date()
