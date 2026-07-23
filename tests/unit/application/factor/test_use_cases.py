"""Tests for factor application use cases."""

from datetime import date

from apps.factor.application.dtos import FactorCalculationRequest
from apps.factor.application.use_cases import (
    CalculateFactorScoresUseCase,
    FactorUseCaseContext,
)


def test_calculate_factor_scores_accepts_empty_factor_selection() -> None:
    """An empty factor selection produces no scores instead of dividing by zero."""

    context = FactorUseCaseContext(
        trade_date=date(2026, 7, 24),
        universe=[],
        get_factor_value=lambda _stock, _factor, _trade_date: None,
        get_stock_info=lambda _stock: None,
        get_factor_definitions=lambda: [],
    )

    result = CalculateFactorScoresUseCase(context).execute(
        FactorCalculationRequest(
            trade_date=context.trade_date,
            universe=[],
            factor_codes=[],
        )
    )

    assert result == []
