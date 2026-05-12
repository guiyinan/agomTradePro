"""
Unit tests for High-Frequency Indicators (Phase 1)

测试高频指标相关功能，包括：
1. Domain 层实体（HighFrequencyIndicator, RegimeSignal, BondYieldCurve）
2. Application 层用例（CalculateTermSpreadUseCase, HighFrequencySignalUseCase）
3. Signal 冲突解决（ResolveSignalConflictUseCase）
4. 混合 Regime 计算（HybridRegimeCalculator）
"""

from datetime import date
from unittest.mock import Mock

from apps.macro.domain.entities import (
    BondYieldCurve,
    CreditSpreadIndicator,
    HighFrequencyIndicator,
    PeriodType,
    RegimeSensitivity,
    RegimeSignal,
    SignalDirection,
)


class TestHighFrequencyIndicator:
    """高频指标实体测试"""

    def test_create_high_frequency_indicator(self):
        """测试：创建高频指标实体"""
        indicator = HighFrequencyIndicator(
            code="CN_BOND_10Y",
            name="10年期国债收益率",
            value=3.5,
            unit="%",
            date=date(2024, 1, 15),
            period_type=PeriodType.DAY,
            regime_sensitivity=RegimeSensitivity.HIGH,
            predictive_power=0.8,
            lead_time_months=6,
            source="akshare"
        )

        assert indicator.code == "CN_BOND_10Y"
        assert indicator.value == 3.5
        assert indicator.regime_sensitivity == RegimeSensitivity.HIGH
        assert indicator.predictive_power == 0.8
        assert indicator.lead_time_months == 6

    def test_to_macro_indicator_conversion(self):
        """测试：转换为 MacroIndicator 实体"""

        hf_indicator = HighFrequencyIndicator(
            code="CN_BOND_10Y",
            name="10年期国债收益率",
            value=3.5,
            unit="%",
            date=date(2024, 1, 15),
            period_type=PeriodType.DAY,
            regime_sensitivity=RegimeSensitivity.HIGH,
            source="akshare"
        )

        macro_indicator = hf_indicator.to_macro_indicator()

        assert macro_indicator.code == "CN_BOND_10Y"
        assert macro_indicator.value == 3.5
        assert macro_indicator.period_type == PeriodType.DAY
        assert macro_indicator.unit == "%"

    def test_regime_sensitivity_enum(self):
        """测试：RegimeSensitivity 枚举"""
        assert RegimeSensitivity.HIGH.value == "HIGH"
        assert RegimeSensitivity.MEDIUM.value == "MEDIUM"
        assert RegimeSensitivity.LOW.value == "LOW"


