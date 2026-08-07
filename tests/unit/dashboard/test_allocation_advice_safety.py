"""Safety coverage for Dashboard-to-Strategy allocation advice inputs."""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.account.domain.entities import (
    AccountProfile,
    AssetClassType,
    CrossBorderFlag,
    Position,
    PositionSource,
    PositionStatus,
    Region,
    RiskTolerance,
)
from apps.dashboard.application.use_cases import GetDashboardDataUseCase
from apps.strategy.application.allocation_service import AllocationService


def _use_case() -> GetDashboardDataUseCase:
    return object.__new__(GetDashboardDataUseCase)


def _profile() -> AccountProfile:
    return AccountProfile(
        user_id=1,
        display_name="tester",
        initial_capital=Decimal("1000"),
        risk_tolerance=RiskTolerance.MODERATE,
        created_at=datetime.now(UTC),
    )


def _position(
    *,
    asset_code: str = "510300.SH",
    market_value: Decimal = Decimal("600"),
    asset_class: AssetClassType = AssetClassType.EQUITY,
) -> Position:
    return Position(
        id=1,
        portfolio_id=1,
        user_id=1,
        asset_code=asset_code,
        shares=6.0,
        avg_cost=Decimal("100"),
        current_price=Decimal("100"),
        market_value=market_value,
        unrealized_pnl=Decimal("0"),
        unrealized_pnl_pct=0.0,
        opened_at=datetime.now(UTC),
        status=PositionStatus.ACTIVE,
        source=PositionSource.MANUAL,
        source_id=None,
        asset_class=asset_class,
        region=Region.CN,
        cross_border=CrossBorderFlag.DOMESTIC,
    )


@pytest.mark.parametrize("total_assets", [True, float("nan"), float("inf"), -1.0])
def test_invalid_total_assets_fail_before_strategy_call(
    total_assets: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def unexpected_call(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(
        AllocationService,
        "calculate_allocation_advice",
        staticmethod(unexpected_call),
    )

    result = _use_case()._generate_allocation_advice(
        current_regime="Recovery",
        policy_level="P0",
        profile=_profile(),
        total_assets=total_assets,
        positions=[_position()],
    )

    assert result is None
    assert calls == []


@pytest.mark.parametrize(
    "position",
    [
        _position(asset_code="bad code"),
        _position(market_value=Decimal("-1")),
        _position(market_value=Decimal("Infinity")),
        _position(asset_class=AssetClassType.FUND),
    ],
)
def test_invalid_position_fails_closed(position: Position) -> None:
    result = _use_case()._generate_allocation_advice(
        current_regime="Recovery",
        policy_level="P0",
        profile=_profile(),
        total_assets=1000.0,
        positions=[position],
    )

    assert result is None


def test_invested_value_cannot_exceed_total_assets() -> None:
    result = _use_case()._generate_allocation_advice(
        current_regime="Recovery",
        policy_level="P0",
        profile=_profile(),
        total_assets=500.0,
        positions=[_position(market_value=Decimal("600"))],
    )

    assert result is None


def test_domain_position_is_adapted_to_strategy_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def calculate_advice(**kwargs: object) -> SimpleNamespace:
        positions = kwargs["current_positions"]
        total_assets = kwargs["total_assets"]
        assert isinstance(positions, list)
        assert isinstance(total_assets, float)
        assert total_assets == 1000.0
        current_allocation = AllocationService._calculate_current_allocation(
            positions,
            total_assets,
        )
        return SimpleNamespace(
            current_allocation=current_allocation,
            target_allocation={},
            allocation_diff={},
            trade_actions=[],
            summary="test",
            expected_return=None,
            expected_volatility=None,
            sharpe_ratio=None,
            regime="Recovery",
        )

    monkeypatch.setattr(
        AllocationService,
        "calculate_allocation_advice",
        staticmethod(calculate_advice),
    )

    result = _use_case()._generate_allocation_advice(
        current_regime="Recovery",
        policy_level="P0",
        profile=_profile(),
        total_assets=1000.0,
        positions=[_position()],
    )

    assert result is not None
    assert result["current_allocation"]["equity"] == 0.6
    assert result["current_allocation"]["cash"] == 0.4


def test_strategy_exception_details_are_not_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_strategy(**kwargs):
        del kwargs
        raise RuntimeError("allocation failed: token=secret")

    monkeypatch.setattr(
        AllocationService,
        "calculate_allocation_advice",
        staticmethod(fail_strategy),
    )

    with caplog.at_level(logging.WARNING):
        result = _use_case()._generate_allocation_advice(
            current_regime="Recovery",
            policy_level="P0",
            profile=_profile(),
            total_assets=1000.0,
            positions=[],
        )

    assert result is None
    assert "RuntimeError" in caplog.text
    assert "token=secret" not in caplog.text
