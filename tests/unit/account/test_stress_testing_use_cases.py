"""Behavior contracts for account historical stress testing."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from apps.account.application.stress_testing_use_cases import (
    HistoricalScenarioService,
    StressTestingUseCase,
    VaRService,
)


class _PositionRepo:
    def __init__(self, positions: list[dict[str, object]]) -> None:
        self.positions = positions

    def list_portfolio_position_weights(self, portfolio_id: int) -> list[dict[str, object]]:
        assert portfolio_id == 7
        return self.positions


class _PriceAdapter:
    def fetch_daily_data(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        assert start_date <= end_date
        multiplier = 1.0 if asset_code == "000001.SZ" else -1.0
        return pd.DataFrame(
            [
                {"trade_date": pd.Timestamp("2015-06-12"), "pct_chg": -10.0 * multiplier},
                {"trade_date": pd.Timestamp("2015-06-15"), "pct_chg": 5.0 * multiplier},
            ]
        )


def test_historical_stress_scenario_aggregates_weighted_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.account.application.business_provider_gateway.get_tushare_stock_adapter",
        lambda: _PriceAdapter(),
    )
    use_case = StressTestingUseCase(
        _PositionRepo(
            [
                {"asset_code": "000001.SZ", "weight": 0.75},
                {"asset_code": "000002.SZ", "weight": 0.25},
            ]
        )
    )

    result = use_case.run_historical_scenario_test(7, "2015_crash")

    assert result.scenario_name == "2015股灾"
    assert result.initial_value == Decimal("1000000")
    assert result.final_value > 0
    assert result.max_drawdown > 0
    assert result.volatility > 0
    assert result.var_95 <= result.var_99


def test_stress_testing_rejects_unknown_empty_and_unavailable_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_case = StressTestingUseCase(_PositionRepo([]))
    with pytest.raises(ValueError, match="不存在"):
        use_case.run_historical_scenario_test(7, "missing")
    with pytest.raises(ValueError, match="没有持仓"):
        use_case.run_historical_scenario_test(7, "2015_crash")

    monkeypatch.setattr(
        "apps.account.application.business_provider_gateway.get_tushare_stock_adapter",
        lambda: SimpleNamespace(fetch_daily_data=lambda *args, **kwargs: pd.DataFrame()),
    )
    unavailable = StressTestingUseCase(_PositionRepo([{"asset_code": "000001.SZ", "weight": 1.0}]))
    with pytest.raises(ValueError, match="无法获取"):
        unavailable.run_historical_scenario_test(7, "2015_crash")


def test_var_drawdown_scenarios_and_recommendation_boundaries() -> None:
    assert VaRService.calculate_historical_var([]) == 0.0
    assert VaRService.calculate_historical_var([-0.5, -0.2, 0.1], 0.95) == -0.5
    assert VaRService.calculate_max_drawdown([]) == (0.0, 0)
    drawdown, recovery = VaRService.calculate_max_drawdown([100.0, 80.0, 70.0, 110.0])
    assert drawdown == pytest.approx(0.3)
    assert recovery == 3

    recommendations = StressTestingUseCase._generate_recommendations(
        Decimal("-0.25"),
        0.35,
        0.04,
    )
    assert len(recommendations) == 4
    assert StressTestingUseCase._generate_recommendations(
        Decimal("0.10"),
        0.05,
        0.01,
    ) == ["组合在该场景下表现尚可，继续保持当前策略"]
    assert HistoricalScenarioService.get_scenario("2020_covid") is not None
    assert len(HistoricalScenarioService.get_all_scenarios()) == 3


def test_run_all_scenarios_preserves_catalog_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_case = StressTestingUseCase(_PositionRepo([]))
    monkeypatch.setattr(
        use_case,
        "run_historical_scenario_test",
        lambda portfolio_id, scenario_id: (portfolio_id, scenario_id),
    )

    results = use_case.run_all_scenarios(7)

    assert results == [
        (7, "2015_crash"),
        (7, "2020_covid"),
        (7, "2018_trade_war"),
    ]
