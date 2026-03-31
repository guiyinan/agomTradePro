"""
Unit tests for Macro Sizing Multiplier domain services.
Pure Python — no Django ORM dependency.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.account.domain.entities import (
    AccountProfile,
    AssetAllocation,
    AssetClassType,
    AssetMetadata,
    CrossBorderFlag,
    DrawdownTier,
    InvestmentStyle,
    MacroSizingConfig,
    Position,
    PositionSource,
    PositionStatus,
    PulseTier,
    Region,
    RegimeTier,
    RiskTolerance,
    StopLossConfig,
    StopLossStatus,
    StopLossType,
    TakeProfitConfig,
    TradingCostConfig,
)
from apps.account.domain.services import (
    LimitCheckResult,
    LimitCheckService,
    MacroSizingContext,
    MultiDimensionLimits,
    PositionService,
    SizingMultiplierResult,
    StopLossService,
    TakeProfitService,
    VolatilityCalculator,
    VolatilityTargetService,
    calculate_macro_multiplier,
    calculate_portfolio_drawdown,
)


def build_default_config() -> MacroSizingConfig:
    return MacroSizingConfig(
        regime_tiers=[
            RegimeTier(min_confidence=0.6, factor=1.0),
            RegimeTier(min_confidence=0.4, factor=0.8),
            RegimeTier(min_confidence=0.0, factor=0.5),
        ],
        pulse_tiers=[
            PulseTier(min_composite=0.3, max_composite=99, factor=1.00),
            PulseTier(min_composite=-0.3, max_composite=0.3, factor=0.85),
            PulseTier(min_composite=-99, max_composite=-0.3, factor=0.70),
        ],
        warning_factor=0.5,
        drawdown_tiers=[
            DrawdownTier(min_drawdown=0.15, factor=0.0),
            DrawdownTier(min_drawdown=0.10, factor=0.5),
            DrawdownTier(min_drawdown=0.05, factor=0.8),
            DrawdownTier(min_drawdown=0.00, factor=1.0),
        ],
        version=1,
    )


def build_position(
    *,
    asset_code: str = "000001.SH",
    market_value: Decimal = Decimal("1000"),
    asset_class: AssetClassType = AssetClassType.EQUITY,
    region: Region = Region.CN,
    cross_border: CrossBorderFlag = CrossBorderFlag.DOMESTIC,
    shares: float = 10,
    avg_cost: Decimal = Decimal("100"),
    current_price: Decimal = Decimal("110"),
) -> Position:
    return Position(
        id=1,
        portfolio_id=1,
        user_id=1,
        asset_code=asset_code,
        shares=shares,
        avg_cost=avg_cost,
        current_price=current_price,
        market_value=market_value,
        unrealized_pnl=Decimal("100"),
        unrealized_pnl_pct=10.0,
        opened_at=datetime.now(timezone.utc),
        status=PositionStatus.ACTIVE,
        source=PositionSource.MANUAL,
        source_id=None,
        asset_class=asset_class,
        region=region,
        cross_border=cross_border,
    )


# ── calculate_macro_multiplier ──────────────────────────────────────────


class TestCalculateMacroMultiplier:
    config = build_default_config()

    @pytest.mark.parametrize(
        "regime_conf,pulse_comp,pulse_warn,drawdown,expected_mult,expected_hint",
        [
            (0.8, 0.5, False, 0.02, 1.0000, "正常开仓"),
            (0.3, 0.5, False, 0.0, 0.5000, "缩半开仓"),
            (0.7, 0.5, True, 0.0, 0.5000, "缩半开仓"),
            (0.3, 0.5, True, 0.0, 0.2500, "缩半开仓"),
            (0.9, 0.9, False, 0.16, 0.0000, "暂停新仓"),
            (0.7, 0.5, False, 0.08, 0.8000, "正常开仓"),
            (0.0, -0.5, True, 0.20, 0.0000, "暂停新仓"),
            (0.7, -0.5, False, 0.0, 0.7000, "减仓操作"),
        ],
    )
    def test_scenario(
        self,
        regime_conf: float,
        pulse_comp: float,
        pulse_warn: bool,
        drawdown: float,
        expected_mult: float,
        expected_hint: str,
    ):
        ctx = MacroSizingContext(
            regime_confidence=regime_conf,
            regime_name="Test",
            pulse_composite=pulse_comp,
            pulse_warning=pulse_warn,
            portfolio_drawdown_pct=drawdown,
        )
        result = calculate_macro_multiplier(ctx, self.config)
        assert result.multiplier == pytest.approx(expected_mult, abs=1e-4)
        assert result.action_hint == expected_hint
        assert isinstance(result, SizingMultiplierResult)
        assert 0.0 <= result.multiplier <= 1.0
        assert result.config_version == 1

    def test_result_contains_all_factors(self):
        ctx = MacroSizingContext(
            regime_confidence=0.7,
            regime_name="Recovery",
            pulse_composite=0.5,
            pulse_warning=False,
            portfolio_drawdown_pct=0.0,
        )
        result = calculate_macro_multiplier(ctx, self.config)
        assert result.regime_factor == 1.0
        assert result.pulse_factor == 1.0
        assert result.drawdown_factor == 1.0
        assert result.multiplier == 1.0

    def test_reasoning_contains_three_factors(self):
        ctx = MacroSizingContext(
            regime_confidence=0.5,
            regime_name="Recovery",
            pulse_composite=0.1,
            pulse_warning=True,
            portfolio_drawdown_pct=0.08,
        )
        result = calculate_macro_multiplier(ctx, self.config)
        assert "Regime置信度" in result.reasoning
        assert "Pulse" in result.reasoning
        assert "组合回撤" in result.reasoning


# ── calculate_portfolio_drawdown ────────────────────────────────────────


class TestCalculatePortfolioDrawdown:
    def test_normal_drawdown(self):
        assert calculate_portfolio_drawdown([80, 100, 90]) == pytest.approx(0.10)

    def test_no_drawdown_rising(self):
        assert calculate_portfolio_drawdown([80, 90, 100]) == 0.0

    def test_empty_list(self):
        assert calculate_portfolio_drawdown([]) == 0.0

    def test_single_element(self):
        assert calculate_portfolio_drawdown([100]) == 0.0

    def test_all_zeros(self):
        assert calculate_portfolio_drawdown([0, 0, 0]) == 0.0

    def test_peak_at_end(self):
        assert calculate_portfolio_drawdown([80, 90, 100]) == 0.0

    def test_drawdown_from_first_element(self):
        assert calculate_portfolio_drawdown([100, 90, 80]) == pytest.approx(0.20)


# ── MacroSizingConfig tier lookups ──────────────────────────────────────


class TestMacroSizingConfigTierLookup:
    @pytest.fixture()
    def config(self) -> MacroSizingConfig:
        return build_default_config()

    def test_regime_factor_high(self, config: MacroSizingConfig):
        assert config.get_regime_factor(0.7) == 1.0

    def test_regime_factor_mid(self, config: MacroSizingConfig):
        assert config.get_regime_factor(0.5) == 0.8

    def test_regime_factor_low(self, config: MacroSizingConfig):
        assert config.get_regime_factor(0.2) == 0.5

    def test_pulse_factor_warning_overrides(self, config: MacroSizingConfig):
        assert config.get_pulse_factor(composite=0.9, warning=True) == config.warning_factor

    def test_pulse_factor_no_warning(self, config: MacroSizingConfig):
        assert config.get_pulse_factor(composite=0.9, warning=False) == 1.0

    def test_drawdown_factor_above_threshold(self, config: MacroSizingConfig):
        assert config.get_drawdown_factor(0.20) == 0.0

    def test_drawdown_factor_zero(self, config: MacroSizingConfig):
        assert config.get_drawdown_factor(0.00) == 1.0

    def test_drawdown_factor_danger_zone(self, config: MacroSizingConfig):
        assert config.get_drawdown_factor(0.12) == 0.5

    def test_drawdown_factor_warning_zone(self, config: MacroSizingConfig):
        assert config.get_drawdown_factor(0.07) == 0.8

    def test_pulse_factor_negative(self, config: MacroSizingConfig):
        assert config.get_pulse_factor(composite=-0.5, warning=False) == 0.70

    def test_pulse_factor_neutral(self, config: MacroSizingConfig):
        assert config.get_pulse_factor(composite=0.0, warning=False) == 0.85


# ── MacroSizingContext dataclass ────────────────────────────────────────


class TestMacroSizingContext:
    def test_is_frozen(self):
        ctx = MacroSizingContext(
            regime_confidence=0.5,
            regime_name="Test",
            pulse_composite=0.3,
            pulse_warning=False,
            portfolio_drawdown_pct=0.05,
        )
        with pytest.raises(AttributeError):
            ctx.regime_confidence = 0.9  # type: ignore[misc]

    def test_field_values(self):
        ctx = MacroSizingContext(
            regime_confidence=0.5,
            regime_name="Recovery",
            pulse_composite=-0.2,
            pulse_warning=True,
            portfolio_drawdown_pct=0.08,
        )
        assert ctx.regime_confidence == 0.5
        assert ctx.regime_name == "Recovery"
        assert ctx.pulse_composite == -0.2
        assert ctx.pulse_warning is True
        assert ctx.portfolio_drawdown_pct == 0.08


class TestAccountDomainEntities:
    def test_asset_metadata_full_classification_and_regime_eligibility(self):
        metadata = AssetMetadata(
            asset_code="000001.SH",
            name="Ping An Bank",
            asset_class=AssetClassType.EQUITY,
            region=Region.CN,
            cross_border=CrossBorderFlag.DOMESTIC,
            style=InvestmentStyle.GROWTH,
            sector="bank",
            sub_class="large-cap",
            description="test",
        )

        classification = metadata.get_full_classification()

        assert classification == "EQUITY | CN | domestic | bank | growth"
        assert metadata.is_eligible_for_regime(
            "Recovery",
            {"equity_CN": {"Recovery": "preferred"}},
        ) is True
        assert metadata.is_eligible_for_regime(
            "Stagflation",
            {"equity_CN": {"Stagflation": "hostile"}},
        ) is False
        assert metadata.is_eligible_for_regime("Unknown", {}) is True

    @pytest.mark.parametrize(
        ("risk_tolerance", "expected"),
        [
            (RiskTolerance.CONSERVATIVE, 0.05),
            (RiskTolerance.MODERATE, 0.10),
            (RiskTolerance.AGGRESSIVE, 0.20),
        ],
    )
    def test_account_profile_max_position_pct(self, risk_tolerance, expected):
        profile = AccountProfile(
            user_id=1,
            display_name="tester",
            initial_capital=Decimal("100000"),
            risk_tolerance=risk_tolerance,
            created_at=datetime.now(timezone.utc),
        )

        assert profile.get_max_position_pct() == expected

    def test_position_and_portfolio_snapshot_metrics(self):
        position = build_position(shares=5, avg_cost=Decimal("100"), current_price=Decimal("120"))
        pnl, pnl_pct = position.calculate_pnl()

        snapshot = __import__("apps.account.domain.entities", fromlist=["PortfolioSnapshot"]).PortfolioSnapshot(
            portfolio_id=1,
            user_id=1,
            name="P1",
            snapshot_date=datetime.now(timezone.utc),
            cash_balance=Decimal("200"),
            total_value=Decimal("1000"),
            invested_value=Decimal("800"),
            total_return=Decimal("50"),
            total_return_pct=5.0,
            positions=[position],
        )

        zero_snapshot = __import__("apps.account.domain.entities", fromlist=["PortfolioSnapshot"]).PortfolioSnapshot(
            portfolio_id=1,
            user_id=1,
            name="P0",
            snapshot_date=datetime.now(timezone.utc),
            cash_balance=Decimal("0"),
            total_value=Decimal("0"),
            invested_value=Decimal("0"),
            total_return=Decimal("0"),
            total_return_pct=0.0,
            positions=[],
        )

        assert pnl == Decimal("100")
        assert pnl_pct == pytest.approx(20.0)
        assert snapshot.get_cash_ratio() == pytest.approx(0.2)
        assert snapshot.get_invested_ratio() == pytest.approx(0.8)
        assert zero_snapshot.get_cash_ratio() == 1.0
        assert zero_snapshot.get_invested_ratio() == 0.0

    def test_asset_allocation_display_name_and_fallback(self):
        allocation = AssetAllocation(
            dimension="asset_class",
            dimension_value="equity",
            count=1,
            market_value=Decimal("100"),
            percentage=100.0,
            asset_codes=["000001.SH"],
        )
        unknown = AssetAllocation(
            dimension="style",
            dimension_value="quality",
            count=1,
            market_value=Decimal("100"),
            percentage=100.0,
            asset_codes=["000001.SH"],
        )

        assert allocation.get_display_name() == "股票"
        assert unknown.get_display_name() == "quality"

    def test_stop_loss_config_calculates_all_price_modes(self):
        fixed = StopLossConfig(position_id=1, stop_loss_type=StopLossType.FIXED, stop_loss_pct=-0.1)
        trailing = StopLossConfig(
            position_id=1,
            stop_loss_type=StopLossType.TRAILING,
            stop_loss_pct=-0.1,
            trailing_stop_pct=0.15,
        )
        time_based = StopLossConfig(
            position_id=1,
            stop_loss_type=StopLossType.TIME_BASED,
            stop_loss_pct=-0.1,
            max_holding_days=10,
            status=StopLossStatus.ACTIVE,
        )

        assert fixed.calculate_stop_price(100, 95, 120) == pytest.approx(90.0)
        assert trailing.calculate_stop_price(100, 95, 120) == pytest.approx(102.0)
        assert time_based.calculate_stop_price(100, 95, 120) == 0.0

    def test_trading_cost_and_take_profit_config_helpers(self):
        trading_cost = TradingCostConfig(id=1, portfolio_id=1)

        buy = trading_cost.calculate_buy_cost(amount=10000, is_shanghai=True)
        sell = trading_cost.calculate_sell_cost(amount=10000, is_shanghai=True)
        tp = TakeProfitConfig(position_id=1, take_profit_pct=0.2)

        assert buy["commission"] == 5.0
        assert buy["transfer_fee"] == 0.2
        assert sell["stamp_duty"] == 10.0
        assert sell["total"] == 15.2
        assert tp.calculate_take_profit_price(100) == pytest.approx(120.0)


class TestPositionService:
    def test_calculate_position_size_applies_adjustments(self):
        result = PositionService.calculate_position_size(
            account_capital=Decimal("100000"),
            risk_tolerance=RiskTolerance.CONSERVATIVE,
            asset_class=AssetClassType.COMMODITY,
            region=Region.EM,
            current_price=Decimal("50"),
        )

        assert result.shares == 48.0
        assert result.notional == Decimal("2400.0")
        assert result.cash_required == Decimal("2400.0")
        assert result.max_loss == Decimal("480.00")

    def test_calculate_regime_match_score_handles_empty_and_non_empty_positions(self):
        empty_result = PositionService.calculate_regime_match_score([], "Recovery")
        positions = [
            build_position(asset_code="CN1", market_value=Decimal("1000"), asset_class=AssetClassType.EQUITY, region=Region.CN),
            build_position(asset_code="US1", market_value=Decimal("500"), asset_class=AssetClassType.EQUITY, region=Region.US),
            build_position(asset_code="CASH1", market_value=Decimal("500"), asset_class=AssetClassType.CASH, region=Region.CN),
        ]
        non_empty = PositionService.calculate_regime_match_score(positions, "Recovery")

        assert empty_result.total_match_score == 100.0
        assert "暂无持仓" in empty_result.recommendations[0]
        assert non_empty.total_match_score == pytest.approx(75.0, abs=0.1)
        assert any("CN1" in item for item in non_empty.preferred_assets)
        assert any("CASH1" in item for item in non_empty.hostile_assets)

    @pytest.mark.parametrize(
        ("regime", "score", "expected"),
        [
            ("Recovery", 85, "复苏期建议"),
            ("Overheat", 60, "过热期建议"),
            ("Stagflation", 40, "滞胀期建议"),
            ("Deflation", 30, "通缩期建议"),
        ],
    )
    def test_generate_regime_recommendations(self, regime, score, expected):
        recommendations = PositionService._generate_regime_recommendations(
            regime,
            score,
            preferred=["A"],
            neutral=[],
            hostile=["BAD (100)"],
        )

        assert any(expected in item for item in recommendations)
        assert any("BAD" in item for item in recommendations)

    def test_calculate_asset_allocation_and_risk(self):
        positions = [
            build_position(asset_code="CN1", market_value=Decimal("1000"), asset_class=AssetClassType.EQUITY, region=Region.CN),
            build_position(asset_code="US1", market_value=Decimal("500"), asset_class=AssetClassType.FUND, region=Region.US),
            build_position(asset_code="US2", market_value=Decimal("1500"), asset_class=AssetClassType.FUND, region=Region.US),
        ]

        allocation = PositionService.calculate_asset_allocation(positions, dimension="region")
        other_allocation = PositionService.calculate_asset_allocation(positions, dimension="unknown")
        risk = PositionService.assess_portfolio_risk(positions, Decimal("3000"))
        empty_risk = PositionService.assess_portfolio_risk([], Decimal("3000"))

        assert [item.dimension_value for item in allocation] == ["US", "CN"]
        assert allocation[0].percentage == pytest.approx(66.666, rel=1e-2)
        assert other_allocation[0].dimension_value == "other"
        assert risk["total_exposure"] == 1.0
        assert risk["risk_level"] == "high"
        assert empty_risk["risk_level"] == "low"


class TestRiskServices:
    def test_stop_loss_service_checks_all_paths(self):
        fixed = StopLossService.check_stop_loss(
            entry_price=100,
            current_price=89,
            highest_price=120,
            stop_loss_type="fixed",
            stop_loss_pct=0.1,
        )
        trailing = StopLossService.check_stop_loss(
            entry_price=100,
            current_price=100,
            highest_price=120,
            stop_loss_type="trailing",
            stop_loss_pct=0.1,
            trailing_stop_pct=0.15,
        )
        unknown = StopLossService.check_stop_loss(
            entry_price=100,
            current_price=100,
            highest_price=120,
            stop_loss_type="other",
            stop_loss_pct=0.1,
        )

        assert fixed.should_trigger is True
        assert fixed.stop_price == pytest.approx(90.0)
        assert trailing.should_trigger is True
        assert trailing.stop_price == pytest.approx(102.0)
        assert unknown.should_trigger is False
        assert unknown.trigger_reason == "未触发"

    @pytest.mark.parametrize("kwargs", [{"stop_loss_pct": -0.1}, {"stop_loss_pct": 1.1}, {"stop_loss_pct": 0.1, "trailing_stop_pct": -0.1}, {"stop_loss_pct": 0.1, "trailing_stop_pct": 1.1}])
    def test_stop_loss_service_validates_inputs(self, kwargs):
        with pytest.raises(ValueError):
            StopLossService.check_stop_loss(
                entry_price=100,
                current_price=95,
                highest_price=100,
                stop_loss_type="fixed",
                **kwargs,
            )

    def test_time_stop_loss_and_trailing_highest_updates(self):
        opened_at = datetime.now(timezone.utc) - timedelta(days=10)
        now = datetime.now(timezone.utc)

        result = StopLossService.check_time_stop_loss(opened_at, now, max_holding_days=5)
        raised_high, raised_time = StopLossService.update_trailing_stop_highest(100, 110, now, None)
        same_high, same_time = StopLossService.update_trailing_stop_highest(110, 100, now, opened_at)

        assert result.should_trigger is True
        assert "时间止损触发" in result.trigger_reason
        assert raised_high == 110
        assert raised_time == now
        assert same_high == 110
        assert same_time == opened_at

    def test_take_profit_service_partial_and_full_paths(self):
        partial = TakeProfitService.check_take_profit(
            entry_price=100,
            current_price=130,
            take_profit_pct=0.2,
            partial_levels=[0.1, 0.2],
        )
        full = TakeProfitService.check_take_profit(
            entry_price=100,
            current_price=120,
            take_profit_pct=0.2,
        )
        none_hit = TakeProfitService.check_take_profit(
            entry_price=100,
            current_price=105,
            take_profit_pct=0.2,
        )

        assert partial.should_trigger is True
        assert partial.partial_level == 1
        assert full.should_trigger is True
        assert "止盈触发" in full.trigger_reason
        assert none_hit.should_trigger is False
        assert none_hit.trigger_reason == "未触发"

    def test_volatility_calculator_and_target_service(self):
        empty_metrics = VolatilityCalculator.calculate_volatility([], window_days=30)
        metrics = VolatilityCalculator.calculate_volatility([0.01, -0.01, 0.02], window_days=2, annualize=False)
        rolling = VolatilityCalculator.calculate_portfolio_volatility(
            [
                {"date": "2024-01-01", "total_value": 100},
                {"date": "2024-01-02", "total_value": 110},
                {"date": "2024-01-03", "total_value": 105},
                {"date": "2024-01-04", "total_value": 120},
            ],
            window_days=2,
        )
        adjustment = VolatilityTargetService.assess_volatility_adjustment(
            current_volatility=0.3,
            target_volatility=0.15,
            tolerance=0.2,
            max_reduction=0.5,
        )
        no_adjustment = VolatilityTargetService.assess_volatility_adjustment(
            current_volatility=0.16,
            target_volatility=0.15,
        )

        assert empty_metrics.annualized_volatility == 0.0
        assert metrics.daily_volatility > 0
        assert len(rolling) == 2
        assert adjustment.should_reduce is True
        assert adjustment.suggested_position_multiplier == 0.5
        assert no_adjustment.should_reduce is False
        assert VolatilityTargetService.get_default_target_volatility("moderate") == 0.15
        assert VolatilityTargetService.get_default_target_volatility("unknown") == 0.15

    @pytest.mark.parametrize(
        ("current_volatility", "target_volatility"),
        [(-0.1, 0.15), (0.2, 0.0)],
    )
    def test_volatility_target_service_validates_inputs(self, current_volatility, target_volatility):
        with pytest.raises(ValueError):
            VolatilityTargetService.assess_volatility_adjustment(
                current_volatility=current_volatility,
                target_volatility=target_volatility,
            )


class TestLimitCheckService:
    def test_limit_checks_and_reject_reason(self):
        growth_position = build_position(asset_code="G1", market_value=Decimal("700"))
        value_position = build_position(asset_code="V1", market_value=Decimal("300"))
        object.__setattr__(growth_position, "style", InvestmentStyle.GROWTH)
        object.__setattr__(value_position, "style", InvestmentStyle.VALUE)

        positions = [growth_position, value_position]
        limits = MultiDimensionLimits(max_style_ratio=0.4, max_sector_ratio=0.25, max_foreign_currency_ratio=0.3)

        style_result = LimitCheckService.check_style_limit(positions, "growth", limits)
        sector_result = LimitCheckService.check_sector_limit(positions, "tech", limits)
        currency_result = LimitCheckService.check_currency_limit(
            [
                build_position(asset_code="CN1", market_value=Decimal("400"), region=Region.CN),
                build_position(asset_code="US1", market_value=Decimal("600"), region=Region.US),
            ],
            "USD",
            limits=limits,
        )
        all_results = LimitCheckService.check_all_limits(
            positions=positions,
            new_asset_code="NEW",
            new_style="growth",
            new_sector="tech",
            new_currency="USD",
            limits=limits,
        )
        should_reject, reason = LimitCheckService.should_reject_position(
            [style_result, sector_result, currency_result]
        )
        allow, allow_reason = LimitCheckService.should_reject_position(
            [LimitCheckResult("style", "value", Decimal("10"), Decimal("40"), 0.1, 0.4, False, True, "")]
        )

        assert style_result.exceeds_limit is True
        assert "已达限额" in style_result.warning_message
        assert sector_result.can_add_position is True
        assert currency_result.exceeds_limit is True
        assert len(all_results) == 3
        assert should_reject is True
        assert reason
        assert allow is False
        assert allow_reason == ""
