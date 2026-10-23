from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.account.application.stop_loss_use_cases import (
    AutoStopLossUseCase,
    AutoTakeProfitUseCase,
    StopLossCheckOutput,
    TakeProfitCheckOutput,
)
from apps.account.domain.services import StopLossCheckResult, TakeProfitCheckResult


def _position_config() -> dict:
    return {
        "id": 7,
        "position_id": 3,
        "position": {
            "id": 3,
            "asset_code": "510300.SH",
            "shares": 200,
            "avg_cost": Decimal("100"),
            "opened_at": datetime(2026, 1, 1, tzinfo=UTC),
            "portfolio_id": 2,
            "user_id": 9,
            "user_email": "owner@example.test",
        },
    }


class _StopLossRepository:
    def __init__(self, configs: list[dict]) -> None:
        self.configs = configs
        self.read_calls: list[int | None] = []
        self.updates: list[dict] = []
        self.update_result = True

    def get_active_stop_loss_configs(self, user_id: int | None = None) -> list[dict]:
        self.read_calls.append(user_id)
        return self.configs

    def update_stop_loss_config(self, config_id: int, **kwargs: object) -> bool:
        self.updates.append({"config_id": config_id, **kwargs})
        return self.update_result


class _TakeProfitRepository:
    def __init__(self, configs: list[dict]) -> None:
        self.configs = configs
        self.read_calls: list[int | None] = []
        self.executed_tranches: list[dict] = []

    def get_active_take_profit_configs(self, user_id: int | None = None) -> list[dict]:
        self.read_calls.append(user_id)
        return self.configs


class _MarketData:
    def __init__(self, price: Decimal | None) -> None:
        self.price = price
        self.observed_at = datetime(2026, 4, 1, tzinfo=UTC)
        self.metadata = (
            None
            if price is None
            else {
                "price": price,
                "asset_code": "510300.SH",
                "source": "unified_quote",
                "timestamp": self.observed_at,
                "observed_at": self.observed_at,
                "trade_date": None,
                "requested_trade_date": None,
                "freshness": "realtime",
                "is_fallback": False,
            }
        )
        self.calls: list[str] = []
        self.scalar_calls: list[str] = []

    def get_current_price(self, asset_code: str) -> Decimal | None:
        """Keep the legacy scalar seam observable for test-first regression runs."""

        self.scalar_calls.append(asset_code)
        return self.price

    def get_price_with_metadata(self, asset_code: str) -> dict | None:
        self.calls.append(asset_code)
        return self.metadata


class _RiskPolicyProvider:
    def __init__(self, parameters: dict) -> None:
        self.parameters = parameters
        self.account_ids: list[int] = []

    def get_effective_parameters(self, account_id: int) -> dict:
        self.account_ids.append(account_id)
        return self.parameters


def test_stop_trigger_is_intent_and_never_calls_legacy_sell_writer(monkeypatch) -> None:
    config = {
        **_position_config(),
        "stop_loss_type": "fixed",
        "stop_loss_pct": 0.2,
        "trailing_stop_pct": None,
        "max_holding_days": None,
        "highest_price": Decimal("100"),
    }
    repo = _StopLossRepository([config])
    monkeypatch.setattr(
        "apps.account.application.stop_loss_use_cases.StopLossService.check_stop_loss",
        lambda **_kwargs: StopLossCheckResult(
            should_trigger=True,
            trigger_reason="stop condition",
            stop_price=90.0,
            current_price=80.0,
            unrealized_pnl_pct=-0.2,
            highest_price=100.0,
        ),
    )

    market = _MarketData(Decimal("80"))
    result = AutoStopLossUseCase(
        market_data_service=market,
        stop_loss_repo=repo,
    ).check_and_execute_stop_loss(user_id=9)

    assert len(result) == 1
    assert isinstance(result[0], StopLossCheckOutput)
    assert result[0].triggered is True
    assert result[0].execution_status == "blocked"
    assert result[0].reason_code == "legacy_automatic_exit_not_qualified"
    assert result[0].current_price == 80
    assert result[0].unrealized_pnl == Decimal("-4000.0")
    assert result[0].price_source == "unified_quote"
    assert result[0].price_observed_at == datetime(2026, 4, 1, tzinfo=UTC)
    assert result[0].price_freshness == "realtime"
    assert result[0].must_not_use_for_decision is True
    assert result[0].must_not_execute is True
    assert market.calls == ["510300.SH"]
    assert market.scalar_calls == []
    assert repo.updates == []


