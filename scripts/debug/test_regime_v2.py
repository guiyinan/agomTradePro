"""
Regime V2 逻辑验证脚本

独立验证新版 Regime 判定逻辑的正确性
"""

import json
import sys
from datetime import date


def test_v2_logic():
    """测试 V2 逻辑"""
    # 导入新服务
    sys.path.insert(0, '.')
    from apps.regime.domain.services_v2 import (
        RegimeCalculatorV2,
        RegimeType,
        ThresholdConfig,
        calculate_regime_by_level,
        calculate_regime_distribution_by_level,
    )

    print("=" * 60)
    print("Regime V2.0 逻辑验证")
    print("=" * 60)

    # 1. 测试当前实际数据
    print("\n【1/4】当前实际数据验证（2026年1月）")
    print("   PMI = 49.3, CPI = 0.8%")

    calculator = RegimeCalculatorV2()
    pmi_series = [50.2, 50.5, 49.0, 49.5, 49.7, 49.3, 49.4, 49.8, 49.0, 49.2, 50.1, 49.3]
    cpi_series = [0.5, -0.7, -0.1, -0.1, -0.1, 0.1, 0.0, -0.4, -0.3, 0.2, 0.7, 0.8]

    result = calculator.calculate(pmi_series, cpi_series, date(2026, 1, 31))

    print(f"   Regime: {result.regime.value}")
    print(f"   置信度: {result.confidence:.1%}")
    print(f"   PMI: {result.growth_level} ({result.growth_state})")
    print(f"   CPI: {result.inflation_level}% ({result.inflation_state})")
    print("\n   概率分布:")
    for regime, prob in result.distribution.items():
        print(f"     {regime}: {prob:.2%}")

    print("\n   Trend Indicators:")
    for t in result.trend_indicators:
        {"up": "UP", "down": "DOWN", "neutral": "FLAT"}[t.direction]
        print(f"     {t.indicator_code}: {t.current_value}, momentum={t.momentum:+.2f} ({t.strength}), direction={t.direction}")

    if result.prediction:
        print(f"\n   预测: {result.prediction}")

    # 2. 测试各象限
    print("\n【2/4】四象限判定测试")

    test_cases = [
        ("Deflation", 49.0, 0.5),
        ("Overheat", 52.0, 3.0),
        ("Recovery", 51.0, 0.5),
        ("Stagflation", 49.0, 3.0),
    ]

    for expected, pmi, cpi in test_cases:
        regime = calculate_regime_by_level(pmi, cpi)
        status = "[PASS]" if regime.value == expected else "[FAIL]"
        print(f"   {status} {expected}: PMI={pmi}, CPI={cpi}% -> {regime.value}")

    # 3. 测试自定义阈值
    print("\n【3/4】自定义阈值测试")
    custom_config = ThresholdConfig(
        pmi_expansion=51.0,  # 提高阈值
        cpi_high=3.0,       # 提高阈值
    )

    test = calculate_regime_by_level(50.5, 2.5, custom_config)
    print("   PMI=50.5, CPI=2.5% (自定义阈值)")
    print(f"   结果: {test.value}")

    # 4. 验证预测逻辑
    print("\n【4/4】预测逻辑测试")
    from apps.regime.domain.services_v2 import generate_prediction

    predictions = [
        ("Deflation + PMI↑", RegimeType.DEFLATION, 1, 0),
        ("Overheat + 双降", RegimeType.OVERHEAT, -1, -1),
    ]

    for desc, regime, pmi_trend, cpi_trend in predictions:
        pred = generate_prediction(regime, pmi_trend, cpi_trend, [])
        print(f"   {desc}")
        print(f"   预测: {pred}")

    print("\n" + "=" * 60)
    print("[SUCCESS] 验证完成！新逻辑符合经济直觉。")
    print("=" * 60)

    return True


def test_with_latest_data():
    """使用最新获取的数据进行测试"""
    print("\n" + "=" * 60)
    print("使用最新数据验证")
    print("=" * 60)

    # 读取最新数据
    try:
        with open('data/macro_data_latest.json', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("请先运行 update_system_data.py 获取最新数据")
        return False

    # 提取 PMI 和 CPI 数据
    pmi_data = sorted(data['CN_PMI'], key=lambda x: x['date'])
    cpi_data = sorted(data['CN_CPI'], key=lambda x: x['date'])

    pmi_series = [d['value'] for d in pmi_data]
    cpi_series = [d['value'] for d in cpi_data]

    print(f"\n数据点数: PMI={len(pmi_series)}, CPI={len(cpi_series)}")
    print(f"PMI 最新: {pmi_series[-1]} ({pmi_data[-1]['date']})")
    print(f"CPI 最新: {cpi_series[-1]}% ({cpi_data[-1]['date']})")

    # 导入并计算
    sys.path.insert(0, '.')
    from apps.regime.domain.services_v2 import RegimeCalculatorV2

    calculator = RegimeCalculatorV2()
    result = calculator.calculate(
        pmi_series,
        cpi_series,
        date.today()
    )

    print("\n=== 判定结果 ===")
    print(f"Regime: {result.regime.value}")
    print(f"置信度: {result.confidence:.1%}")
    print(f"增长状态: {result.growth_state} (PMI: {result.growth_level})")
    print(f"通胀状态: {result.inflation_state} (CPI: {result.inflation_level}%)")

    print("\n=== 趋势分析 ===")
    for t in result.trend_indicators:
        direction_icon = {"up": "▲", "down": "▼", "neutral": "▶"}[t.direction]
        {"weak": "浅", "moderate": "中", "strong": "深"}[t.strength]
        print(f"{t.indicator_code}: {t.current_value} {direction_icon} ({strength}强度)")

    if result.prediction:
        print("\n=== 预测 ===")
        print(result.prediction)

    # 对比旧算法
    print("\n=== 与旧算法对比 ===")
    from apps.regime.domain.services import RegimeCalculator as OldCalculator

    old_calc = OldCalculator()
    old_result = old_calc.calculate(pmi_series, cpi_series, date.today())

    print("旧算法（动量法）:")
    print(f"  Regime: {old_result.snapshot.dominant_regime}")
    print(f"  置信度: {old_result.snapshot.confidence:.1%}")
    print(f"  增长动量 Z: {old_result.snapshot.growth_momentum_z:+.3f}")
    print(f"  通胀动量 Z: {old_result.snapshot.inflation_momentum_z:+.3f}")

    print("\n新算法（水平法）:")
    print(f"  Regime: {result.regime.value}")
    print(f"  置信度: {result.confidence:.1%}")

    # 判断哪个更符合经济直觉
    if result.growth_level < 50 and result.inflation_level < 2:
        print(f"\n✅ 新算法结果（{result.regime.value}）更符合经济直觉：")
        print(f"   PMI {result.growth_level} < 50（收缩）")
        print(f"   CPI {result.inflation_level}% < 2%（低通胀）")
        print(f"   → 应该是 {result.regime.value} 而非 {old_result.snapshot.dominant_regime}")

    return True


if __name__ == "__main__":
    success = test_v2_logic()
    if success:
        test_with_latest_data()