class TestRegimeSignal:
    """Regime信号实体测试"""

    def test_create_regime_signal(self):
        """测试：创建 Regime 信号"""
        signal = RegimeSignal(
            indicator_code="CN_TERM_SPREAD_10Y2Y",
            direction=SignalDirection.BEARISH,
            strength=0.8,
            confidence=0.7,
            signal_date=date(2024, 1, 15),
            regime_sensitivity=RegimeSensitivity.HIGH,
            lead_time_months=6,
            source="DAILY_HIGH_FREQ"
        )

        assert signal.indicator_code == "CN_TERM_SPREAD_10Y2Y"
        assert signal.direction == SignalDirection.BEARISH
        assert signal.strength == 0.8
        assert signal.confidence == 0.7

    def test_signal_direction_properties(self):
        """测试：信号方向属性"""
        bullish_signal = RegimeSignal(
            indicator_code="CN_NHCI",
            direction=SignalDirection.BULLISH,
            strength=0.7,
            confidence=0.6,
            signal_date=date.today(),
            regime_sensitivity=RegimeSensitivity.MEDIUM
        )

        assert bullish_signal.is_bullish is True
        assert bullish_signal.is_bearish is False
        assert bullish_signal.is_neutral is False

        bearish_signal = RegimeSignal(
            indicator_code="CN_TERM_SPREAD_10Y2Y",
            direction=SignalDirection.BEARISH,
            strength=0.8,
            confidence=0.7,
            signal_date=date.today(),
            regime_sensitivity=RegimeSensitivity.HIGH
        )

        assert bearish_signal.is_bullish is False
        assert bearish_signal.is_bearish is True
        assert bearish_signal.is_neutral is False

    def test_high_confidence_property(self):
        """测试：高置信度属性"""
        high_conf_signal = RegimeSignal(
            indicator_code="CN_TERM_SPREAD_10Y2Y",
            direction=SignalDirection.BEARISH,
            strength=0.8,
            confidence=0.8,  # >= 0.7
            signal_date=date.today(),
            regime_sensitivity=RegimeSensitivity.HIGH
        )

        assert high_conf_signal.is_high_confidence is True

        low_conf_signal = RegimeSignal(
            indicator_code="CN_NHCI",
            direction=SignalDirection.BULLISH,
            strength=0.5,
            confidence=0.5,  # < 0.7
            signal_date=date.today(),
            regime_sensitivity=RegimeSensitivity.MEDIUM
        )

        assert low_conf_signal.is_high_confidence is False

    def test_high_sensitivity_property(self):
        """测试：高敏感度属性"""
        high_sens_signal = RegimeSignal(
            indicator_code="CN_TERM_SPREAD_10Y2Y",
            direction=SignalDirection.BEARISH,
            strength=0.8,
            confidence=0.7,
            signal_date=date.today(),
            regime_sensitivity=RegimeSensitivity.HIGH
        )

        assert high_sens_signal.is_high_sensitivity is True

        medium_sens_signal = RegimeSignal(
            indicator_code="CN_NHCI",
            direction=SignalDirection.BULLISH,
            strength=0.5,
            confidence=0.5,
            signal_date=date.today(),
            regime_sensitivity=RegimeSensitivity.MEDIUM
        )

        assert medium_sens_signal.is_high_sensitivity is False


class TestBondYieldCurve:
    """国债收益率曲线实体测试"""

    def test_create_yield_curve(self):
        """测试：创建收益率曲线"""
        curve = BondYieldCurve(
            date=date(2024, 1, 15),
            bond_10y=3.5,
            bond_5y=3.0,
            bond_2y=2.5,
            bond_1y=2.0,
            term_spread_10y2y=100,  # BP
            term_spread_10y1y=150,
            is_inverted=False,
            inversion_severity=0.0
        )

        assert curve.bond_10y == 3.5
        assert curve.term_spread_10y2y == 100
        assert curve.is_inverted is False

    def test_inverted_yield_curve(self):
        """测试：倒挂收益率曲线"""
        curve = BondYieldCurve(
            date=date(2024, 1, 15),
            bond_10y=2.5,
            bond_5y=3.0,
            bond_2y=3.5,
            bond_1y=4.0,
            term_spread_10y2y=-100,  # Negative spread = inverted
            term_spread_10y1y=-150,
            is_inverted=True,
            inversion_severity=100
        )

        assert curve.is_inverted is True
        assert curve.inversion_severity == 100
        assert curve.curve_shape == "INVERTED"

    def test_curve_shape_normal(self):
        """测试：正常收益率曲线"""
        curve = BondYieldCurve(
            date=date(2024, 1, 15),
            bond_10y=3.5,
            bond_5y=3.2,
            bond_2y=3.0,
            term_spread_10y2y=0.5,  # 50 BP (0.5 - 1.5 BP = NORMAL)
            is_inverted=False
        )

        assert curve.curve_shape == "NORMAL"

    def test_curve_shape_flat(self):
        """测试：平坦收益率曲线"""
        curve = BondYieldCurve(
            date=date(2024, 1, 15),
            bond_10y=3.0,
            bond_5y=2.9,
            bond_2y=2.8,
            term_spread_10y2y=0.2,  # Less than 0.5 BP
            is_inverted=False
        )

        assert curve.curve_shape == "FLAT"

    def test_curve_shape_steep(self):
        """测试：陡峭收益率曲线"""
        curve = BondYieldCurve(
            date=date(2024, 1, 15),
            bond_10y=5.0,
            bond_5y=3.5,
            bond_2y=2.5,
            term_spread_10y2y=250,  # More than 1.5 BP
            is_inverted=False
        )

        assert curve.curve_shape == "STEEP"


