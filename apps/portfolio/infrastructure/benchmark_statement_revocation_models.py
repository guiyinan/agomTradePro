"""Permanent owner withdrawal of a previously certified original custody statement."""

from django.db import models

from apps.portfolio.infrastructure.policy_benchmark_daily_valuation_models import (
    PortfolioBenchmarkDailyValuationModel,
    _ImmutableValuation,
)


class BenchmarkStatementRevocationModel(_ImmutableValuation):
    """One terminal withdrawal per exact certified day, retaining the owner's original hash."""

    day = models.OneToOneField(PortfolioBenchmarkDailyValuationModel, on_delete=models.PROTECT)
    original_hash = models.CharField(max_length=64)
    owner_user_id = models.PositiveBigIntegerField()
    recorded_at = models.DateTimeField()

    class Meta(_ImmutableValuation.Meta):
        app_label = "portfolio"
        db_table = "portfolio_benchmark_statement_revocation"
