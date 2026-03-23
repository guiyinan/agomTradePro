"""
Test Regime Calculation V2 (Level-based)

测试基于绝对水平的 Regime 判定逻辑
"""

from datetime import date

import pytest

from apps.regime.domain.services_v2 import (
    RegimeCalculatorV2,
    RegimeType,
    ThresholdConfig,
    TrendIndicator,
    calculate_momentum_simple,
    calculate_regime_by_level,
    calculate_regime_distribution_by_level,
    classify_momentum_strength,
    generate_prediction,
)


class TestRegimeByLevel:
    """测试基于水平的 Regime 判定"""

    def test_deflation_regime(self):
        """测试通缩象限：PMI < 50, CPI 低"""
        regime = calculate_regime_by_level(pmi_value=49.3, cpi_value=0.8)
        assert regime == RegimeType.DEFLATION
        assert regime.value == "Deflation"

    def test_overheat_regime(self):
        """测试过热象限：PMI > 50, CPI 高"""
        regime = calculate_regime_by_level(pmi_value=52.0, cpi_value=3.0)
        assert regime == RegimeType.OVERHEAT

    def test_recovery_regime(self):
        """测试复苏象限：PMI > 50, CPI 低"""
        regime = calculate_regime_by_level(pmi_value=51.0, cpi_value=0.5)
        assert regime == RegimeType.RECOVERY

    def test_stagflation_regime(self):
        """测试滞胀象限：PMI < 50, CPI 高"""
        regime = calculate_regime_by_level(pmi_value=49.0, cpi_value=3.0)
        assert regime == RegimeType.STAGFLATION

    def test_custom_thresholds(self):
        """测试自定义阈值"""
        config = ThresholdConfig(
            pmi_expansion=51.0,  # 提高 PMI 阈值
            cpi_high=3.0,       # 提高 CPI 阈值
        )
        regime = calculate_regime_by_level(pmi_value=50.5, cpi_value=2.5, config=config)
        # PMI 50.5 < 51, CPI 2.5 < 3, 应该是通缩或复苏
        assert regime in [RegimeType.DEFLATION, RegimeType.RECOVERY]


class TestRegimeDistribution:
    """测试概率分布计算"""

    def test_distribution_sums_to_one(self):
        """测试概率总和为 1"""
        dist = calculate_regime_distribution_by_level(pmi_value=49.3, cpi_value=0.8)
        total = sum(dist.values())
        assert abs(total - 1.0) < 0.01

    def test_deflation_distribution(self):
        """测试通缩场景的分布"""
        dist = calculate_regime_distribution_by_level(pmi_value=49.0, cpi_value=0.5)
        # Deflation 应该是主导
        assert dist["Deflation"] > 0.4
        # Overheat 应该很低
        assert dist["Overheat"] < 0.2

    def test_overheat_distribution(self):
        """测试过热场景的分布"""
        dist = calculate_regime_distribution_by_level(pmi_value=52.0, cpi_value=3.0)
        # Overheat 应该是主导
        assert dist["Overheat"] > 0.4


class TestMomentumCalculation:
    """测试动量计算"""

    def test_momentum_up(self):
        """测试上升动量"""
        series = [49.0, 49.5, 50.0, 50.5]
        momentum, direction = calculate_momentum_simple(series, period=3)
        assert momentum > 0
        assert direction == 1

    def test_momentum_down(self):
        """测试下降动量"""
        series = [50.5, 50.0, 49.5, 49.0]
        momentum, direction = calculate_momentum_simple(series, period=3)
        assert momentum < 0
        assert direction == -1

    def test_momentum_flat(self):
        """测试持平"""
        series = [50.0, 50.1, 49.9, 50.0]
        momentum, direction = calculate_momentum_simple(series, period=3)
        assert abs(momentum) < 0.2
        assert direction == 0

    def test_strength_classification(self):
        """测试强度分类"""
        assert classify_momentum_strength(0.3) == "weak"
        assert classify_momentum_strength(1.0) == "moderate"
        assert classify_momentum_strength(2.0) == "strong"


class TestTrendIndicator:
    """测试趋势指标"""

    def test_trend_indicator_creation(self):
        """测试趋势指标创建"""
        indicator = TrendIndicator(
            indicator_code="PMI",
            current_value=49.3,
            momentum=0.3,
            momentum_z=0.5,
            direction="up",
            strength="moderate"
        )
        assert indicator.indicator_code == "PMI"
        assert indicator.current_value == 49.3
        assert indicator.direction == "up"


