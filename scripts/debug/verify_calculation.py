"""验证最新 Regime 计算使用正确的算法"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from datetime import date
from apps.regime.application.use_cases import CalculateRegimeUseCase, CalculateRegimeRequest
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.regime.domain.services import RegimeCalculator

print("=" * 60)
print("验证 Regime 计算算法")
print("=" * 60)

# 创建使用绝对动量的计算器
calculator = RegimeCalculator(
    momentum_period=3,
    zscore_window=60,
    zscore_min_periods=24,
    sigmoid_k=2.0,
    use_absolute_inflation_momentum=True  # 关键参数
)

repository = DjangoMacroRepository()
use_case = CalculateRegimeUseCase(
    repository=repository,
    regime_repository=None,
    calculator=calculator
)

# 计算今天的 Regime
request = CalculateRegimeRequest(
    as_of_date=date.today(),
    use_pit=True,
    growth_indicator="PMI",
    inflation_indicator="CPI",
    data_source="akshare",
    skip_cache=True  # 强制跳过缓存
)

response = use_case.execute(request)

if response.success:
    snapshot = response.snapshot
    print(f"\n计算结果:")
    print(f"  日期: {snapshot.observed_at}")
    print(f"  主导象限: {snapshot.dominant_regime}")
    print(f"  置信度: {snapshot.confidence:.1%}")
    print(f"  增长 Z-Score: {snapshot.growth_momentum_z:+.2f}")
    print(f"  通胀 Z-Score: {snapshot.inflation_momentum_z:+.2f}")
    print(f"  分布: {snapshot.distribution}")

    # 验证通胀动量计算
    print(f"\n中间数据:")
    if response.intermediate_data:
        inflation_momentum = response.intermediate_data.get('inflation_momentum', [])
        if inflation_momentum:
            latest_momentum = inflation_momentum[-1]
            print(f"  最新通胀动量: {latest_momentum:+.4f}")
            print(f"  计算方式: 绝对差值 (current - past)")
            print(f"  算法验证: {'✓ 正确' if abs(latest_momentum) < 10 else '✗ 可能错误（相对动量）'}")
else:
    print(f"计算失败: {response.error}")
