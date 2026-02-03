"""
数据获取器模块。

按指标类别分组的 AKShare 数据获取器。
"""

from .base_fetchers import BaseIndicatorFetcher
from .economic_fetchers import EconomicIndicatorFetcher
from .trade_fetchers import TradeIndicatorFetcher
from .financial_fetchers import FinancialIndicatorFetcher
from .other_fetchers import OtherIndicatorFetcher
from .high_frequency_fetchers import HighFrequencyIndicatorFetcher
from .weekly_indicators_fetchers import WeeklyIndicatorFetcher
from .pmi_subitems_fetchers import PMISubitemsFetcher

__all__ = [
    'BaseIndicatorFetcher',
    'EconomicIndicatorFetcher',
    'TradeIndicatorFetcher',
    'FinancialIndicatorFetcher',
    'OtherIndicatorFetcher',
    'HighFrequencyIndicatorFetcher',
    'WeeklyIndicatorFetcher',
    'PMISubitemsFetcher',
]
