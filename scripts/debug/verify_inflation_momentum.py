"""验证通胀动量计算是否正确使用绝对差值算法"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.regime.domain.services import calculate_absolute_momentum, calculate_rolling_zscore
import json

# 获取 CPI 数据
repo = DjangoMacroRepository()
cpi_data = repo.get_inflation_series_full(
    indicator_code="CPI",
    end_date=None,
    use_pit=False,
    source="akshare"
)

print("CPI 数据（最新20条）:")
print("-" * 50)
for data in cpi_data[-20:]:
    print(f"{data.reporting_period}: CPI={data.value:.2f}%")

print("\n" + "="*50)
print("通胀动量计算验证:")
print("="*50)

# 提取 CPI 序列
cpi_series = [d.value for d in cpi_data]

# 使用绝对差值动量
inflation_momentums = calculate_absolute_momentum(cpi_series, period=3)

# 计算 Z-score
inflation_z_scores = calculate_rolling_zscore(inflation_momentums, window=60, min_periods=24)

print("\n最近10个月的通胀动量和 Z-score:")
print("-" * 60)
for i in range(max(0, len(cpi_data) - 10), len(cpi_data)):
    cpi_value = cpi_series[i]
    momentum = inflation_momentums[i]
    z_score = inflation_z_scores[i]
    print(f"{cpi_data[i].reporting_period}: CPI={cpi_value:.2f}% -> 动量={momentum:+.3f}pp -> Z={z_score:+.2f}")

# 验证：手动计算最后一个动量
if len(cpi_series) >= 4:
    current = cpi_series[-1]
    past = cpi_series[-4]  # 3个月前
    manual_momentum = current - past
    print(f"\n验证最后一个动量计算:")
    print(f"  当前 CPI: {current:.2f}%")
    print(f"  3个月前 CPI: {past:.2f}%")
    print(f"  绝对差值动量: {current:.2f} - {past:.2f} = {manual_momentum:+.3f}pp")
    print(f"  代码计算动量: {inflation_momentums[-1]:+.3f}pp")
    print(f"  匹配: {abs(manual_momentum - inflation_momentums[-1]) < 0.001}")
