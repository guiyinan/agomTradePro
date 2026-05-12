"""
初始化配置数据脚本

从硬编码迁移到数据库配置。
"""

import os
import sys

import django

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.asset_analysis.infrastructure.models import (
    AssetConfigModel,
)
from apps.filter.infrastructure.models import (
    FilterParameterConfigModel,
)
from apps.macro.infrastructure.models import (
    IndicatorConfigModel,
)
from apps.regime.infrastructure.models import (
    RegimeEligibilityConfigModel,
    RiskParameterConfigModel,
)


def init_asset_config():
    """初始化资产配置"""
    configs = [
        {
            'asset_class': 'a_share_growth',
            'display_name': 'A股成长',
            'ticker_symbol': '000300.SH',
            'data_source': 'tushare',
            'category': 'equity',
            'description': '沪深300指数作为成长风格 proxy',
        },
        {
            'asset_class': 'a_share_value',
            'display_name': 'A股价值',
            'ticker_symbol': '000905.SH',
            'data_source': 'tushare',
            'category': 'equity',
            'description': '中证500指数作为价值风格 proxy',
        },
        {
            'asset_class': 'china_bond',
            'display_name': '中债',
            'ticker_symbol': 'H11025.CSI',
            'data_source': 'tushare',
            'category': 'bond',
            'description': '中债总财富指数',
        },
        {
            'asset_class': 'gold',
            'display_name': '黄金',
            'ticker_symbol': 'AU9999.SGE',
            'data_source': 'tushare',
            'category': 'commodity',
            'description': '上海黄金现货',
        },
        {
            'asset_class': 'commodity',
            'display_name': '商品',
            'ticker_symbol': 'NH0100.NHF',
            'data_source': 'tushare',
            'category': 'commodity',
            'description': '南华商品指数',
        },
        {
            'asset_class': 'cash',
            'display_name': '现金',
            'ticker_symbol': '',
            'data_source': '',
            'category': 'cash',
            'description': '现金类资产',
        },
    ]

    for config in configs:
        AssetConfigModel.objects.update_or_create(
            asset_class=config['asset_class'],
            defaults=config
        )
    print(f"[OK] AssetConfigModel initialized: {len(configs)} records")


def init_indicator_config():
    """初始化指标配置"""
    # 从现有的硬编码中提取
    from apps.macro.application.indicator_service import IndicatorService

    for code, metadata in IndicatorService.INDICATOR_METADATA.items():
        IndicatorConfigModel.objects.update_or_create(
            code=code,
            defaults={
                'name': metadata.get('name', code),
                'name_en': metadata.get('name_en', ''),
                'category': metadata.get('category', 'other'),
                'unit': metadata.get('unit', ''),
                'threshold_bullish': metadata.get('threshold_bullish'),
                'threshold_bearish': metadata.get('threshold_bearish'),
                'description': metadata.get('description', ''),
                'is_active': True
            }
        )
    print("[OK] IndicatorConfigModel initialized")


def init_regime_eligibility():
    """初始化准入矩阵配置"""
    # 从现有硬编码中提取
    from apps.signal.domain.rules import DEFAULT_ELIGIBILITY_MATRIX, Eligibility

    for asset_class, regime_map in DEFAULT_ELIGIBILITY_MATRIX.items():
        for regime, eligibility in regime_map.items():
            RegimeEligibilityConfigModel.objects.update_or_create(
                asset_class=asset_class,
                regime=regime,
                defaults={
                    'eligibility': eligibility.value,
                    'is_active': True
                }
            )
    print("[OK] RegimeEligibilityConfigModel initialized")


def init_risk_parameters():
    """初始化风险参数配置"""
    # 仓位配置
    position_configs = [
        {
            'key': 'position_p0',
            'name': 'P0 档位仓位',
            'parameter_type': 'position_size',
            'value_float': 1.0,
            'policy_level': 'P0',
            'description': 'P0（常态）下的标准仓位',
        },
        {
            'key': 'position_p1',
            'name': 'P1 档位仓位',
            'parameter_type': 'position_size',
            'value_float': 0.8,
            'policy_level': 'P1',
            'description': 'P1（预警）下的降低仓位',
        },
        {
            'key': 'position_p2',
            'name': 'P2 档位仓位',
            'parameter_type': 'position_size',
            'value_float': 0.5,
            'policy_level': 'P2',
            'description': 'P2（干预）下的进一步降低仓位',
        },
        {
            'key': 'position_p3',
            'name': 'P3 档位仓位',
            'parameter_type': 'position_size',
            'value_float': 0.0,
            'policy_level': 'P3',
            'description': 'P3（危机）下的完全退出',
        },
    ]

    # Regime 调整因子
    adjustment_configs = [
        {
            'key': 'adjustment_recovery',
            'name': '复苏期调整因子',
            'parameter_type': 'adjustment_factor',
            'value_float': 1.2,
            'regime': 'Recovery',
            'description': 'Recovery Regime 下的仓位提升',
        },
        {
            'key': 'adjustment_stagflation',
            'name': '滞胀期调整因子',
            'parameter_type': 'adjustment_factor',
            'value_float': 0.7,
            'regime': 'Stagflation',
            'description': 'Stagflation Regime 下的仓位降低',
        },
    ]

    all_configs = position_configs + adjustment_configs

    for config in all_configs:
        RiskParameterConfigModel.objects.update_or_create(
            key=config['key'],
            defaults=config
        )
    print(f"[OK] RiskParameterConfigModel initialized: {len(all_configs)} records")


def init_filter_parameters():
    """初始化滤波参数配置"""
    configs = [
        {
            'key': 'hp_monthly',
            'name': 'HP 滤波（月度）',
            'filter_type': 'hp',
            'parameters': {'lambda': 129600},
            'data_frequency': 'M',
            'description': '月度宏观数据的 HP 滤波参数',
        },
        {
            'key': 'kalman_macro',
            'name': 'Kalman 滤波（宏观）',
            'filter_type': 'kalman',
            'parameters': {
                'level_variance': 0.05,
                'slope_variance': 0.005,
                'observation_variance': 0.5,
            },
            'indicator_category': 'growth',
            'description': '宏观指标的 Kalman 滤波参数',
        },
    ]

    for config in configs:
        FilterParameterConfigModel.objects.update_or_create(
            key=config['key'],
            defaults=config
        )
    print(f"[OK] FilterParameterConfigModel initialized: {len(configs)} records")


def main():
    """执行所有初始化"""
    print("[INFO] 开始初始化配置数据...")
    print()

    init_asset_config()
    init_indicator_config()
    init_regime_eligibility()
    init_risk_parameters()
    init_filter_parameters()

    print()
    print("[SUCCESS] 配置数据初始化完成！")
    print()
    print("[TIP] 提示：可以通过 Django Admin 后台修改这些配置")


if __name__ == '__main__':
    main()