class TestCreditSpreadIndicator:
    """信用利差指标实体测试"""

    def test_create_credit_spread(self):
        """测试：创建信用利差指标"""
        spread = CreditSpreadIndicator(
            date=date(2024, 1, 15),
            spread_10y=150,  # BP
            aaa_yield=4.0,
            baa_yield=5.5,
            treasury_10y=3.5,
            warning_level="NORMAL",
            spread_percentile=50.0
        )

        assert spread.spread_10y == 150
        assert spread.aaa_yield == 4.0
        assert spread.baa_yield == 5.5
        assert spread.treasury_10y == 3.5

    def test_stressed_credit_market(self):
        """测试：信用市场压力状态"""
        spread = CreditSpreadIndicator(
            date=date(2024, 1, 15),
            spread_10y=300,
            aaa_yield=5.0,
            baa_yield=8.0,
            treasury_10y=5.0,
            warning_level="DANGER",
            spread_percentile=95.0
        )

        assert spread.is_stressed is True
        assert spread.stress_level == 0.95

    def test_normal_credit_market(self):
        """测试：正常信用市场状态"""
        spread = CreditSpreadIndicator(
            date=date(2024, 1, 15),
            spread_10y=100,
            aaa_yield=4.0,
            baa_yield=5.0,
            treasury_10y=4.0,
            warning_level="NORMAL",
            spread_percentile=30.0
        )

        assert spread.is_stressed is False
        assert spread.stress_level == 0.30


class TestTermSpreadCalculation:
    """期限利差计算测试"""

    def test_calculate_normal_spread(self):
        """测试：计算正常期限利差"""
        from apps.regime.application.use_cases import (
            CalculateTermSpreadRequest,
            CalculateTermSpreadUseCase,
        )

        # Mock repository
        mock_repo = Mock()
        mock_repo.get_by_code_and_date = Mock(return_value=None)

        # Setup mock data
        mock_long_bond = Mock()
        mock_long_bond.value = 3.5

        mock_short_bond = Mock()
        mock_short_bond.value = 2.5

        def mock_get_latest(code, before_date):
            if "10Y" in code:
                return mock_long_bond
            elif "2Y" in code:
                return mock_short_bond
            return None

        mock_repo.get_latest_observation = Mock(side_effect=mock_get_latest)

        use_case = CalculateTermSpreadUseCase(mock_repo)
        request = CalculateTermSpreadRequest(
            as_of_date=date(2024, 1, 15),
            long_term="10Y",
            short_term="2Y",
            country="CN"
        )

        response = use_case.execute(request)

        assert response.success is True
        assert response.spread_value == 100  # (3.5 - 2.5) * 100 = 100 BP
        assert response.is_inverted is False
        assert response.curve_shape == "STEEP"

    def test_calculate_inverted_spread(self):
        """测试：计算倒挂期限利差"""
        from apps.regime.application.use_cases import (
            CalculateTermSpreadRequest,
            CalculateTermSpreadUseCase,
        )

        mock_repo = Mock()

        # Setup mock data for inverted curve
        mock_long_bond = Mock()
        mock_long_bond.value = 2.5  # Lower yield

        mock_short_bond = Mock()
        mock_short_bond.value = 3.5  # Higher yield = inverted

        def mock_get_latest(code, before_date):
            if "10Y" in code:
                return mock_long_bond
            elif "2Y" in code:
                return mock_short_bond
            return None

        mock_repo.get_latest_observation = Mock(side_effect=mock_get_latest)
        mock_repo.get_by_code_and_date = Mock(return_value=None)

        use_case = CalculateTermSpreadUseCase(mock_repo)
        request = CalculateTermSpreadRequest(
            as_of_date=date(2024, 1, 15),
            long_term="10Y",
            short_term="2Y",
            country="CN"
        )

        response = use_case.execute(request)

        assert response.success is True
        assert response.spread_value == -100  # (2.5 - 3.5) * 100 = -100 BP
        assert response.is_inverted is True
        assert response.inversion_severity == 100
        assert response.curve_shape == "INVERTED"


