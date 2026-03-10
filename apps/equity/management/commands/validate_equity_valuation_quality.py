from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.equity.application.use_cases_valuation_sync import (
    ValidateEquityValuationQualityRequest,
    ValidateEquityValuationQualityUseCase,
)
from apps.equity.infrastructure.repositories import (
    DjangoStockRepository,
    DjangoValuationDataQualityRepository,
)


class Command(BaseCommand):
    help = "Validate local equity valuation data quality and persist gate snapshot."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, default=None)
        parser.add_argument("--primary-source", type=str, default="akshare")

    def handle(self, *args, **options):
        as_of_date = date.fromisoformat(options["date"]) if options["date"] else None
        use_case = ValidateEquityValuationQualityUseCase(
            stock_repository=DjangoStockRepository(),
            quality_repository=DjangoValuationDataQualityRepository(),
        )
        response = use_case.execute(
            ValidateEquityValuationQualityRequest(
                as_of_date=as_of_date,
                primary_source=options["primary_source"],
            )
        )
        if not response.success:
            raise CommandError(response.error)

        self.stdout.write(self.style.SUCCESS("Equity valuation quality validation completed"))
        self.stdout.write(str(response.data))
