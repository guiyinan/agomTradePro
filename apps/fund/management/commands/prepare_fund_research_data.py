from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from apps.fund.infrastructure.models import FundInfoModel
from apps.fund.infrastructure.repositories import DjangoFundRepository


class Command(BaseCommand):
    help = "Prepare fund research data by syncing fund info, NAV history, and performance snapshots."

    def add_arguments(self, parser) -> None:
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

    def handle(self, *args, **options) -> None:
        repo = DjangoFundRepository()
        start_date = self._parse_date(options["start_date"], default=date.today() - timedelta(days=365))
        end_date = self._parse_date(options["end_date"], default=date.today())

        if start_date >= end_date:
            raise CommandError("start-date must be earlier than end-date")

        if not options["skip_info_sync"]:
            try:
                synced_count = repo.ensure_fund_universe_seeded()
            except Exception as exc:
                raise CommandError(f"Failed to sync fund master data: {exc}") from exc
            self.stdout.write(self.style.SUCCESS(f"Fund info sync completed: {synced_count} rows"))

        fund_codes = self._resolve_fund_codes(options)
        if not fund_codes:
            raise CommandError("No fund codes available. Sync fund master data first or pass --fund-codes.")

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
                    allow_remote_sync=options["allow_remote_nav_sync"],
                )
            except Exception:
                failed_codes.append(fund_code)
                continue

            if performance is None:
                skipped_count += 1
                self.stdout.write(
                    self.style.WARNING(f"Skipped {fund_code}: no usable NAV/performance data in the target range")
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
            self.stdout.write(self.style.ERROR(f"Failed funds ({len(failed_codes)}): {', '.join(failed_codes[:20])}"))

    def _resolve_fund_codes(self, options) -> list[str]:
        raw_codes = [code.strip() for code in options["fund_codes"].split(",") if code.strip()]
        if raw_codes:
            return raw_codes

        queryset = FundInfoModel._default_manager.filter(is_active=True)

        raw_types = [item.strip() for item in options["fund_types"].split(",") if item.strip()]
        if raw_types:
            queryset = queryset.filter(fund_type__in=raw_types)

        max_funds = max(int(options["max_funds"]), 1)
        return list(
            queryset.order_by("-fund_scale", "fund_code").values_list("fund_code", flat=True)[:max_funds]
        )

    def _parse_date(self, value: str, *, default: date) -> date:
        if not value:
            return default
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CommandError(f"Invalid date: {value}") from exc