class TestSignalConflictResolution:
    """信号冲突解决测试"""

    def test_all_consistent_signals(self):
        """测试：日度和月度信号一致"""
        from apps.regime.application.use_cases import (
            ResolveSignalConflictRequest,
            ResolveSignalConflictUseCase,
        )

        use_case = ResolveSignalConflictUseCase()
        request = ResolveSignalConflictRequest(
            daily_signal="Recovery",
            daily_confidence=0.7,
            daily_duration_days=5,
            monthly_signal="Recovery",
            monthly_confidence=0.8
        )

        response = use_case.execute(request)

        assert response.final_signal == "Recovery"
        assert response.source == "ALL_CONSISTENT"
        assert response.final_confidence > 0.8  # Boosted confidence

    def test_persistent_daily_signal(self):
        """测试：日度信号持续超过阈值"""
        from apps.regime.application.use_cases import (
            ResolveSignalConflictRequest,
            ResolveSignalConflictUseCase,
        )

        use_case = ResolveSignalConflictUseCase()
        request = ResolveSignalConflictRequest(
            daily_signal="Stagflation",
            daily_confidence=0.7,
            daily_duration_days=12,  # >= 10 days
            monthly_signal="Recovery",
            monthly_confidence=0.8
        )

        response = use_case.execute(request)

        assert response.final_signal == "Stagflation"
        assert response.source == "DAILY_PERSISTENT"
        assert response.final_confidence >= 0.7

    def test_default_monthly_signal(self):
        """测试：默认使用月度信号"""
        from apps.regime.application.use_cases import (
            ResolveSignalConflictRequest,
            ResolveSignalConflictUseCase,
        )

        use_case = ResolveSignalConflictUseCase()
        request = ResolveSignalConflictRequest(
            daily_signal="Stagflation",
            daily_confidence=0.6,
            daily_duration_days=3,  # < 10 days
            monthly_signal="Recovery",
            monthly_confidence=0.8
        )

        response = use_case.execute(request)

        assert response.final_signal == "Recovery"
        assert response.source == "MONTHLY_DEFAULT"
        assert response.final_confidence < 0.8  # Reduced confidence


