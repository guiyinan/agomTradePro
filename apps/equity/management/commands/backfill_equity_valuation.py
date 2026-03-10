from django.core.management.base import BaseCommand, CommandError

from apps.equity.application.use_cases_valuation_sync import (
    BackfillEquityValuationRequest,
    BackfillEquityValuationUseCase,
)
from apps.equity.infrastructure.repositories import DjangoStockRepository


class Command(BaseCommand):
    help = "Backfill historical equity valuation data."

    def add_arguments(self, parser):
        parser.add_argument("--years", type=int, default=3)
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        use_case = BackfillEquityValuationUseCase(stock_repository=DjangoStockRepository())
        response = use_case.execute(
            BackfillEquityValuationRequest(
                years=options["years"],
                batch_size=options["batch_size"],
            )
        )
        if not response.success:
            raise CommandError(response.error)

        self.stdout.write(self.style.SUCCESS("Equity valuation backfill completed"))
        self.stdout.write(str(response.data))
