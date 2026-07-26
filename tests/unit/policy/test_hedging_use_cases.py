from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.policy.application.hedging_use_cases import (
    CalculateHedgeUseCase,
    ExecuteHedgingUseCase,
    HedgeCalculationResult,
    HedgeEffectivenessAnalyzer,
)
from apps.policy.domain.entities import PolicyLevel
from apps.policy.domain.hedging import HedgePolicyConfig, HedgeRule


@dataclass
class _FakeRealtimePrice:
    price: object


class _FakeRealtimePriceRepository:
    def __init__(self, price: object):
        self.price = price

    def get_latest_price(self, instrument_code: str) -> _FakeRealtimePrice:
        return _FakeRealtimePrice(price=self.price)


class _FakeHedgeRepository:
    def __init__(self) -> None:
        self.created_payloads: list[dict[str, object]] = []
        self.updated_metrics: list[dict[str, float | int]] = []
        self.hedge_snapshot: dict[str, object] | None = None

    def create_hedge_position(self, **payload: object) -> dict[str, object]:
        self.created_payloads.append(payload)
        return {
            "id": 42,
            "instrument_code": payload["instrument_code"],
            "hedge_ratio": payload["hedge_ratio"],
            "hedge_value": payload["hedge_value"],
            "execution_price": payload.get("execution_price"),
            "status": payload["status"],
            "executed_at": payload.get("executed_at"),
        }

    def get_hedge_position(self, *, hedge_id: int, portfolio_id: int) -> dict[str, object] | None:
        return self.hedge_snapshot

    def update_beta_metrics(
        self,
        *,
        hedge_id: int,
        portfolio_id: int,
        beta_before: float,
        beta_after: float,
    ) -> bool:
        self.updated_metrics.append(
            {
                "hedge_id": hedge_id,
                "portfolio_id": portfolio_id,
                "beta_before": beta_before,
                "beta_after": beta_after,
            }
        )
        return True


class _FakeAccountPositionRepository:
    def __init__(
        self,
        positions: list[dict[str, object]],
        *,
        owns_portfolio: bool = True,
    ) -> None:
        self.positions = positions
        self.owns_portfolio = owns_portfolio

    def user_owns_portfolio(self, *, portfolio_id: int, user_id: int) -> bool:
        return self.owns_portfolio

    def list_portfolio_position_weights(self, portfolio_id: int) -> list[dict[str, object]]:
        return self.positions


def _hedge_calculation() -> HedgeCalculationResult:
    return HedgeCalculationResult(
        should_hedge=True,
        policy_level=PolicyLevel.P2,
        hedge_ratio=0.5,
        hedge_value=Decimal("100000"),
        recommended_instrument="IF-CURRENT",
        instrument_type="future",
        estimated_cost=Decimal("50"),
        reason="policy hedge",
    )


def test_calculate_hedge_uses_injected_policy_configuration() -> None:
    config = HedgePolicyConfig(
        rules=(
            (
                PolicyLevel.P2,
                HedgeRule(
                    ratio=Decimal("0.4"),
                    instrument_code="IF-CURRENT",
                    instrument_type="future",
                    estimated_cost_rate=Decimal("0.0007"),
                ),
            ),
        )
    )

    result = CalculateHedgeUseCase(config).calculate_hedge_requirement(
        portfolio_id=7,
        policy_level="P2",
        portfolio_value=Decimal("1000000"),
        equity_exposure=Decimal("500000"),
    )

    assert result.hedge_ratio == 0.4
    assert result.hedge_value == Decimal("200000.0")
    assert result.estimated_cost == Decimal("140.00000")
    assert result.recommended_instrument == "IF-CURRENT"


def test_calculate_hedge_rejects_unknown_policy_and_invalid_financial_values() -> None:
    config = HedgePolicyConfig(rules=())
    use_case = CalculateHedgeUseCase(config)

    with pytest.raises(ValueError, match="unsupported policy level"):
        use_case.calculate_hedge_requirement(
            portfolio_id=7,
            policy_level="UNKNOWN",
            portfolio_value=Decimal("100"),
            equity_exposure=Decimal("50"),
        )
    with pytest.raises(ValueError, match="within portfolio value"):
        use_case.calculate_hedge_requirement(
            portfolio_id=7,
            policy_level="P2",
            portfolio_value=Decimal("100"),
            equity_exposure=Decimal("101"),
        )


