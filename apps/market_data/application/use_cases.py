"""
Market Data 模块 - Application 层用例

编排数据采集、持久化、情绪分析等业务流程。
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Optional

from apps.market_data.domain.entities import (
    CapitalFlowSnapshot,
    StockNewsItem,
)
from apps.market_data.domain.enums import DataCapability
from apps.market_data.infrastructure.registries.source_registry import SourceRegistry
from apps.market_data.infrastructure.repositories.capital_flow_repository import (
    CapitalFlowRepository,
)
from apps.market_data.infrastructure.repositories.stock_news_repository import (
    StockNewsRepository,
)

logger = logging.getLogger(__name__)

# 新闻数量低于此值时标记 data_sufficient=False
_MIN_NEWS_THRESHOLD = 3


@dataclass(frozen=True)
class SyncCapitalFlowRequest:
    """同步资金流向请求"""

    stock_code: str
    period: str = "5d"


@dataclass(frozen=True)
class SyncCapitalFlowResponse:
    """同步资金流向响应"""

    stock_code: str
    synced_count: int
    success: bool
    error_message: str = ""


class SyncCapitalFlowUseCase:
    """同步个股资金流向用例

    从 market_data provider 拉取资金流向并持久化。
    """

    def __init__(
        self,
        registry: SourceRegistry,
        repository: CapitalFlowRepository | None = None,
    ) -> None:
        self._registry = registry
        self._repository = repository or CapitalFlowRepository()

    def execute(self, request: SyncCapitalFlowRequest) -> SyncCapitalFlowResponse:
        """执行同步（自动 failover 到下一个 provider）"""
        flows = self._registry.call_with_failover(
            DataCapability.CAPITAL_FLOW,
            lambda p: p.get_capital_flows(
                request.stock_code, period=request.period
            ),
        )
        if flows is None:
            return SyncCapitalFlowResponse(
                stock_code=request.stock_code,
                synced_count=0,
                success=False,
                error_message="所有资金流向 provider 均不可用",
            )

        saved = self._repository.save_batch(flows)
        logger.info(
            "资金流向同步: %s, 获取 %d 条, 保存 %d 条",
            request.stock_code,
            len(flows),
            saved,
        )
        return SyncCapitalFlowResponse(
            stock_code=request.stock_code,
            synced_count=saved,
            success=True,
        )


@dataclass(frozen=True)
class IngestStockNewsRequest:
    """采集股票新闻请求"""

    stock_code: str
    limit: int = 20


@dataclass(frozen=True)
class IngestStockNewsResponse:
    """采集股票新闻响应"""

    stock_code: str
    fetched_count: int
    new_count: int
    data_sufficient: bool
    success: bool
    error_message: str = ""


class IngestStockNewsUseCase:
    """采集个股新闻用例

    从 market_data provider 拉取新闻，去重后持久化。
    """

    def __init__(
        self,
        registry: SourceRegistry,
        repository: StockNewsRepository | None = None,
    ) -> None:
        self._registry = registry
        self._repository = repository or StockNewsRepository()

    def execute(self, request: IngestStockNewsRequest) -> IngestStockNewsResponse:
        """执行采集（自动 failover 到下一个 provider）"""
        items = self._registry.call_with_failover(
            DataCapability.STOCK_NEWS,
            lambda p: p.get_stock_news(
                request.stock_code, limit=request.limit
            ),
        )
        if items is None:
            return IngestStockNewsResponse(
                stock_code=request.stock_code,
                fetched_count=0,
                new_count=0,
                data_sufficient=False,
                success=False,
                error_message="所有股票新闻 provider 均不可用",
            )

        new_count = self._repository.save_batch(items)
        total_recent = self._repository.count_recent(request.stock_code, days=3)

        logger.info(
            "新闻采集: %s, 获取 %d 条, 新增 %d 条, 近3日共 %d 条",
            request.stock_code,
            len(items),
            new_count,
            total_recent,
        )

        return IngestStockNewsResponse(
            stock_code=request.stock_code,
            fetched_count=len(items),
            new_count=new_count,
            data_sufficient=total_recent >= _MIN_NEWS_THRESHOLD,
            success=True,
        )
