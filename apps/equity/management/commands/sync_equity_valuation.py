from datetime import date, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.equity.application.use_cases_valuation_sync import (
    SyncEquityValuationRequest,
    SyncEquityValuationUseCase,
)
from apps.equity.infrastructure.repositories import DjangoStockRepository


class Command(BaseCommand):
    help = "Sync equity valuation data from external providers."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register bounded valuation synchronization options."""

        parser.add_argument("--days-back", type=int, default=1)
        parser.add_argument("--start-date", type=str, default=None)
        parser.add_argument("--end-date", type=str, default=None)
        parser.add_argument("--stock-code", action="append", dest="stock_codes")
        parser.add_argument("--primary-source", type=str, default="akshare")
        parser.add_argument("--fallback-source", type=str, default="tushare")

    def handle(self, *args: Any, **options: Any) -> None:
        """Synchronize valuation data for a validated date and stock selection."""

        days_back = options.get("days_back")
        if (
            isinstance(days_back, bool)
            or not isinstance(days_back, int)
            or not 1 <= days_back <= 3660
        ):
            raise CommandError("days-back must be an integer between 1 and 3660")
        raw_start_date = options.get("start_date")
        raw_end_date = options.get("end_date")
        if raw_start_date is not None and not isinstance(raw_start_date, str):
            raise CommandError("start-date must use YYYY-MM-DD format")
        if raw_end_date is not None and not isinstance(raw_end_date, str):
            raise CommandError("end-date must use YYYY-MM-DD format")
        try:
            end_date = date.fromisoformat(raw_end_date) if raw_end_date else date.today()
            start_date = (
                date.fromisoformat(raw_start_date)
                if raw_start_date
                else end_date - timedelta(days=days_back)
            )
        except ValueError as exc:
            raise CommandError("valuation dates must use YYYY-MM-DD format") from exc
        raw_stock_codes = options.get("stock_codes")
        if raw_stock_codes is not None and (
            not isinstance(raw_stock_codes, list)
            or not all(
                isinstance(code, str) and 0 < len(code.strip()) <= 32 for code in raw_stock_codes
            )
            or len(raw_stock_codes) > 5000
        ):
            raise CommandError("stock-code must be a list of at most 5000 bounded strings")
        stock_codes = (
            [code.strip().upper() for code in raw_stock_codes]
            if raw_stock_codes is not None
            else None
        )
        primary_source = options.get("primary_source")
        fallback_source = options.get("fallback_source")
        if not isinstance(primary_source, str) or not isinstance(fallback_source, str):
            raise CommandError("valuation sources must be text")

        use_case = SyncEquityValuationUseCase(stock_repository=DjangoStockRepository())
        response = use_case.execute(
            SyncEquityValuationRequest(
                stock_codes=stock_codes,
                start_date=start_date,
                end_date=end_date,
                primary_source=primary_source,
                fallback_source=fallback_source,
                days_back=days_back,
            )
        )
        if not response.success:
            raise CommandError("Equity valuation sync failed")

        self.stdout.write(self.style.SUCCESS("Equity valuation sync completed"))
        for key, value in (response.data or {}).items():
            self.stdout.write(f"{key}: {value}")
