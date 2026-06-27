from apps.risk_center.application.trade_guard import EvaluatePreTradeRiskUseCase


class _FakeResolver:
    def __init__(self, parameters):
        self.parameters = parameters

    def execute(self, *, account_id: int):
        return {
            "account_id": account_id,
            "parameters": self.parameters,
            "sources": {},
            "floor_applied": [],
            "exceptions_applied": [],
        }


def test_pre_trade_guard_allows_buy_within_effective_limits():
    guard = EvaluatePreTradeRiskUseCase(
        resolver=_FakeResolver(
            {
                "max_total_position_pct": 0.8,
                "max_single_position_pct": 0.25,
                "min_cash_pct": 0.1,
                "hard_exclusions": [],
            }
        )
    )

    result = guard.execute(
        account_id=1,
        symbol="000001.SZ",
        side="buy",
        quantity=100,
        price=10.0,
        account_equity=10000.0,
        total_position_value=5000.0,
        cash_balance=5000.0,
    )

    assert result.passed is True
    assert result.violations == []
    assert result.metrics["projected_total_position_pct"] == 0.6


def test_pre_trade_guard_rejects_hard_exclusion_and_limit_breaks():
    guard = EvaluatePreTradeRiskUseCase(
        resolver=_FakeResolver(
            {
                "max_total_position_pct": 0.55,
                "max_single_position_pct": 0.05,
                "min_cash_pct": 0.5,
                "hard_exclusions": ["000001.SZ"],
            }
        )
    )

    result = guard.execute(
        account_id=1,
        symbol="000001.SZ",
        side="buy",
        quantity=100,
        price=10.0,
        account_equity=10000.0,
        total_position_value=5000.0,
        cash_balance=5000.0,
    )

    assert result.passed is False
    assert any("hard exclusions" in item for item in result.violations)
    assert any("max_total_position_pct" in item for item in result.violations)
    assert any("max_single_position_pct" in item for item in result.violations)
    assert any("min_cash_pct" in item for item in result.violations)


def test_pre_trade_guard_sell_does_not_apply_buy_exposure_limits():
    guard = EvaluatePreTradeRiskUseCase(
        resolver=_FakeResolver(
            {
                "max_total_position_pct": 0.1,
                "max_single_position_pct": 0.1,
                "min_cash_pct": 0.9,
                "hard_exclusions": [],
            }
        )
    )

    result = guard.execute(
        account_id=1,
        symbol="000001.SZ",
        side="sell",
        quantity=100,
        price=10.0,
        account_equity=10000.0,
        total_position_value=9000.0,
        cash_balance=1000.0,
        current_symbol_position_value=1000.0,
    )

    assert result.passed is True
    assert result.violations == []
