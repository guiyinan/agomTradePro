"""Volatility adjustment application boundary tests."""

from datetime import date
from decimal import Decimal

import pytest

from apps.account.application.volatility_use_cases import (
    VolatilityAdjustmentUseCase,
    VolatilityAnalysisOutput,
)
from apps.account.domain.services import (
    VolatilityAdjustmentResult,
)


class FakeAnalysisUseCase:
    """Return a deterministic reduction assessment."""

    def analyze_portfolio_volatility(
        self,
        portfolio_id: int,
        user_id: int,
    ) -> VolatilityAnalysisOutput:
        return VolatilityAnalysisOutput(
            portfolio_id=portfolio_id,
            current_volatility_30d=0.3,
            current_volatility_60d=0.3,
            current_volatility_90d=0.3,
            target_volatility=0.15,
            adjustment_result=VolatilityAdjustmentResult(
                current_volatility=0.3,
                target_volatility=0.15,
                volatility_ratio=2.0,
                should_reduce=True,
                suggested_position_multiplier=0.5,
                reduction_reason="test reduction",
            ),
            volatility_history=[],
            as_of_date=date(2026, 7, 24),
        )


class FakePositionRepository:
    """Capture the atomic batch call made by the use case."""

    def __init__(self, price: Decimal, status: str = "executed") -> None:
        self.price = price
        self.status = status
        self.calls = []

    def list_open_positions_for_adjustment(self, portfolio_id: int):
        return [
            {
                "id": 7,
                "asset_code": "600000.SH",
                "shares": 100.0,
                "current_price": self.price,
                "avg_cost": Decimal("10"),
            }
        ]

    def execute_volatility_reduction(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": self.status,
            "reduced_positions": (
                []
                if self.status == "already_executed"
                else [{"asset_code": "600000.SH", "shares_reduced": 50.0}]
            ),
        }


def test_invalid_execution_price_stops_before_repository_write() -> None:
    repository = FakePositionRepository(Decimal("0"))
    use_case = VolatilityAdjustmentUseCase(
        position_repo=repository,
        analysis_use_case=FakeAnalysisUseCase(),
    )

    with pytest.raises(ValueError, match="数量或价格无效"):
        use_case.execute_volatility_adjustment(portfolio_id=1, user_id=2)

    assert repository.calls == []


def test_repeated_batch_is_reported_without_claiming_reductions() -> None:
    repository = FakePositionRepository(Decimal("12"), status="already_executed")
    use_case = VolatilityAdjustmentUseCase(
        position_repo=repository,
        analysis_use_case=FakeAnalysisUseCase(),
    )

    first_result = use_case.execute_volatility_adjustment(portfolio_id=1, user_id=2)
    second_result = use_case.execute_volatility_adjustment(portfolio_id=1, user_id=2)

    assert first_result["status"] == "already_executed"
    assert first_result["reduced_positions"] == []
    assert repository.calls[0]["idempotency_key"] == repository.calls[1]["idempotency_key"]
    assert second_result["status"] == "already_executed"
