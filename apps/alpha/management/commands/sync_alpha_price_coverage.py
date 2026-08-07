from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.alpha.application.query_services import get_alpha_cache_earliest_trade_date
from apps.data_center.application.public import get_alpha_price_coverage_sync_service_port
from apps.data_center.application.public_protocols import AlphaPriceCoverageReportProtocol


class AlphaPriceCoverageSyncService:
    """Compatibility façade preserving the command's patchable construction seam."""

    def __init__(self) -> None:
        self._delegate = get_alpha_price_coverage_sync_service_port()

    def sync_from_alpha_cache(
        self,
        *,
        start_date: date,
        end_date: date,
        include_remote: bool = True,
        extra_codes: Iterable[str] = (),
    ) -> AlphaPriceCoverageReportProtocol:
        """Run the Data Center-owned Alpha price-coverage synchronization."""

        return self._delegate.sync_from_alpha_cache(
            start_date=start_date,
            end_date=end_date,
            include_remote=include_remote,
            extra_codes=extra_codes,
        )


class Command(BaseCommand):
    help = "Backfill asset master rows and local price bars for Alpha cache assets."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register bounded Alpha coverage synchronization options."""

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

    def handle(self, *args: Any, **options: Any) -> None:
        """Validate options and run one Alpha price coverage synchronization."""

        del args
        try:
            start_date = self._parse_start_date(self._string_option(options, "start_date"))
            end_date = self._parse_end_date(self._string_option(options, "end_date"))
        except (TypeError, ValueError):
            raise CommandError("alpha_price_date_invalid") from None
        if start_date > end_date:
            raise CommandError("alpha_price_date_range_invalid")

        extra_codes = self._string_list_option(options, "extra_code")
        no_remote = self._bool_option(options, "no_remote")

        report = AlphaPriceCoverageSyncService().sync_from_alpha_cache(
            start_date=start_date,
            end_date=end_date,
            include_remote=not no_remote,
            extra_codes=extra_codes,
        )

        self.stdout.write(self.style.SUCCESS("Alpha price coverage sync completed"))
        self.stdout.write(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))

    @staticmethod
    def _parse_start_date(raw_value: str) -> date:
        if raw_value:
            return date.fromisoformat(raw_value)
        earliest = get_alpha_cache_earliest_trade_date()
        if earliest is not None:
            return earliest
        return timezone.now().date() - timedelta(days=30)

    @staticmethod
    def _parse_end_date(raw_value: str) -> date:
        if raw_value:
            return date.fromisoformat(raw_value)
        return timezone.now().date()

    @staticmethod
    def _string_option(options: dict[str, Any], name: str) -> str:
        value = options.get(name, "")
        if not isinstance(value, str):
            raise TypeError(f"{name}_invalid")
        return value.strip()

    @staticmethod
    def _string_list_option(options: dict[str, Any], name: str) -> list[str]:
        value = options.get(name, [])
        if not isinstance(value, (list, tuple)) or len(value) > 5000:
            raise CommandError(f"{name}_invalid")
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip() or len(item) > 100:
                raise CommandError(f"{name}_invalid")
            normalized.append(item.strip())
        return normalized

    @staticmethod
    def _bool_option(options: dict[str, Any], name: str) -> bool:
        value = options.get(name, False)
        if not isinstance(value, bool):
            raise CommandError(f"{name}_invalid")
        return value
