"""
初始化宏观指标配置

Usage:
    python manage.py shell < scripts/init_indicators.py
    python scripts/init_indicators.py
"""

import os
import sys

import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.macro.infrastructure.models import IndicatorConfigModel

# 常用宏观指标配置
DEFAULT_INDICATORS = [
    # 增长指标
    {
        'code': 'CN_PMI_MANUFACTURING',
        'name': '中国制造业PMI',
        'name_en': 'China Manufacturing PMI',
        'category': 'growth',
        'unit': '指数',
        'data_source': 'akshare',
        'fetch_frequency': 'M',
        'publication_lag_days': 35,
        'threshold_bullish': 50.5,
        'threshold_bearish': 49.5,
        'description': '中国制造业采购经理指数，反映制造业扩张情况',
        'is_active': True
    },
    {
        'code': 'CN_PMI_NONMANUFACTURING',
        'name': '中国非制造业PMI',
        'name_en': 'China Non-Manufacturing PMI',
        'category': 'growth',
        'unit': '指数',
        'data_source': 'akshare',
        'fetch_frequency': 'M',
        'publication_lag_days': 35,
        'threshold_bullish': 52.0,
        'threshold_bearish': 50.0,
        'description': '中国非制造业商务活动指数',
        'is_active': True
    },
    {
        'code': 'CN_GDP',
        'name': '中国GDP',
        'name_en': 'China GDP',
        'category': 'growth',
        'unit': '%',
        'data_source': 'akshare',
        'fetch_frequency': 'Q',
        'publication_lag_days': 60,
        'threshold_bullish': 6.5,
        'threshold_bearish': 5.5,
        'description': '中国国内生产总值同比增长率',
        'is_active': True
    },
    {
        'code': 'CN_INDUSTRIAL_PRODUCTION',
        'name': '工业增加值',
        'name_en': 'Industrial Production YOY',
        'category': 'growth',
        'unit': '%',
        'data_source': 'akshare',
        'fetch_frequency': 'M',
        'publication_lag_days': 35,
        'threshold_bullish': 7.0,
        'threshold_bearish': 5.0,
        'description': '规模以上工业增加值同比增长率',
        'is_active': True
    },
    # 通胀指标
    {
        'code': 'CN_CPI',
        'name': 'CPI同比',
        'name_en': 'China CPI YOY',
        'category': 'inflation',
        'unit': '%',
        'data_source': 'akshare',
        'fetch_frequency': 'M',
        'publication_lag_days': 35,
        'threshold_bullish': 2.5,
        'threshold_bearish': 1.0,
        'description': '居民消费价格指数同比',
        'is_active': True
    },
    {
        'code': 'CN_PPI',
        'name': 'PPI同比',
        'name_en': 'China PPI YOY',
        'category': 'inflation',
        'unit': '%',
        'data_source': 'akshare',
        'fetch_frequency': 'M',
        'publication_lag_days': 35,
        'threshold_bullish': 3.0,
        'threshold_bearish': -2.0,
        'description': '工业生产者出厂价格指数同比',
        'is_active': True
    },
    # 货币指标
    {
        'code': 'CN_M2',
        'name': 'M2同比',
        'name_en': 'China M2 YOY',
        'category': 'monetary',
        'unit': '%',
        'data_source': 'akshare',
        'fetch_frequency': 'M',
        'publication_lag_days': 35,
        'threshold_bullish': 10.0,
        'threshold_bearish': 8.0,
        'description': '广义货币供应量同比增长率',
        'is_active': True
    },
    {
        'code': 'CN_M1',
        'name': 'M1同比',
        'name_en': 'China M1 YOY',
        'category': 'monetary',
        'unit': '%',
        'data_source': 'akshare',
        'fetch_frequency': 'M',
        'publication_lag_days': 35,
        'threshold_bullish': 12.0,
        'threshold_bearish': 5.0,
        'description': '狭义货币供应量同比增长率',
        'is_active': True
    },
    # 利率指标
    {
        'code': 'SHIBOR_OVERNIGHT',
        'name': 'SHIBOR隔夜',
        'name_en': 'SHIBOR Overnight',
        'category': 'interest',
        'unit': '%',
        'data_source': 'tushare',
        'fetch_frequency': 'D',
        'publication_lag_days': 1,
        'threshold_bullish': 3.0,
        'threshold_bearish': 1.5,
        'description': '上海银行间同业拆放利率隔夜',
        'is_active': True
    },
    {
        'code': 'SHIBOR_1W',
        'name': 'SHIBOR 1周',
        'name_en': 'SHIBOR 1 Week',
        'category': 'interest',
        'unit': '%',
        'data_source': 'tushare',
        'fetch_frequency': 'D',
        'publication_lag_days': 1,
        'threshold_bullish': 3.5,
        'threshold_bearish': 2.0,
        'description': '上海银行间同业拆放利率1周',
        'is_active': True
    },
    {
        'code': 'LOAN_PRIME_1Y',
        'name': 'LPR 1年期',
        'name_en': 'Loan Prime Rate 1Y',
        'category': 'interest',
        'unit': '%',
        'data_source': 'akshare',
        'fetch_frequency': 'M',
        'publication_lag_days': 35,
        'threshold_bullish': 4.5,
        'threshold_bearish': 3.5,
        'description': '贷款市场报价利率1年期',
        'is_active': True
    },
]


def init_indicators():
    """初始化宏观指标配置"""
    print("开始初始化宏观指标配置...")

    created_count = 0
    updated_count = 0
    skipped_count = 0

    for indicator_data in DEFAULT_INDICATORS:
        code = indicator_data['code']

        # 检查是否已存在
        try:
            existing = IndicatorConfigModel.objects.get(code=code)
            print(f"  [更新] {code} - {indicator_data['name']}")
            # 更新字段
            for key, value in indicator_data.items():
                setattr(existing, key, value)
            existing.save()
            updated_count += 1
        except IndicatorConfigModel.DoesNotExist:
            print(f"  [创建] {code} - {indicator_data['name']}")
            IndicatorConfigModel.objects.create(**indicator_data)
            created_count += 1
        except Exception as e:
            print(f"  [跳过] {code} - {e}")
            skipped_count += 1

    print("\n初始化完成:")
    print(f"  新建: {created_count}")
    print(f"  更新: {updated_count}")
    print(f"  跳过: {skipped_count}")
    print(f"  总计: {len(DEFAULT_INDICATORS)}")


if __name__ == '__main__':
    init_indicators()
