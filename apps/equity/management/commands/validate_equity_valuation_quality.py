from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

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

    def add_arguments(self, parser: CommandParser) -> None:
        """Register valuation quality validation options."""

        parser.add_argument("--date", type=str, default=None)
        parser.add_argument("--primary-source", type=str, default="akshare")

    def handle(self, *args: Any, **options: Any) -> None:
        """Validate valuation quality for one optional evidence date."""

        raw_date = options.get("date")
        if raw_date is not None and not isinstance(raw_date, str):
            raise CommandError("date must use YYYY-MM-DD format")
        try:
            as_of_date = date.fromisoformat(raw_date) if raw_date else None
        except ValueError as exc:
            raise CommandError("date must use YYYY-MM-DD format") from exc
        primary_source = options.get("primary_source")
        if not isinstance(primary_source, str):
            raise CommandError("primary-source must be text")
        use_case = ValidateEquityValuationQualityUseCase(
            stock_repository=DjangoStockRepository(),
            quality_repository=DjangoValuationDataQualityRepository(),
        )
        response = use_case.execute(
            ValidateEquityValuationQualityRequest(
                as_of_date=as_of_date,
                primary_source=primary_source,
            )
        )
        if not response.success:
            raise CommandError("Equity valuation quality validation failed")

        self.stdout.write(self.style.SUCCESS("Equity valuation quality validation completed"))
        self.stdout.write(str(response.data))
