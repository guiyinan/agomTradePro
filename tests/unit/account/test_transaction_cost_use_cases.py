"""Regression tests for account transaction-cost application use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.account.application.transaction_cost_use_cases import (
    RecordTransactionCostUseCase,
    TransactionCostAnalysisUseCase,
    TransactionCostEstimationUseCase,
)


class _AssetMetadataRepository:
    def get_asset_by_code(self, asset_code: str) -> dict[str, object] | None:
        return {
            "asset_code": asset_code,
            "name": "Test asset",
            "asset_class": "equity",
            "region": "CN",
            "cross_border": False,
            "style": "blend",
        }


class _TransactionCostConfigRepository:
    def get_cost_config(
        self, market: str, asset_class: str
    ) -> dict[str, object] | None:
        return {
            "market": market,
            "asset_class": asset_class,
            "commission_rate": Decimal("0.0003"),
            "slippage_rate": Decimal("0.0002"),
            "stamp_duty_rate": Decimal("0.001"),
            "transfer_fee_rate": Decimal("0.00001"),
            "min_commission": Decimal("5"),
            "cost_warning_threshold": 0.005,
        }

    def get_default_cost_config(
        self, market: str, asset_class: str
    ) -> dict[str, object]:
        raise AssertionError("specific test configuration should be used")


class _TransactionRepository:
    def __init__(self, transactions: list[dict[str, object]] | None = None) -> None:
        self.transactions = transactions or []
        self.updated_costs: dict[str, object] | None = None
        self.update_result: dict[str, object] | None = None

    def update_transaction_costs(
        self,
        transaction_id: int,
        *,
        commission: Decimal,
        slippage: Decimal | None = None,
        stamp_duty: Decimal | None = None,
        transfer_fee: Decimal | None = None,
    ) -> dict[str, object] | None:
        self.updated_costs = {
            "transaction_id": transaction_id,
            "commission": commission,
            "slippage": slippage,
            "stamp_duty": stamp_duty,
            "transfer_fee": transfer_fee,
        }
        return self.update_result

    def list_user_transaction_costs(
        self,
        user_id: int,
        *,
        portfolio_id: int | None = None,
        since_date: datetime | None = None,
    ) -> list[dict[str, object]]:
        assert user_id == 7
        assert portfolio_id == 11
        assert since_date is not None
        return self.transactions


def _transaction(
    *,
    transaction_id: int,
    notional: Decimal,
    commission: Decimal,
    estimated_cost: Decimal | None,
    cost_variance_pct: float | None,
) -> dict[str, object]:
    return {
        "id": transaction_id,
        "portfolio_id": 11,
        "position_id": None,
        "asset_code": "000001.SH",
        "action": "sell",
        "notional": notional,
        "commission": commission,
        "slippage": None,
        "stamp_duty": None,
        "transfer_fee": None,
        "estimated_cost": estimated_cost,
        "cost_variance": None,
        "cost_variance_pct": cost_variance_pct,
        "traded_at": datetime(2026, 7, 22, tzinfo=UTC),
    }


def test_estimate_transaction_cost_returns_typed_breakdown() -> None:
    use_case = TransactionCostEstimationUseCase(
        asset_meta_repo=_AssetMetadataRepository(),
        transaction_cost_config_repo=_TransactionCostConfigRepository(),
    )

    estimate = use_case.estimate_transaction_cost(
        asset_code="000001.SH",
        shares=100,
        price=Decimal("10"),
        action="sell",
        user_id=7,
    )

    assert estimate.market == "CN_A_SHARE"
    assert estimate.trade_value == Decimal("1000")
    assert estimate.commission == Decimal("5")
    assert estimate.slippage == Decimal("0.2")
    assert estimate.stamp_duty == Decimal("1")
    assert estimate.transfer_fee == Decimal("0.01000")
    assert estimate.total_cost == Decimal("6.21000")
    assert estimate.cost_ratio == pytest.approx(0.00621)
    assert estimate.exceeds_threshold is True


def test_estimate_transaction_cost_rejects_unknown_action() -> None:
    use_case = TransactionCostEstimationUseCase(
        asset_meta_repo=_AssetMetadataRepository(),
        transaction_cost_config_repo=_TransactionCostConfigRepository(),
    )

    with pytest.raises(ValueError, match="交易方向"):
        use_case.estimate_transaction_cost(
            asset_code="000001.SH",
            shares=100,
            price=Decimal("10"),
            action="hold",
            user_id=7,
        )


def test_record_actual_cost_raises_when_transaction_is_missing() -> None:
    repository = _TransactionRepository()
    use_case = RecordTransactionCostUseCase(transaction_repo=repository)

    with pytest.raises(ValueError, match="交易 99 不存在"):
        use_case.record_actual_cost(
            transaction_id=99,
            actual_commission=Decimal("5"),
        )

    assert repository.updated_costs == {
        "transaction_id": 99,
        "commission": Decimal("5"),
        "slippage": None,
        "stamp_duty": None,
        "transfer_fee": None,
    }


def test_analyze_transaction_costs_uses_mapping_fields_and_positive_notional_count() -> None:
    repository = _TransactionRepository(
        transactions=[
            _transaction(
                transaction_id=1,
                notional=Decimal("1000"),
                commission=Decimal("5"),
                estimated_cost=Decimal("5"),
                cost_variance_pct=0.0,
            ),
            _transaction(
                transaction_id=2,
                notional=Decimal("100"),
                commission=Decimal("2"),
                estimated_cost=Decimal("2.5"),
                cost_variance_pct=-0.2,
            ),
            _transaction(
                transaction_id=3,
                notional=Decimal("0"),
                commission=Decimal("0"),
                estimated_cost=None,
                cost_variance_pct=None,
            ),
        ]
    )
    use_case = TransactionCostAnalysisUseCase(transaction_repo=repository)

    analysis = use_case.analyze_user_transaction_costs(
        user_id=7,
        portfolio_id=11,
        days=30,
    )

    assert analysis.total_transactions == 3
    assert analysis.total_traded_value == Decimal("1100")
    assert analysis.total_actual_cost == Decimal("7")
    assert analysis.total_estimated_cost == Decimal("7.5")
    assert analysis.estimation_accuracy == pytest.approx(0.5)
    assert analysis.avg_cost_ratio == pytest.approx((0.005 + 0.02) / 2)
    assert analysis.high_cost_transactions == [
        {
            "id": 2,
            "asset_code": "000001.SH",
            "action": "sell",
            "notional": 100.0,
            "cost_ratio": 0.02,
            "traded_at": datetime(2026, 7, 22, tzinfo=UTC),
        }
    ]