def test_execute_hedge_uses_repositories() -> None:
    hedge_repo = _FakeHedgeRepository()
    use_case = ExecuteHedgingUseCase(
        hedge_repository=hedge_repo,
        account_position_repository=_FakeAccountPositionRepository([]),
        price_repository=_FakeRealtimePriceRepository(Decimal("5123.4")),
    )
    result = use_case.execute_hedge(
        portfolio_id=7,
        user_id=1,
        calculation=_hedge_calculation(),
    )

    assert result is not None
    assert result.hedge_id == 42
    assert result.execution_price == Decimal("5123.4")
    assert hedge_repo.created_payloads[0]["status"] == "executed"
    assert hedge_repo.created_payloads[0]["instrument_type"] == "future"
    assert hedge_repo.created_payloads[0]["policy_level"] == "P2"


def test_execute_hedge_rejects_cross_user_and_missing_price_without_writing() -> None:
    hedge_repo = _FakeHedgeRepository()
    denied = ExecuteHedgingUseCase(
        hedge_repository=hedge_repo,
        account_position_repository=_FakeAccountPositionRepository(
            [],
            owns_portfolio=False,
        ),
        price_repository=_FakeRealtimePriceRepository(Decimal("5000")),
    )
    with pytest.raises(PermissionError, match="not owned"):
        denied.execute_hedge(7, 2, _hedge_calculation())

    unavailable = ExecuteHedgingUseCase(
        hedge_repository=hedge_repo,
        account_position_repository=_FakeAccountPositionRepository([]),
        price_repository=_FakeRealtimePriceRepository(float("nan")),
    )
    with pytest.raises(RuntimeError, match="price is unavailable"):
        unavailable.execute_hedge(7, 1, _hedge_calculation())

    assert hedge_repo.created_payloads == []


def test_analyze_hedge_effectiveness_updates_missing_beta() -> None:
    hedge_repo = _FakeHedgeRepository()
    hedge_repo.hedge_snapshot = {
        "id": 9,
        "portfolio_id": 3,
        "instrument_code": "IF2312",
        "instrument_type": "future",
        "hedge_ratio": 0.4,
        "hedge_value": Decimal("50000"),
        "policy_level": "P2",
        "status": "executed",
        "execution_price": Decimal("5000"),
        "executed_at": datetime.now(UTC),
        "opening_cost": Decimal("20"),
        "closing_cost": Decimal("5"),
        "total_cost": None,
        "beta_before": None,
        "beta_after": None,
        "hedge_profit": Decimal("120"),
        "notes": "test",
    }
    analyzer = HedgeEffectivenessAnalyzer(
        hedge_repository=hedge_repo,
        account_position_repository=_FakeAccountPositionRepository(
            [{"asset_code": "000001.SH", "weight": 1.0}]
        ),
    )
    result = analyzer.analyze_hedge_effectiveness(portfolio_id=3, hedge_id=9, user_id=1)

    assert result["beta_before"] == 1.0
    assert result["beta_after"] == 0.6
    assert result["hedge_cost"] == 25.0
    assert result["hedge_benefit"] == 120.0
    assert result["net_benefit"] == 95.0
    assert hedge_repo.updated_metrics == [
        {
            "hedge_id": 9,
            "portfolio_id": 3,
            "beta_before": 1.0,
            "beta_after": 0.6,
        }
    ]


def test_analyze_hedge_effectiveness_rejects_non_finite_metrics() -> None:
    hedge_repo = _FakeHedgeRepository()
    hedge_repo.hedge_snapshot = {
        "total_cost": Decimal("NaN"),
        "hedge_profit": Decimal("1"),
        "beta_before": 1.0,
        "beta_after": 0.5,
    }
    analyzer = HedgeEffectivenessAnalyzer(
        hedge_repository=hedge_repo,
        account_position_repository=_FakeAccountPositionRepository([]),
    )

    with pytest.raises(ValueError, match="total_cost must be finite"):
        analyzer.analyze_hedge_effectiveness(portfolio_id=3, hedge_id=9, user_id=1)

    hedge_repo.hedge_snapshot["total_cost"] = Decimal("-1")
    with pytest.raises(ValueError, match="total_cost must be non-negative"):
        analyzer.analyze_hedge_effectiveness(portfolio_id=3, hedge_id=9, user_id=1)


def test_analyze_hedge_effectiveness_rejects_cross_user_access() -> None:
    analyzer = HedgeEffectivenessAnalyzer(
        hedge_repository=_FakeHedgeRepository(),
        account_position_repository=_FakeAccountPositionRepository(
            [],
            owns_portfolio=False,
        ),
    )

    with pytest.raises(PermissionError, match="not owned"):
        analyzer.analyze_hedge_effectiveness(portfolio_id=3, hedge_id=9, user_id=2)
