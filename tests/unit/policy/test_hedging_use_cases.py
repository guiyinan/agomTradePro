from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from apps.policy.application.hedging_use_cases import (
    ExecuteHedgingUseCase,
    HedgeCalculationResult,
    HedgeEffectivenessAnalyzer,
)


@dataclass
class _FakeRealtimePrice:
    price: Decimal


class _FakeRealtimePriceRepository:
    def __init__(self, price: Decimal):
        self.price = price

    def get_latest_price(self, instrument_code: str):
        return _FakeRealtimePrice(price=self.price)


class _FakeHedgeRepository:
    def __init__(self):
        self.created_payloads: list[dict] = []
        self.updated_metrics: list[dict] = []
        self.hedge_snapshot: dict | None = None

    def create_hedge_position(self, **payload):
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

    def get_hedge_position(self, *, hedge_id: int, portfolio_id: int):
        return self.hedge_snapshot

    def update_beta_metrics(self, *, hedge_id: int, beta_before: float, beta_after: float):
        self.updated_metrics.append(
            {
                "hedge_id": hedge_id,
                "beta_before": beta_before,
                "beta_after": beta_after,
            }
        )
        return True


class _FakeAccountPositionRepository:
    def __init__(self, positions: list[dict]):
        self.positions = positions

    def list_portfolio_position_weights(self, portfolio_id: int):
        return self.positions


def test_execute_hedge_uses_repositories(monkeypatch):
    hedge_repo = _FakeHedgeRepository()
    monkeypatch.setattr(
        "apps.policy.application.hedging_use_cases.get_hedge_position_repository",
        lambda: hedge_repo,
    )
    monkeypatch.setattr(
        "apps.policy.application.hedging_use_cases.get_realtime_price_repository",
        lambda: _FakeRealtimePriceRepository(Decimal("5123.4")),
    )

    use_case = ExecuteHedgingUseCase()
    result = use_case.execute_hedge(
        portfolio_id=7,
        user_id=1,
        calculation=HedgeCalculationResult(
            should_hedge=True,
            hedge_ratio=0.5,
            hedge_value=Decimal("100000"),
            recommended_instrument="IF2312",
            estimated_cost=Decimal("50"),
            reason="policy hedge",
        ),
    )

    assert result is not None
    assert result.hedge_id == 42
    assert result.execution_price == Decimal("5123.4")
    assert hedge_repo.created_payloads[0]["status"] == "executed"
    assert hedge_repo.created_payloads[0]["instrument_type"] == "future"


def test_analyze_hedge_effectiveness_updates_missing_beta(monkeypatch):
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
    monkeypatch.setattr(
        "apps.policy.application.hedging_use_cases.get_hedge_position_repository",
        lambda: hedge_repo,
    )
    monkeypatch.setattr(
        "apps.policy.application.hedging_use_cases.get_account_position_repository",
        lambda: _FakeAccountPositionRepository(
            [{"asset_code": "000001.SH", "weight": 1.0}]
        ),
    )

    analyzer = HedgeEffectivenessAnalyzer()
    result = analyzer.analyze_hedge_effectiveness(portfolio_id=3, hedge_id=9)

    assert result["beta_before"] == 1.0
    assert result["beta_after"] == 0.6
    assert result["hedge_cost"] == 25.0
    assert result["hedge_benefit"] == 120.0
    assert result["net_benefit"] == 95.0
    assert hedge_repo.updated_metrics == [
        {"hedge_id": 9, "beta_before": 1.0, "beta_after": 0.6}
    ]
