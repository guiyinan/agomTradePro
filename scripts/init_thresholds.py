"""
初始化阈值配置

Usage:
    python manage.py shell < scripts/init_thresholds.py
    python scripts/init_thresholds.py
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from shared.infrastructure.models import RiskParameterConfigModel


# 默认阈值配置
DEFAULT_THRESHOLDS = [
    # Regime 计算相关
    {
        'key': 'regime_confidence_low',
        'name': 'Regime 低置信度阈值',
        'parameter_type': 'other',
        'value_float': 0.3,
        'description': '当 Regime 置信度低于此值时，触发降级方案',
        'is_active': True
    },
    {
        'key': 'regime_confidence_critical',
        'name': 'Regime 临界置信度阈值',
        'parameter_type': 'other',
        'value_float': 0.1,
        'description': '当 Regime 置信度低于此值时，拒绝使用该 Regime',
        'is_active': True
    },
    {
        'key': 'regime_min_data_points',
        'name': 'Regime 计算最小数据点',
        'parameter_type': 'other',
        'value_float': 24.0,
        'description': '计算 Regime 至少需要 24 个月的数据',
        'is_active': True
    },
    {
        'key': 'regime_momentum_period',
        'name': 'Regime 动量计算周期',
        'parameter_type': 'other',
        'value_float': 3.0,
        'description': '动量计算周期（月）',
        'is_active': True
    },
    {
        'key': 'regime_zscore_window',
        'name': 'Regime Z-score 窗口',
        'parameter_type': 'other',
        'value_float': 60.0,
        'description': 'Z-score 计算滚动窗口（月）',
        'is_active': True
    },
    # 政策档位相关
    {
        'key': 'policy_p2_position_adjustment',
        'name': 'P2 档位仓位调整',
        'parameter_type': 'position_size',
        'policy_level': 'P2',
        'value_float': -20.0,
        'description': 'P2 档位时降低仓位 20%',
        'is_active': True
    },
    {
        'key': 'policy_p3_position_adjustment',
        'name': 'P3 档位仓位调整',
        'parameter_type': 'position_size',
        'policy_level': 'P3',
        'value_float': -50.0,
        'description': 'P3 档位时降低仓位 50%',
        'is_active': True
    },
    {
        'key': 'policy_p3_signal_pause_hours',
        'name': 'P3 信号暂停时长',
        'parameter_type': 'other',
        'policy_level': 'P3',
        'value_float': 48.0,
        'description': 'P3 档位时暂停新信号 48 小时',
        'is_active': True
    },
    # 仓位限制
    {
        'key': 'position_max_single_asset',
        'name': '单一资产最大仓位',
        'parameter_type': 'position_size',
        'value_float': 20.0,
        'description': '单一资产最大仓位百分比（激进型）',
        'is_active': True
    },
    {
        'key': 'position_max_single_asset_conservative',
        'name': '单一资产最大仓位（保守）',
        'parameter_type': 'position_size',
        'value_float': 5.0,
        'description': '单一资产最大仓位百分比（保守型）',
        'is_active': True
    },
    {
        'key': 'position_max_single_asset_moderate',
        'name': '单一资产最大仓位（稳健）',
        'parameter_type': 'position_size',
        'value_float': 10.0,
        'description': '单一资产最大仓位百分比（稳健型）',
        'is_active': True
    },
    # 止损止盈
    {
        'key': 'stop_loss_default_pct',
        'name': '默认止损百分比',
        'parameter_type': 'stop_loss',
        'value_float': -10.0,
        'description': '默认止损线 -10%',
        'is_active': True
    },
    {
        'key': 'stop_loss_aggressive_pct',
        'name': '激进止损百分比',
        'parameter_type': 'stop_loss',
        'value_float': -15.0,
        'description': '激进型止损线 -15%',
        'is_active': True
    },
    {
        'key': 'take_profit_default_pct',
        'name': '默认止盈百分比',
        'parameter_type': 'stop_loss',
        'value_float': 20.0,
        'description': '默认止盈线 +20%',
        'is_active': True
    },
    {
        'key': 'trailing_stop_pct',
        'name': '移动止损百分比',
        'parameter_type': 'stop_loss',
        'value_float': 10.0,
        'description': '移动止损触发百分比',
        'is_active': True
    },
    # 波动率控制
    {
        'key': 'volatility_target_conservative',
        'name': '目标波动率（保守）',
        'parameter_type': 'volatility',
        'value_float': 10.0,
        'description': '保守型目标年化波动率 10%',
        'is_active': True
    },
    {
        'key': 'volatility_target_moderate',
        'name': '目标波动率（稳健）',
        'parameter_type': 'volatility',
        'value_float': 15.0,
        'description': '稳健型目标年化波动率 15%',
        'is_active': True
    },
    {
        'key': 'volatility_target_aggressive',
        'name': '目标波动率（激进）',
        'parameter_type': 'volatility',
        'value_float': 20.0,
        'description': '激进型目标年化波动率 20%',
        'is_active': True
    },
    {
        'key': 'volatility_adjustment_threshold',
        'name': '波动率调整触发阈值',
        'parameter_type': 'volatility',
        'value_float': 1.2,
        'description': '实际波动率超过目标 1.2 倍时触发调整',
        'is_active': True
    },
    # 多维限额
    {
        'key': 'limit_max_style_concentration',
        'name': '风格最大集中度',
        'parameter_type': 'position_size',
        'value_float': 40.0,
        'description': '单一投资风格最大占比 40%',
        'is_active': True
    },
    {
        'key': 'limit_max_sector_concentration',
        'name': '行业最大集中度',
        'parameter_type': 'position_size',
        'value_float': 25.0,
        'description': '单一行业板块最大占比 25%',
        'is_active': True
    },
    {
        'key': 'limit_max_foreign_currency',
        'name': '外币资产最大占比',
        'parameter_type': 'position_size',
        'value_float': 30.0,
        'description': '非本币资产最大占比 30%',
        'is_active': True
    },
]


def init_thresholds():
    """初始化阈值配置"""
    print("开始初始化阈值配置...")

    created_count = 0
    updated_count = 0
    skipped_count = 0

    for threshold_data in DEFAULT_THRESHOLDS:
        key = threshold_data['key']

        # 检查是否已存在
        try:
            existing = RiskParameterConfigModel.objects.get(key=key)
            print(f"  [更新] {key} - {threshold_data['name']}")
            # 更新字段
            for field_name, value in threshold_data.items():
                setattr(existing, field_name, value)
            existing.save()
            updated_count += 1
        except RiskParameterConfigModel.DoesNotExist:
            print(f"  [创建] {key} - {threshold_data['name']}")
            RiskParameterConfigModel.objects.create(**threshold_data)
            created_count += 1
        except Exception as e:
            print(f"  [跳过] {key} - {e}")
            skipped_count += 1

    print(f"\n初始化完成:")
    print(f"  新建: {created_count}")
    print(f"  更新: {updated_count}")
    print(f"  跳过: {skipped_count}")
    print(f"  总计: {len(DEFAULT_THRESHOLDS)}")


if __name__ == '__main__':
    init_thresholds()
