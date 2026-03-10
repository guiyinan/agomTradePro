from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from apps.equity.application.use_cases_valuation_sync import (
    SyncEquityValuationRequest,
    SyncEquityValuationUseCase,
)
from apps.equity.infrastructure.repositories import DjangoStockRepository


class Command(BaseCommand):
    help = "Sync equity valuation data from external providers."

    def add_arguments(self, parser):
        parser.add_argument("--days-back", type=int, default=1)
        parser.add_argument("--start-date", type=str, default=None)
        parser.add_argument("--end-date", type=str, default=None)
        parser.add_argument("--stock-code", action="append", dest="stock_codes")
        parser.add_argument("--primary-source", type=str, default="akshare")
        parser.add_argument("--fallback-source", type=str, default="tushare")

    def handle(self, *args, **options):
        end_date = date.fromisoformat(options["end_date"]) if options["end_date"] else date.today()
        start_date = (
            date.fromisoformat(options["start_date"])
            if options["start_date"]
            else end_date - timedelta(days=options["days_back"])
        )

        use_case = SyncEquityValuationUseCase(stock_repository=DjangoStockRepository())
        response = use_case.execute(
            SyncEquityValuationRequest(
                stock_codes=options.get("stock_codes"),
                start_date=start_date,
                end_date=end_date,
                primary_source=options["primary_source"],
                fallback_source=options["fallback_source"],
                days_back=options["days_back"],
            )
        )
        if not response.success:
            raise CommandError(response.error)

        self.stdout.write(self.style.SUCCESS("Equity valuation sync completed"))
        for key, value in response.data.items():
            self.stdout.write(f"{key}: {value}")
