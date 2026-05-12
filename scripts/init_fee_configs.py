"""
费率配置初始化脚本

初始化模拟盘交易费率配置，包括：
1. 标准费率（万3佣金）
2. VIP费率（万2佣金）
3. 低佣费率（万1.5佣金）
4. 基金费率（免佣）

Usage:
    python manage.py shell < scripts/init_fee_configs.py
    或
    python scripts/init_fee_configs.py
"""
import os
import sys

import django

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.simulated_trading.infrastructure.models import FeeConfigModel


def init_fee_configs():
    """初始化费率配置"""

    # 1. 标准费率配置（股票）
    standard_equity, created = FeeConfigModel.objects.get_or_create(
        config_name="标准费率-股票",
        defaults={
            'asset_type': 'equity',
            'commission_rate_buy': 0.0003,      # 万3
            'commission_rate_sell': 0.0003,     # 万3
            'min_commission': 5.0,              # 最低5元
            'stamp_duty_rate': 0.001,           # 0.1%印花税(卖出)
            'transfer_fee_rate': 0.00002,       # 过户费0.002%
            'min_transfer_fee': 0.0,
            'slippage_rate': 0.001,             # 0.1%滑点
            'is_default': True,
            'is_active': True,
            'description': '标准A股交易费率：买入万3+卖出万3+印花税0.1%+过户费0.002%+滑点0.1%'
        }
    )
    if created:
        print(f"[OK] Created: {standard_equity.config_name}")
    else:
        print(f"[SKIP] Already exists: {standard_equity.config_name}")

    # 2. VIP费率配置（股票）
    vip_equity, created = FeeConfigModel.objects.get_or_create(
        config_name="VIP费率-股票",
        defaults={
            'asset_type': 'equity',
            'commission_rate_buy': 0.0002,      # 万2
            'commission_rate_sell': 0.0002,     # 万2
            'min_commission': 5.0,              # 最低5元
            'stamp_duty_rate': 0.001,           # 0.1%印花税(卖出)
            'transfer_fee_rate': 0.00002,       # 过户费0.002%
            'min_transfer_fee': 0.0,
            'slippage_rate': 0.0005,            # 0.05%滑点
            'is_default': False,
            'is_active': True,
            'description': 'VIP费率：佣金万2+印花税0.1%+过户费0.002%+滑点0.05%'
        }
    )
    if created:
        print(f"[OK] Created: {vip_equity.config_name}")
    else:
        print(f"[SKIP] Already exists: {vip_equity.config_name}")

    # 3. 低佣费率配置（股票）
    low_commission_equity, created = FeeConfigModel.objects.get_or_create(
        config_name="低佣费率-股票",
        defaults={
            'asset_type': 'equity',
            'commission_rate_buy': 0.00015,     # 万1.5
            'commission_rate_sell': 0.00015,    # 万1.5
            'min_commission': 1.0,              # 最低1元
            'stamp_duty_rate': 0.001,           # 0.1%印花税(卖出)
            'transfer_fee_rate': 0.00002,       # 过户费0.002%
            'min_transfer_fee': 0.0,
            'slippage_rate': 0.0005,            # 0.05%滑点
            'is_default': False,
            'is_active': True,
            'description': '超低佣金费率：佣金万1.5+印花税0.1%+过户费0.002%+滑点0.05%'
        }
    )
    if created:
        print(f"[OK] Created: {low_commission_equity.config_name}")
    else:
        print(f"[SKIP] Already exists: {low_commission_equity.config_name}")

    # 4. 基金费率配置（免佣）
    fund_config, created = FeeConfigModel.objects.get_or_create(
        config_name="基金费率-免佣",
        defaults={
            'asset_type': 'fund',
            'commission_rate_buy': 0.0,         # 免佣
            'commission_rate_sell': 0.0,        # 免佣
            'min_commission': 0.0,              # 无最低佣金
            'stamp_duty_rate': 0.0,             # 基金无印花税
            'transfer_fee_rate': 0.0,           # 基金无过户费
            'min_transfer_fee': 0.0,
            'slippage_rate': 0.0005,            # 0.05%滑点
            'is_default': True,
            'is_active': True,
            'description': '基金交易费率：免佣金+免印花税+免过户费，仅0.05%滑点'
        }
    )
    if created:
        print(f"[OK] Created: {fund_config.config_name}")
    else:
        print(f"[SKIP] Already exists: {fund_config.config_name}")

    # 5. 债券费率配置
    bond_config, created = FeeConfigModel.objects.get_or_create(
        config_name="债券费率-低佣",
        defaults={
            'asset_type': 'bond',
            'commission_rate_buy': 0.0001,      # 万1
            'commission_rate_sell': 0.0001,     # 万1
            'min_commission': 1.0,
            'stamp_duty_rate': 0.0,             # 债券无印花税
            'transfer_fee_rate': 0.0,
            'min_transfer_fee': 0.0,
            'slippage_rate': 0.0003,            # 0.03%滑点
            'is_default': True,
            'is_active': True,
            'description': '债券交易费率：佣金万1+免印花税+免过户费+滑点0.03%'
        }
    )
    if created:
        print(f"[OK] Created: {bond_config.config_name}")
    else:
        print(f"[SKIP] Already exists: {bond_config.config_name}")

    # 6. 通用费率配置（备用）
    universal_config, created = FeeConfigModel.objects.get_or_create(
        config_name="通用费率-中佣",
        defaults={
            'asset_type': 'all',
            'commission_rate_buy': 0.00025,     # 万2.5
            'commission_rate_sell': 0.00025,    # 万2.5
            'min_commission': 5.0,
            'stamp_duty_rate': 0.001,           # 默认有印花税
            'transfer_fee_rate': 0.00002,
            'min_transfer_fee': 0.0,
            'slippage_rate': 0.0008,            # 0.08%滑点
            'is_default': False,
            'is_active': True,
            'description': '通用费率配置，适用于各类资产：佣金万2.5+印花税0.1%+过户费0.002%+滑点0.08%'
        }
    )
    if created:
        print(f"[OK] Created: {universal_config.config_name}")
    else:
        print(f"[SKIP] Already exists: {universal_config.config_name}")

    print("\n" + "="*60)
    print("Fee config initialization completed!")
    print(f"Total configs: {FeeConfigModel.objects.count()}")
    print("="*60)

    # 显示所有配置
    print("\nAll fee configurations:")
    for config in FeeConfigModel.objects.all():
        default_mark = "[DEFAULT]" if config.is_default else ""
        active_mark = "[ACTIVE]" if config.is_active else "[INACTIVE]"
        print(f"  {active_mark} {config.config_name} {default_mark}")
        print(f"      Type: {config.get_asset_type_display()}")
        print(f"      Commission: Buy {config.commission_rate_buy*10000:.1f} / Sell {config.commission_rate_sell*10000:.1f}")
        print(f"      Description: {config.description}")
        print()


if __name__ == "__main__":
    print("="*60)
    print("模拟盘费率配置初始化脚本")
    print("="*60)
    print()
    init_fee_configs()