def test_realtime_freshness_is_trusted_without_a_local_age_budget() -> None:
    """The use case preserves producer freshness instead of inventing an age limit."""

    config = {
        **_position_config(),
        "stop_loss_type": "fixed",
        "stop_loss_pct": 0.2,
        "trailing_stop_pct": None,
        "max_holding_days": None,
        "highest_price": Decimal("100"),
    }
    market = _MarketData(Decimal("95"))
    market.observed_at = datetime(2025, 1, 1, tzinfo=UTC)
    market.metadata["observed_at"] = market.observed_at
    market.metadata["timestamp"] = market.observed_at

    result = AutoStopLossUseCase(
        market_data_service=market,
        stop_loss_repo=_StopLossRepository([config]),
    ).check_and_execute_stop_loss(user_id=9)[0]

    assert result.check_status == "evaluated"
    assert result.price_freshness == "realtime"
    assert result.price_observed_at == market.observed_at
    assert result.must_not_use_for_decision is True
    assert result.must_not_execute is True
    assert market.scalar_calls == []


def test_stop_missing_price_is_unavailable_without_synthetic_financial_values() -> None:
    config = {
        **_position_config(),
        "stop_loss_type": "fixed",
        "stop_loss_pct": 0.2,
        "trailing_stop_pct": None,
        "max_holding_days": None,
        "highest_price": Decimal("100"),
    }
    repo = _StopLossRepository([config])

    result = AutoStopLossUseCase(
        market_data_service=_MarketData(None),
        stop_loss_repo=repo,
    ).check_and_execute_stop_loss(user_id=9)

    assert len(result) == 1
    assert result[0].triggered is False
    assert result[0].check_status == "unavailable"
    assert result[0].reason_code == "market_price_unavailable"
    assert result[0].check_result is None
    assert result[0].current_price is None
    assert result[0].unrealized_pnl is None
    assert result[0].unrealized_pnl_pct is None
    assert repo.updates == []


def test_stop_malformed_position_has_no_fabricated_identity() -> None:
    """A missing position payload produces unknown identity, never zero sentinels."""

    config = {
        "id": 7,
        "position_id": 3,
        "position": None,
        "stop_loss_type": "fixed",
        "stop_loss_pct": 0.2,
        "trailing_stop_pct": None,
        "max_holding_days": None,
        "highest_price": Decimal("100"),
    }
    market = _MarketData(Decimal("80"))
    result = AutoStopLossUseCase(
        market_data_service=market,
        stop_loss_repo=_StopLossRepository([config]),
    ).check_and_execute_stop_loss(user_id=9)[0]

    assert result.check_status == "unavailable"
    assert result.position_id is None
    assert result.asset_code is None
    assert result.current_price is None
    assert result.unrealized_pnl is None
    assert market.calls == []


def test_trailing_high_water_observation_is_preserved_without_trade_write() -> None:
    config = {
        **_position_config(),
        "stop_loss_type": "trailing",
        "stop_loss_pct": 0.2,
        "trailing_stop_pct": 0.1,
        "max_holding_days": None,
        "highest_price": Decimal("100"),
        "highest_price_updated_at": datetime(2026, 4, 1, tzinfo=UTC),
    }
    repo = _StopLossRepository([config])

    market = _MarketData(Decimal("110"))
    result = AutoStopLossUseCase(
        market_data_service=market,
        stop_loss_repo=repo,
    ).check_and_execute_stop_loss(user_id=9)

    assert result[0].check_status == "evaluated"
    assert result[0].triggered is False
    assert repo.updates[0]["config_id"] == 7
    assert repo.updates[0]["highest_price"] == Decimal("110.0")
    assert repo.updates[0]["highest_price_updated_at"] == market.observed_at
    assert "status" not in repo.updates[0]
    assert "triggered_at" not in repo.updates[0]
    assert market.scalar_calls == []


