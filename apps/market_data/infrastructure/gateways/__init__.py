"""
Market Data 模块 - Domain 层协议

定义统一的市场数据 Provider 协议。
业务模块只依赖这些协议，不依赖任何具体数据源实现。
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from apps.market_data.domain.entities import (
    CapitalFlowSnapshot,
    QuoteSnapshot,
    StockNewsItem,
    TechnicalSnapshot,
)
from apps.market_data.domain.enums import DataCapability


class MarketDataProviderProtocol(ABC):
    """统一市场数据 Provider 协议

    每个 provider 通过 supports() 声明自己支持的能力，
    SourceRegistry 按能力分发请求。
    """

    @abstractmethod
    def provider_name(self) -> str:
        """返回 provider 唯一标识名"""
        ...

    @abstractmethod
    def supports(self, capability: DataCapability) -> bool:
        """判断是否支持某种数据能力"""
        ...

    def get_quote_snapshots(
        self, stock_codes: list[str]
    ) -> list[QuoteSnapshot]:
        """批量获取实时行情快照

        默认返回空列表，子类按需覆盖。
        """
        return []

    def get_capital_flows(
        self, stock_code: str, period: str = "5d"
    ) -> list[CapitalFlowSnapshot]:
        """获取个股资金流向

        Args:
            stock_code: 股票代码（Tushare 格式，如 000001.SZ）
            period: 时间范围，如 '1d', '5d', '10d'
        """
        return []

    def get_stock_news(
        self, stock_code: str, limit: int = 20
    ) -> list[StockNewsItem]:
        """获取个股新闻"""
        return []

    def get_technical_snapshot(
        self, stock_code: str
    ) -> TechnicalSnapshot | None:
        """获取个股技术指标快照"""
        return None