class TestRegimeCalculatorV2:
    """测试新的 Regime 计算器"""

    @pytest.fixture
    def calculator(self):
        return RegimeCalculatorV2()

    def test_calculate_with_current_data(self, calculator):
        """测试使用当前实际数据计算"""
        # 2025年12月/2026年1月的实际数据
        pmi_series = [50.2, 50.5, 49.0, 49.5, 49.7, 49.3, 49.4, 49.8, 49.0, 49.2, 50.1, 49.3]
        cpi_series = [0.5, -0.7, -0.1, -0.1, -0.1, 0.1, 0.0, -0.4, -0.3, 0.2, 0.7, 0.8]

        result = calculator.calculate(pmi_series, cpi_series, date(2026, 1, 31))

        # 验证结果
        assert result.regime == RegimeType.DEFLATION  # 修正：应该是通缩而非过热
        assert result.growth_level == 49.3
        assert result.inflation_level == 0.8
        assert result.growth_state == "contraction"
        assert result.inflation_state in ["low", "deflation"]
        assert len(result.trend_indicators) == 2
        assert result.confidence > 0.3

    def test_calculate_expansion_high_inflation(self, calculator):
        """测试扩张+高通胀（过热）"""
        pmi_series = [51.0, 51.5, 52.0]
        cpi_series = [2.5, 2.8, 3.0]

        result = calculator.calculate(pmi_series, cpi_series, date(2024, 1, 31))

        assert result.regime == RegimeType.OVERHEAT
        assert result.growth_state == "expansion"
        assert result.inflation_state == "high"

    def test_calculate_recovery(self, calculator):
        """测试复苏（扩张+低通胀）"""
        pmi_series = [50.0, 50.5, 51.0]
        cpi_series = [0.2, 0.3, 0.5]

        result = calculator.calculate(pmi_series, cpi_series, date(2024, 1, 31))

        assert result.regime == RegimeType.RECOVERY
        assert result.growth_state == "expansion"
        assert result.inflation_state == "low"

    def test_trend_indicators_populated(self, calculator):
        """测试趋势指标被正确填充"""
        pmi_series = [49.0, 49.5, 50.0]
        cpi_series = [0.5, 0.6, 0.8]

        result = calculator.calculate(pmi_series, cpi_series, date(2024, 1, 31))

        assert len(result.trend_indicators) == 2

        pmi_trend = next((t for t in result.trend_indicators if t.indicator_code == "PMI"), None)
        assert pmi_trend is not None
        assert pmi_trend.current_value == 50.0
        assert pmi_trend.momentum > 0  # 上升

        cpi_trend = next((t for t in result.trend_indicators if t.indicator_code == "CPI"), None)
        assert cpi_trend is not None
        assert cpi_trend.current_value == 0.8


class TestPrediction:
    """测试预测功能"""

    def test_deflation_recovery_prediction(self):
        """测试通缩转向复苏的预测"""
        prediction = generate_prediction(
            RegimeType.DEFLATION,
            pmi_trend=1,   # PMI 上升
            cpi_trend=0,   # CPI 持平
            trend_indicators=[]
        )
        assert "复苏" in prediction

    def test_overheat_cooling_prediction(self):
        """测试过热降温的预测"""
        prediction = generate_prediction(
            RegimeType.OVERHEAT,
            pmi_trend=-1,  # PMI 下降
            cpi_trend=-1,  # CPI 下降
            trend_indicators=[]
        )
        assert "降温" in prediction


if __name__ == "__main__":
    # 简单验证
    calculator = RegimeCalculatorV2()

    # 当前实际数据
    pmi_series = [50.2, 50.5, 49.0, 49.5, 49.7, 49.3, 49.4, 49.8, 49.0, 49.2, 50.1, 49.3]
    cpi_series = [0.5, -0.7, -0.1, -0.1, -0.1, 0.1, 0.0, -0.4, -0.3, 0.2, 0.7, 0.8]

    result = calculator.calculate(pmi_series, cpi_series, date(2026, 1, 31))

    print("=" * 60)
    print("Regime 计算结果（新版 - 基于水平）")
    print("=" * 60)
    print(f"Regime: {result.regime.value}")
    print(f"置信度: {result.confidence:.1%}")
    print(f"PMI: {result.growth_level} ({result.growth_state})")
    print(f"CPI: {result.inflation_level}% ({result.inflation_state})")
    print()
    print("概率分布:")
    for regime, prob in result.distribution.items():
        print(f"  {regime}: {prob:.2%}")
    print()
    print("趋势指标:")
    for t in result.trend_indicators:
        print(f"  {t.indicator_code}: {t.current_value}, 动量={t.momentum:+.2f} ({t.strength})")
    print()
    if result.prediction:
        print(f"预测: {result.prediction}")
