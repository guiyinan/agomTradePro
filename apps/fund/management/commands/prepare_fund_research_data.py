from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.fund.infrastructure.models import FundInfoModel
from apps.fund.infrastructure.repositories import DjangoFundRepository

logger = logging.getLogger(__name__)
_FUND_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


class Command(BaseCommand):
    help = (
        "Prepare fund research data by syncing fund info, NAV history, and performance snapshots."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--fund-codes",
            type=str,
            default="",
            help="Comma-separated fund codes to prepare. When omitted, use local fund universe.",
        )
        parser.add_argument(
            "--fund-types",
            type=str,
            default="",
            help="Comma-separated fund types to limit the fund universe.",
        )
        parser.add_argument(
            "--max-funds",
            type=int,
            default=30,
            help="Maximum number of funds to backfill when fund codes are not specified.",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default="",
            help="Performance/NAV start date in YYYY-MM-DD format. Default: 1 year ago.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default="",
            help="Performance/NAV end date in YYYY-MM-DD format. Default: today.",
        )
        parser.add_argument(
            "--skip-info-sync",
            action="store_true",
            help="Do not auto-sync the fund master list when local fund info is empty.",
        )
        parser.add_argument(
            "--allow-remote-nav-sync",
            action="store_true",
            help="Fetch missing NAV history from Tushare when local NAV data is absent.",
        )

    def handle(self, *args: str, **options: Any) -> None:
        repo = DjangoFundRepository()
        start_date = self._parse_date(
            options.get("start_date"),
            default=date.today() - timedelta(days=365),
        )
        end_date = self._parse_date(options.get("end_date"), default=date.today())

        if start_date >= end_date:
            raise CommandError("start-date must be earlier than end-date")
        if (end_date - start_date).days > 7_305:
            raise CommandError("fund research date range exceeds 20 years")

        skip_info_sync = options.get("skip_info_sync", False)
        allow_remote_nav_sync = options.get("allow_remote_nav_sync", False)
        if not isinstance(skip_info_sync, bool) or not isinstance(allow_remote_nav_sync, bool):
            raise CommandError("fund research boolean options are invalid")

        if not skip_info_sync:
            try:
                synced_count = repo.ensure_fund_universe_seeded()
            except Exception as exc:
                logger.error(
                    "Fund master sync failed: %s",
                    type(exc).__name__,
                )
                raise CommandError("fund_master_sync_failed") from None
            self.stdout.write(self.style.SUCCESS(f"Fund info sync completed: {synced_count} rows"))

        fund_codes = self._resolve_fund_codes(options)
        if not fund_codes:
            raise CommandError(
                "No fund codes available. Sync fund master data first or pass --fund-codes."
            )

        self.stdout.write(
            f"Preparing {len(fund_codes)} funds for range {start_date.isoformat()} -> {end_date.isoformat()}"
        )

        prepared_count = 0
        skipped_count = 0
        failed_codes: list[str] = []

        for fund_code in fund_codes:
            try:
                performance = repo.get_or_build_fund_performance(
                    fund_code=fund_code,
                    start_date=start_date,
                    end_date=end_date,
                    allow_remote_sync=allow_remote_nav_sync,
                )
            except Exception:
                failed_codes.append(fund_code)
                continue

            if performance is None:
                skipped_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipped {fund_code}: no usable NAV/performance data in the target range"
                    )
                )
                continue

            prepared_count += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"Prepared {fund_code}: {performance.start_date.isoformat()} -> "
                    f"{performance.end_date.isoformat()}, total_return={performance.total_return:.2f}%"
                )
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Prepared funds: {prepared_count}"))
        self.stdout.write(self.style.WARNING(f"Skipped funds: {skipped_count}"))
        if failed_codes:
            self.stdout.write(
                self.style.ERROR(
                    f"Failed funds ({len(failed_codes)}): {', '.join(failed_codes[:20])}"
                )
            )

    def _resolve_fund_codes(self, options: Mapping[str, Any]) -> list[str]:
        raw_code_value = options.get("fund_codes", "")
        raw_type_value = options.get("fund_types", "")
        if not isinstance(raw_code_value, str) or not isinstance(raw_type_value, str):
            raise CommandError("fund selector options are invalid")
        raw_codes = [code.strip() for code in raw_code_value.split(",") if code.strip()]
        if (
            len(raw_codes) > 1_000
            or len(set(raw_codes)) != len(raw_codes)
            or any(_FUND_CODE_PATTERN.fullmatch(code) is None for code in raw_codes)
        ):
            raise CommandError("fund-codes contains invalid identifiers")
        if raw_codes:
            return raw_codes

        queryset = FundInfoModel._default_manager.filter(is_active=True)

        raw_types = [item.strip() for item in raw_type_value.split(",") if item.strip()]
        if len(raw_types) > 100 or any(
            not item or len(item) > 100 or any(ord(character) < 32 for character in item)
            for item in raw_types
        ):
            raise CommandError("fund-types contains invalid identifiers")
        if raw_types:
            queryset = queryset.filter(fund_type__in=raw_types)

        raw_max_funds = options.get("max_funds", 30)
        if (
            isinstance(raw_max_funds, bool)
            or not isinstance(raw_max_funds, int)
            or not 1 <= raw_max_funds <= 1_000
        ):
            raise CommandError("max-funds must be between 1 and 1000")
        max_funds = raw_max_funds
        return list(
            queryset.order_by("-fund_scale", "fund_code").values_list("fund_code", flat=True)[
                :max_funds
            ]
        )

    def _parse_date(self, value: Any, *, default: date) -> date:
        if value is None:
            return default
        if not isinstance(value, str):
            raise CommandError("fund research date is invalid")
        if not value:
            return default
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise CommandError("fund research date is invalid") from None
