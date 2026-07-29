from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.equity.application.use_cases_valuation_sync import (
    BackfillEquityValuationRequest,
    BackfillEquityValuationUseCase,
)
from apps.equity.infrastructure.repositories import DjangoStockRepository


class Command(BaseCommand):
    help = "Backfill historical equity valuation data."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register bounded historical backfill options."""

        parser.add_argument("--years", type=int, default=3)
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args: Any, **options: Any) -> None:
        """Backfill a validated historical valuation window."""

        years = options.get("years")
        batch_size = options.get("batch_size")
        if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 30:
            raise CommandError("years must be an integer between 1 and 30")
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or not 1 <= batch_size <= 5000
        ):
            raise CommandError("batch-size must be an integer between 1 and 5000")
        use_case = BackfillEquityValuationUseCase(stock_repository=DjangoStockRepository())
        response = use_case.execute(
            BackfillEquityValuationRequest(
                years=years,
                batch_size=batch_size,
            )
        )
        if not response.success:
            raise CommandError("Equity valuation backfill failed")

        self.stdout.write(self.style.SUCCESS("Equity valuation backfill completed"))
        self.stdout.write(str(response.data))
