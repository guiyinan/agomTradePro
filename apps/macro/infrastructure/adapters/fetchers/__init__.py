"""
数据获取器模块。

按指标类别分组的 AKShare 数据获取器。
"""

from .base_fetchers import BaseIndicatorFetcher
from .economic_fetchers import EconomicIndicatorFetcher
from .trade_fetchers import TradeIndicatorFetcher
from .financial_fetchers import FinancialIndicatorFetcher
from .other_fetchers import OtherIndicatorFetcher

__all__ = [
    'BaseIndicatorFetcher',
    'EconomicIndicatorFetcher',
    'TradeIndicatorFetcher',
    'FinancialIndicatorFetcher',
    'OtherIndicatorFetcher',
]