def test_trailing_high_water_rejected_update_is_unavailable() -> None:
    config = {
        **_position_config(),
        "stop_loss_type": "trailing",
        "stop_loss_pct": 0.2,
        "trailing_stop_pct": 0.1,
        "max_holding_days": None,
        "highest_price": Decimal("100"),
        "highest_price_updated_at": datetime(2026, 3, 1, tzinfo=UTC),
    }
    repo = _StopLossRepository([config])
    repo.update_result = False
    market = _MarketData(Decimal("110"))

    result = AutoStopLossUseCase(
        market_data_service=market,
        stop_loss_repo=repo,
    ).check_and_execute_stop_loss(user_id=9)[0]

    assert result.check_status == "unavailable"
    assert result.reason_code == "stop_loss_configuration_unavailable"
    assert result.price_source == "unified_quote"
    assert result.price_observed_at == market.observed_at
    assert config["highest_price"] == Decimal("100")


@pytest.mark.parametrize("kind", ["stop_loss", "take_profit"])
@pytest.mark.parametrize(
    "change",
    [
        lambda metadata: metadata.update(freshness="historical"),
        lambda metadata: metadata.update(freshness="close_fallback"),
        lambda metadata: metadata.update(is_fallback=True),
        lambda metadata: metadata.update(asset_code="000001.SZ"),
        lambda metadata: metadata.update(price=True),
        lambda metadata: metadata.update(price=Decimal("NaN")),
        lambda metadata: metadata.update(price=Decimal("0")),
        lambda metadata: metadata.update(observed_at=None),
        lambda metadata: metadata.update(observed_at=datetime(2026, 4, 1)),
        lambda metadata: metadata.update(observed_at=datetime(2027, 1, 1, tzinfo=UTC)),
    ],
)
def test_unqualified_price_metadata_is_unavailable_for_both_exit_rules(kind, change) -> None:
    market = _MarketData(Decimal("80"))
    change(market.metadata)
    config = {
        **_position_config(),
        "stop_loss_type": "fixed",
        "stop_loss_pct": 0.2,
        "trailing_stop_pct": None,
        "max_holding_days": None,
        "highest_price": Decimal("100"),
        "take_profit_pct": 0.2,
        "partial_profit_levels": [0.1],
        "is_active": True,
    }

    if kind == "stop_loss":
        result = AutoStopLossUseCase(
            market_data_service=market,
            stop_loss_repo=_StopLossRepository([config]),
        ).check_and_execute_stop_loss(user_id=9)[0]
    else:
        result = AutoTakeProfitUseCase(
            market_data_service=market,
            take_profit_repo=_TakeProfitRepository([config]),
        ).check_and_execute_take_profit(user_id=9)[0]

    assert result.check_status == "unavailable"
    assert result.reason_code == "market_price_unavailable"
    assert result.current_price is None
    assert result.unrealized_pnl is None
    assert result.unrealized_pnl_pct is None
    assert result.price_source is None
    assert result.price_observed_at is None
    assert result.price_freshness is None
    assert result.must_not_use_for_decision is True
    assert result.must_not_execute is True
    assert market.scalar_calls == []


def test_take_profit_trigger_does_not_consume_levels_or_write_a_legacy_sell(
    monkeypatch,
) -> None:
    config = {
        **_position_config(),
        "take_profit_pct": 0.4,
        "partial_profit_levels": [0.1, 0.2, 0.3],
        "is_active": True,
    }
    repo = _TakeProfitRepository([config])
    monkeypatch.setattr(
        "apps.account.application.stop_loss_use_cases.TakeProfitService.check_take_profit",
        lambda **_kwargs: TakeProfitCheckResult(
            should_trigger=True,
            trigger_reason="first tranche",
            take_profit_price=110.0,
            current_price=130.0,
            unrealized_pnl_pct=0.3,
            partial_level=1,
        ),
    )

    market = _MarketData(Decimal("130"))
    result = AutoTakeProfitUseCase(
        market_data_service=market,
        take_profit_repo=repo,
    ).check_and_execute_take_profit(user_id=9)

    assert len(result) == 1
    assert isinstance(result[0], TakeProfitCheckOutput)
    assert result[0].triggered is True
    assert result[0].execution_status == "blocked"
    assert result[0].reason_code == "legacy_automatic_exit_not_qualified"
    assert result[0].partial_level == 1
    assert market.scalar_calls == []
    assert repo.executed_tranches == []
    assert config["partial_profit_levels"] == [0.1, 0.2, 0.3]
    assert config["is_active"] is True


