"""
AgomSAAF 核心算法验证脚本

独立验证系统核心算法的正确性，不依赖 Django。
"""

import sys
from datetime import date
from typing import List, Dict

# 测试 Regime 算法
def test_regime_algorithm():
    """测试 Regime 判定算法"""
    print("=" * 60)
    print("Regime 判定算法测试")
    print("=" * 60)

    from apps.regime.domain.services import (
        RegimeCalculator,
        calculate_regime_distribution,
        sigmoid,
        calculate_momentum,
        calculate_rolling_zscore,
    )

    # 测试 1: Sigmoid 函数
    print("\n1. Sigmoid 函数测试:")
    print(f"   sigmoid(0) = {sigmoid(0):.4f} (期望: 0.5)")
    print(f"   sigmoid(1) = {sigmoid(1):.4f} (期望: >0.5)")
    print(f"   sigmoid(-1) = {sigmoid(-1):.4f} (期望: <0.5)")

    # 测试 2: Regime 分布
    print("\n2. Regime 分布测试:")
    dist = calculate_regime_distribution(0, 0, correlation=0.3)
    print(f"   中性状态 (z=0,0): {dist}")
    print(f"   总和: {sum(dist.values()):.4f} (期望: 1.0)")

    dist_recovery = calculate_regime_distribution(2, -2, correlation=0.3)
    print(f"   复苏象限 (z=2,-2): Recovery={dist_recovery['Recovery']:.2%}")

    # 测试 3: 动量计算
    print("\n3. 动量计算测试:")
    series = [100, 102, 105, 110, 108, 106]
    momentum = calculate_momentum(series, period=3)
    print(f"   序列: {series}")
    print(f"   3月动量: {momentum}")

    # 测试 4: Z-score 计算
    print("\n4. Z-score 计算测试:")
    z_scores = calculate_rolling_zscore(series, window=5, min_periods=3)
    print(f"   Z-score: {[f'{z:.2f}' for z in z_scores]}")

    # 测试 5: 完整 Regime 计算
    print("\n5. 完整 Regime 计算测试:")
    calculator = RegimeCalculator(
        momentum_period=3,
        zscore_window=24,
        zscore_min_periods=12,
        sigmoid_k=2.0,
        correlation=0.3
    )

    # 模拟历史数据
    import random
    random.seed(42)
    growth_data = [50 + random.gauss(0, 2) for _ in range(30)]
    inflation_data = [2.0 + random.gauss(0, 0.5) for _ in range(30)]

    result = calculator.calculate(growth_data, inflation_data, date(2024, 1, 31))

    print(f"   增长动量 Z-score: {result.snapshot.growth_momentum_z:.3f}")
    print(f"   通胀动量 Z-score: {result.snapshot.inflation_momentum_z:.3f}")
    print(f"   主导 Regime: {result.snapshot.dominant_regime}")
    print(f"   置信度: {result.snapshot.confidence_percent:.1f}%")
    print(f"   分布: ")
    for regime, prob in result.snapshot.distribution.items():
        print(f"     {regime}: {prob:.2%}")
    if result.warnings:
        print(f"   警告: {result.warnings}")

    return True


def test_invalidation_algorithm():
    """测试证伪逻辑算法"""
    print("\n" + "=" * 60)
    print("证伪逻辑算法测试")
    print("=" * 60)

    from apps.signal.domain.invalidation import (
        InvalidationCondition,
        InvalidationRule,
        LogicOperator,
        ComparisonOperator,
        evaluate_rule,
        IndicatorValue,
        IndicatorType,
    )
    from apps.signal.domain.indicators import get_all_indicators

    # 测试 1: 条件创建
    print("\n1. 条件创建测试:")
    from apps.signal.domain.invalidation import IndicatorType
    cond = InvalidationCondition(
        indicator_code="CN_PMI_MANUFACTURING",
        indicator_type=IndicatorType.MACRO,
        operator=ComparisonOperator.LT,
        threshold=50.0
    )
    print(f"   条件: PMI < 50")
    print(f"   条件创建成功: {cond is not None}")

    # 测试 2: 规则创建
    print("\n2. 规则创建测试:")
    rule = InvalidationRule(
        conditions=[
            InvalidationCondition(
                indicator_code="CN_PMI_MANUFACTURING",
                indicator_type=IndicatorType.MACRO,
                operator=ComparisonOperator.LT,
                threshold=50.0
            ),
            InvalidationCondition(
                indicator_code="CN_CPI_YOY",
                indicator_type=IndicatorType.MACRO,
                operator=ComparisonOperator.LT,
                threshold=2.0
            )
        ],
        logic=LogicOperator.AND
    )
    print(f"   规则: PMI < 50 AND CPI < 2.0")
    print(f"   规则创建成功: {rule is not None}")

    # 测试 3: 规则评估
    print("\n3. 规则评估测试:")
    indicator_values = {
        "CN_PMI_MANUFACTURING": IndicatorValue(
            code="CN_PMI_MANUFACTURING",
            current_value=49.5,
            history_values=[50.0, 49.8, 49.5],
            unit="指数",
            last_updated="2024-01-31"
        ),
        "CN_CPI_YOY": IndicatorValue(
            code="CN_CPI_YOY",
            current_value=1.8,
            history_values=[2.0, 1.9, 1.8],
            unit="%",
            last_updated="2024-01-31"
        )
    }

    eval_result = evaluate_rule(rule, indicator_values)
    print(f"   PMI = 49.5, CPI = 1.8")
    print(f"   规则触发 (证伪): {eval_result.is_invalidated}")
    print(f"   检查原因: {eval_result.reason}")

    # 测试 4: 规则序列化
    print("\n4. 规则序列化测试:")
    rule_dict = rule.to_dict()
    print(f"   规则字典: 条件数={len(rule_dict['conditions'])}")

    # 测试 5: 指标注册表
    print("\n5. 指标注册表测试:")
    all_indicators = get_all_indicators()
    print(f"   已注册指标数: {len(all_indicators)}")
    for ind in all_indicators[:3]:
        print(f"   - {ind.name} ({ind.code})")

    return True


