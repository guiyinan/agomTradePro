"""
Alpha Domain Layer

Alpha 信号抽象层 - 定义股票评分的核心接口和实体。
仅使用 Python 标准库，不依赖 Django 或外部库。
"""

from .entities import (
    AlphaProviderConfig,
    AlphaResult,
    InvalidationCondition,
    StockScore,
)
from .interfaces import AlphaProvider, AlphaProviderStatus

__all__ = [
    "AlphaProvider",
    "AlphaProviderStatus",
    "StockScore",
    "AlphaResult",
    "AlphaProviderConfig",
    "InvalidationCondition",
]