def test_take_profit_missing_price_is_unavailable_without_synthetic_financial_values() -> None:
    config = {
        **_position_config(),
        "take_profit_pct": 0.4,
        "partial_profit_levels": [0.1, 0.2],
        "is_active": True,
    }
    repo = _TakeProfitRepository([config])

    result = AutoTakeProfitUseCase(
        market_data_service=_MarketData(None),
        take_profit_repo=repo,
    ).check_and_execute_take_profit(user_id=9)

    assert len(result) == 1
    assert result[0].check_status == "unavailable"
    assert result[0].reason_code == "market_price_unavailable"
    assert result[0].current_price is None
    assert result[0].unrealized_pnl is None
    assert result[0].unrealized_pnl_pct is None
    assert repo.executed_tranches == []


def test_take_profit_malformed_position_has_no_fabricated_identity() -> None:
    """A malformed payload keeps identity unknown rather than inventing a key."""

    config = {
        "id": 8,
        "position_id": 4,
        "position": None,
        "take_profit_pct": 0.4,
        "partial_profit_levels": [0.1, 0.2],
        "is_active": True,
    }
    market = _MarketData(Decimal("130"))
    result = AutoTakeProfitUseCase(
        market_data_service=market,
        take_profit_repo=_TakeProfitRepository([config]),
    ).check_and_execute_take_profit(user_id=9)[0]

    assert result.check_status == "unavailable"
    assert result.position_id is None
    assert result.asset_code is None
    assert result.current_price is None
    assert result.unrealized_pnl is None
    assert market.calls == []


@pytest.mark.parametrize("user_id", [True, False, 0, -1, "9"])
def test_use_cases_reject_invalid_user_before_repository_or_provider(user_id) -> None:
    stop_repo = _StopLossRepository([])
    take_repo = _TakeProfitRepository([])

    with pytest.raises(ValueError, match="invalid_exit_user_id"):
        AutoStopLossUseCase(stop_loss_repo=stop_repo).check_and_execute_stop_loss(user_id=user_id)
    with pytest.raises(ValueError, match="invalid_exit_user_id"):
        AutoTakeProfitUseCase(take_profit_repo=take_repo).check_and_execute_take_profit(
            user_id=user_id
        )

    assert stop_repo.read_calls == []
    assert take_repo.read_calls == []


def test_configured_risk_policy_remains_the_stop_threshold_source() -> None:
    config = {
        **_position_config(),
        "stop_loss_type": "fixed",
        "stop_loss_pct": 0.2,
        "trailing_stop_pct": None,
        "max_holding_days": None,
        "highest_price": Decimal("100"),
    }
    policy = _RiskPolicyProvider({"max_stop_loss_pct": 0.08})
    result = AutoStopLossUseCase(
        market_data_service=_MarketData(Decimal("95")),
        stop_loss_repo=_StopLossRepository([config]),
        risk_policy_provider=policy,
    ).check_and_execute_stop_loss(user_id=9)

    assert policy.account_ids == [2]
    assert result[0].check_result is not None
    assert result[0].check_result.stop_price == 92.0


def test_configured_risk_policy_remains_the_take_threshold_source() -> None:
    config = {
        **_position_config(),
        "take_profit_pct": 0.4,
        "partial_profit_levels": None,
        "is_active": True,
    }
    policy = _RiskPolicyProvider({"take_profit_pct": 0.25})
    result = AutoTakeProfitUseCase(
        market_data_service=_MarketData(Decimal("120")),
        take_profit_repo=_TakeProfitRepository([config]),
        risk_policy_provider=policy,
    ).check_and_execute_take_profit(user_id=9)

    assert policy.account_ids == [2]
    assert result[0].check_result is not None
    assert result[0].check_result.take_profit_price == 125.0