def test_stop_loss_algorithm():
    """测试止损算法"""
    print("\n" + "=" * 60)
    print("止损控制算法测试")
    print("=" * 60)

    from apps.account.domain.services import StopLossService

    # 测试 1: 固定止损
    print("\n1. 固定止损测试:")
    result = StopLossService.check_stop_loss(
        entry_price=100.0,
        current_price=89.0,
        highest_price=100.0,
        stop_loss_pct=0.10,  # 10%
        stop_loss_type="fixed",
    )
    print(f"   入场价: 100, 当前价: 89, 止损比例: 10%")
    print(f"   止损价: {result.stop_price:.2f}")
    print(f"   触发止损: {result.should_trigger}")
    print(f"   原因: {result.trigger_reason}")

    # 测试 2: 移动止损
    print("\n2. 移动止损测试:")
    result = StopLossService.check_stop_loss(
        entry_price=100.0,
        current_price=115.0,
        highest_price=115.0,
        stop_loss_pct=0.05,  # 5% 移动止损
        stop_loss_type="trailing",
    )
    print(f"   入场价: 100, 当前价: 115, 最高价: 115")
    print(f"   移动止损价: {result.stop_price:.2f}")
    print(f"   触发止损: {result.should_trigger}")

    # 测试 3: 未触发止损
    print("\n3. 未触发止损测试:")
    result = StopLossService.check_stop_loss(
        entry_price=100.0,
        current_price=95.0,
        highest_price=100.0,
        stop_loss_pct=0.10,
        stop_loss_type="fixed",
    )
    print(f"   当前价 95 > 止损价 90")
    print(f"   触发止损: {result.should_trigger}")

    return True


def test_volatility_control_algorithm():
    """测试波动率控制算法"""
    print("\n" + "=" * 60)
    print("波动率控制算法测试")
    print("=" * 60)

    from apps.account.domain.services import VolatilityTargetService

    # 测试 1: 无需调整
    print("\n1. 无需调整测试:")
    result = VolatilityTargetService.assess_volatility_adjustment(
        current_volatility=0.15,
        target_volatility=0.15,
        tolerance=0.1,
        max_reduction=0.5,
    )
    print(f"   当前波动率: {result.current_volatility:.1%}")
    print(f"   目标波动率: {result.target_volatility:.1%}")
    print(f"   需要调整: {result.should_reduce}")

    # 测试 2: 需要调整
    print("\n2. 需要调整测试:")
    result = VolatilityTargetService.assess_volatility_adjustment(
        current_volatility=0.25,
        target_volatility=0.15,
        tolerance=0.1,
        max_reduction=0.5,
    )
    print(f"   当前波动率: {result.current_volatility:.1%}")
    print(f"   目标波动率: {result.target_volatility:.1%}")
    print(f"   波动率比率: {result.volatility_ratio:.2f}")
    print(f"   建议仓位乘数: {result.suggested_position_multiplier:.1%}")
    print(f"   调整原因: {result.reduction_reason}")

    return True


def test_backtest_pit_algorithm():
    """测试回测 PIT 算法"""
    print("\n" + "=" * 60)
    print("回测 Point-in-Time 算法测试")
    print("=" * 60)

    from apps.backtest.domain.services import PITDataProcessor
    from datetime import timedelta, date

    # 创建 PIT 处理器
    processor = PITDataProcessor(
        publication_lags={
            "PMI": timedelta(days=35),  # PMI 滞后 35 天发布
            "CPI": timedelta(days=10),  # CPI 滞后 10 天发布
        }
    )

    # 测试 1: 获取发布日期
    print("\n1. 发布日期计算:")
    obs_date = date(2024, 1, 31)
    pub_date = processor.get_publication_date(obs_date, "PMI")
    print(f"   PMI 观测日期: {obs_date}")
    print(f"   PMI 发布日期: {pub_date} (滞后35天)")

    # 测试 2: 数据可用性检查
    print("\n2. 数据可用性检查:")
    check_date = date(2024, 3, 10)
    available = processor.is_data_available(obs_date, "PMI", check_date)
    print(f"   检查日期: {check_date}")
    print(f"   PMI(1月) 是否可用: {available}")

    # 测试 3: 获取最新可用数据
    print("\n3. 获取最新可用数据:")
    data_points = [
        (date(2023, 12, 31), 49.5),
        (date(2024, 1, 31), 50.1),
        (date(2024, 2, 29), 49.8),
    ]
    latest = processor.get_latest_available_value(data_points, "PMI", check_date)
    if latest:
        print(f"   最新可用数据: {latest[0]} -> {latest[1]}")
    else:
        print(f"   无可用数据")

    return True


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("AgomSAAF 核心算法验证")
    print("=" * 60)

    tests = [
        ("Regime 判定算法", test_regime_algorithm),
        ("证伪逻辑算法", test_invalidation_algorithm),
        ("止损控制算法", test_stop_loss_algorithm),
        ("波动率控制算法", test_volatility_control_algorithm),
        ("回测 PIT 算法", test_backtest_pit_algorithm),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"\n[X] {name} 测试失败: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"算法验证完成: {passed} 通过, {failed} 失败")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
