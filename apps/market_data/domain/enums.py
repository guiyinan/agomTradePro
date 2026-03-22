"""
Market Data 模块 - Domain 层枚举

定义数据能力类型，用于能力导向的 provider 注册与分发。
"""

from enum import Enum


class DataCapability(Enum):
    """数据能力枚举

    按能力注册 provider，不按站点写死。
    业务模块通过能力类型获取 provider，不感知具体数据源。
    """

    REALTIME_QUOTE = "realtime_quote"
    CAPITAL_FLOW = "capital_flow"
    STOCK_NEWS = "stock_news"
    TECHNICAL_FACTORS = "technical_factors"
    HISTORICAL_PRICE = "historical_price"


class ProviderHealth(Enum):
    """Provider 健康状态"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CIRCUIT_OPEN = "circuit_open"
    UNKNOWN = "unknown"