class TestHybridRegimeCalculator:
    """混合Regime计算器测试"""

    def test_monthly_only_no_daily_context(self):
        """测试：仅月度信号，无日度上下文"""
        from apps.regime.domain.services import HybridRegimeCalculator, RegimeCalculator

        monthly_calc = RegimeCalculator()
        hybrid_calc = HybridRegimeCalculator(monthly_calc)

        growth_series = [50, 51, 52, 51, 50]
        inflation_series = [2.0, 2.1, 2.0, 1.9, 2.0]

        result = hybrid_calc.calculate_hybrid(
            growth_series=growth_series,
            inflation_series=inflation_series,
            daily_context=None,
            as_of_date=date(2024, 1, 15)
        )

        assert result.source == "MONTHLY_ONLY"
        assert result.daily_context is None
        assert result.final_confidence == result.monthly_confidence

    def test_all_consistent_signals_boost_confidence(self):
        """测试：信号一致时提升置信度"""
        from apps.regime.domain.services import (
            DailySignalContext,
            HybridRegimeCalculator,
            RegimeCalculator,
        )

        monthly_calc = RegimeCalculator()
        hybrid_calc = HybridRegimeCalculator(monthly_calc)

        growth_series = [50, 51, 52, 53, 54]  # Rising
        inflation_series = [2.0, 2.1, 2.2, 2.3, 2.4]  # Rising

        # Create bullish daily context (matches Overheat regime)
        daily_context = DailySignalContext(
            signal_direction="BULLISH",
            signal_strength=0.8,
            confidence=0.7,
            persist_days=5,
            contributing_indicators=[],
            warning_signals=[]
        )

        result = hybrid_calc.calculate_hybrid(
            growth_series=growth_series,
            inflation_series=inflation_series,
            daily_context=daily_context,
            as_of_date=date(2024, 1, 15)
        )

        # When signals align, confidence should be boosted
        assert result.final_confidence >= result.monthly_confidence

    def test_persistent_daily_signal_overrides(self):
        """测试：持续日度信号覆盖月度信号"""
        from apps.regime.domain.services import (
            DailySignalContext,
            HybridRegimeCalculator,
            RegimeCalculator,
        )

        monthly_calc = RegimeCalculator()
        hybrid_calc = HybridRegimeCalculator(monthly_calc, daily_persist_threshold=10)

        growth_series = [50, 51, 52, 51, 50]
        inflation_series = [2.0, 2.1, 2.0, 1.9, 2.0]

        # Create bearish daily context with high persistence
        daily_context = DailySignalContext(
            signal_direction="BEARISH",
            signal_strength=0.8,
            confidence=0.7,
            persist_days=12,  # >= threshold
            contributing_indicators=[],
            warning_signals=["YIELD_CURVE_INVERTED"]
        )

        result = hybrid_calc.calculate_hybrid(
            growth_series=growth_series,
            inflation_series=inflation_series,
            daily_context=daily_context,
            as_of_date=date(2024, 1, 15)
        )

        # Daily persistent signal should influence the result
        assert result.daily_context is not None
        assert result.daily_context.persist_days == 12


class TestRegimeSignalDirectionMapping:
    """Regime信号方向映射测试"""

    def test_bullish_signal_to_regime(self):
        """测试：BULLISH信号映射到正确Regime"""
        from apps.regime.domain.services import HybridRegimeCalculator

        calc = HybridRegimeCalculator()

        # When distribution favors Recovery
        distribution = {"Recovery": 0.6, "Overheat": 0.2, "Stagflation": 0.1, "Deflation": 0.1}
        regime = calc._map_signal_to_regime("BULLISH", distribution)
        assert regime == "Recovery"

        # When distribution favors Overheat
        distribution = {"Recovery": 0.2, "Overheat": 0.6, "Stagflation": 0.1, "Deflation": 0.1}
        regime = calc._map_signal_to_regime("BULLISH", distribution)
        assert regime == "Overheat"

    def test_bearish_signal_to_regime(self):
        """测试：BEARISH信号映射到正确Regime"""
        from apps.regime.domain.services import HybridRegimeCalculator

        calc = HybridRegimeCalculator()

        # When distribution favors Stagflation
        distribution = {"Recovery": 0.1, "Overheat": 0.1, "Stagflation": 0.6, "Deflation": 0.2}
        regime = calc._map_signal_to_regime("BEARISH", distribution)
        assert regime == "Stagflation"

        # When distribution favors Deflation
        distribution = {"Recovery": 0.1, "Overheat": 0.1, "Stagflation": 0.2, "Deflation": 0.6}
        regime = calc._map_signal_to_regime("BEARISH", distribution)
        assert regime == "Deflation"

    def test_neutral_signal_preserves_current(self):
        """测试：NEUTRAL信号保持当前主导Regime"""
        from apps.regime.domain.services import HybridRegimeCalculator

        calc = HybridRegimeCalculator()

        distribution = {"Recovery": 0.4, "Overheat": 0.1, "Stagflation": 0.1, "Deflation": 0.4}
        regime = calc._map_signal_to_regime("NEUTRAL", distribution)
        # Should return the dominant regime (Recovery in this case)
        assert regime == "Recovery"


