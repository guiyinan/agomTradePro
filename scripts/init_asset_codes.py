"""
初始化资产代码配置

Usage:
    python manage.py shell < scripts/init_asset_codes.py
    python scripts/init_asset_codes.py
"""

import os
import sys

import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.account.domain.entities import AssetClassType, CrossBorderFlag, InvestmentStyle, Region
from apps.asset_analysis.infrastructure.models import AssetConfigModel

# 常用资产代码配置
DEFAULT_ASSETS = [
    # A股主要指数
    {
        'asset_class': '000001.SH',
        'display_name': '上证指数',
        'ticker_symbol': '000001.SH',
        'data_source': 'tushare',
        'category': 'equity',
        'description': '上证综合指数'
    },
    {
        'asset_class': '399001.SZ',
        'display_name': '深证成指',
        'ticker_symbol': '399001.SZ',
        'data_source': 'tushare',
        'category': 'equity',
        'description': '深圳成份指数'
    },
    {
        'asset_class': '000300.SH',
        'display_name': '沪深300',
        'ticker_symbol': '000300.SH',
        'data_source': 'tushare',
        'category': 'equity',
        'description': '沪深300指数'
    },
    {
        'asset_class': '000905.SH',
        'display_name': '中证500',
        'ticker_symbol': '000905.SH',
        'data_source': 'tushare',
        'category': 'equity',
        'description': '中证500指数'
    },
    {
        'asset_class': '000852.SH',
        'display_name': '中证1000',
        'ticker_symbol': '000852.SH',
        'data_source': 'tushare',
        'category': 'equity',
        'description': '中证1000指数'
    },
    # 行业指数
    {
        'asset_class': '000016.SH',
        'display_name': '上证50',
        'ticker_symbol': '000016.SH',
        'data_source': 'tushare',
        'category': 'equity',
        'description': '上证50指数'
    },
    {
        'asset_class': '399006.SZ',
        'display_name': '创业板指',
        'ticker_symbol': '399006.SZ',
        'data_source': 'tushare',
        'category': 'equity',
        'description': '创业板指数'
    },
    {
        'asset_class': '399303.SZ',
        'display_name': '国证2000',
        'ticker_symbol': '399303.SZ',
        'data_source': 'tushare',
        'category': 'equity',
        'description': '国证2000指数'
    },
    # 商品
    {
        'asset_class': 'AU.SHF',
        'display_name': '黄金期货',
        'ticker_symbol': 'AU.SHF',
        'data_source': 'tushare',
        'category': 'commodity',
        'description': '上海黄金交易所黄金期货'
    },
    {
        'asset_class': 'AG.SHF',
        'display_name': '白银期货',
        'ticker_symbol': 'AG.SHF',
        'data_source': 'tushare',
        'category': 'commodity',
        'description': '上海期货交易所白银期货'
    },
    # 债券
    {
        'asset_class': 'TB.SHF',
        'display_name': '5年期国债',
        'ticker_symbol': 'TB.SHF',
        'data_source': 'tushare',
        'category': 'bond',
        'description': '5年期国债期货'
    },
]


def init_asset_codes():
    """初始化资产代码配置"""
    print("开始初始化资产代码配置...")

    created_count = 0
    updated_count = 0
    skipped_count = 0

    for asset_data in DEFAULT_ASSETS:
        asset_class = asset_data['asset_class']

        # 检查是否已存在
        try:
            existing = AssetConfigModel.objects.get(asset_class=asset_class)
            print(f"  [更新] {asset_class} - {asset_data['display_name']}")
            # 更新字段
            for key, value in asset_data.items():
                setattr(existing, key, value)
            existing.save()
            updated_count += 1
        except AssetConfigModel.DoesNotExist:
            print(f"  [创建] {asset_class} - {asset_data['display_name']}")
            AssetConfigModel.objects.create(**asset_data)
            created_count += 1
        except Exception as e:
            print(f"  [跳过] {asset_class} - {e}")
            skipped_count += 1

    print("\n初始化完成:")
    print(f"  新建: {created_count}")
    print(f"  更新: {updated_count}")
    print(f"  跳过: {skipped_count}")
    print(f"  总计: {len(DEFAULT_ASSETS)}")


if __name__ == '__main__':
    init_asset_codes()