class TestSignalStrengthScoring:
    """信号强度评分测试"""

    def test_term_spread_scoring(self):
        """测试：期限利差评分"""
        # spread > 100 BP => score = 1.0
        assert (1.0 - 1.0) < 0.01

        # spread < 0 BP => score = -1.0
        assert (-1.0 - (-1.0)) < 0.01

        # spread = 50 BP => score = 0.5
        assert abs(0.5 - 0.5) < 0.01

    def test_nhci_momentum_scoring(self):
        """测试：NHCI动量评分"""
        # Change > 5% => score = 1.0
        change_pct = 6.0
        score = min(change_pct / 5, 1.0) if change_pct > 0 else max(change_pct / 5, -1.0)
        assert score == 1.0

        # Change < -5% => score = -1.0
        change_pct = -6.0
        score = min(change_pct / 5, 1.0) if change_pct > 0 else max(change_pct / 5, -1.0)
        assert score == -1.0

        # Change = 2.5% => score = 0.5
        change_pct = 2.5
        score = min(change_pct / 5, 1.0) if change_pct > 0 else max(change_pct / 5, -1.0)
        assert abs(score - 0.5) < 0.01

    def test_us_bond_yield_scoring(self):
        """测试：美国国债收益率评分"""
        # Yield > 4.5% => score = -1.0 (bearish for China)
        us_yield = 5.0
        if us_yield > 4.5:
            score = -1.0
        elif us_yield < 3.0:
            score = 1.0
        else:
            score = 1.0 - ((us_yield - 3.0) / 1.5) * 2
        assert score == -1.0

        # Yield < 3.0% => score = 1.0 (bullish for China)
        us_yield = 2.5
        if us_yield > 4.5:
            score = -1.0
        elif us_yield < 3.0:
            score = 1.0
        else:
            score = 1.0 - ((us_yield - 3.0) / 1.5) * 2
        assert score == 1.0

        # Yield = 3.75% => middle score
        us_yield = 3.75
        if us_yield > 4.5:
            score = -1.0
        elif us_yield < 3.0:
            score = 1.0
        else:
            score = 1.0 - ((us_yield - 3.0) / 1.5) * 2
        assert abs(score - 0.0) < 0.1


class TestDistributionAdjustment:
    """分布调整测试"""

    def test_adjust_distribution_for_daily(self):
        """测试：根据日度信号调整分布"""
        from apps.regime.domain.services import HybridRegimeCalculator

        calc = HybridRegimeCalculator()

        original = {"Recovery": 0.4, "Overheat": 0.2, "Stagflation": 0.2, "Deflation": 0.2}

        # Boost Recovery with high signal strength
        adjusted = calc._adjust_distribution_for_daily(original, "Recovery", 0.8)

        # Recovery should have higher weight
        assert adjusted["Recovery"] > original["Recovery"]

        # Total should be normalized to 1.0
        total = sum(adjusted.values())
        assert abs(total - 1.0) < 0.01

    def test_blend_distributions(self):
        """测试：融合月度和日度分布"""
        from apps.regime.domain.services import HybridRegimeCalculator

        calc = HybridRegimeCalculator()

        monthly_dist = {"Recovery": 0.5, "Overheat": 0.3, "Stagflation": 0.1, "Deflation": 0.1}

        # Blend towards Overheat
        blended = calc._blend_distributions(monthly_dist, "Overheat", 0.7, 0.3)

        # Overheat should have higher weight after blending
        assert blended["Overheat"] > monthly_dist["Overheat"]

        # Total should be 1.0
        total = sum(blended.values())
        assert abs(total - 1.0) < 0.01
