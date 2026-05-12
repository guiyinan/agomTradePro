"""
个股分析模块 Domain 层端口定义

定义外部依赖的协议接口，遵循依赖倒置原则。
Domain 层定义接口，Infrastructure 层实现接口。
"""

from abc import abstractmethod
from datetime import date
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class RegimeDataPort(Protocol):
    """
    Regime 数据端口协议

    定义获取 Regime 历史数据的接口，由 regime 模块的仓储实现。
    """

    @abstractmethod
    def get_snapshots_in_range(
        self,
        start_date: date,
        end_date: date
    ) -> list:
        """
        获取日期范围内的快照列表

        Args:
            start_date: 起始日期（包含）
            end_date: 结束日期（包含）

        Returns:
            List[RegimeSnapshot]: 快照列表，按时间升序排列
        """
        ...

    @abstractmethod
    def get_snapshot_by_date(
        self,
        observed_at: date
    ) -> Optional:
        """
        按日期获取 Regime 快照

        Args:
            observed_at: 观测日期

        Returns:
            Optional[RegimeSnapshot]: 快照实体，不存在则返回 None
        """
        ...


@runtime_checkable
class MarketDataPort(Protocol):
    """
    市场数据端口协议

    定义获取市场指数数据的接口，由 macro 或 realtime 模块实现。
    """

    @abstractmethod
    def get_index_daily_returns(
        self,
        index_code: str,
        start_date: date,
        end_date: date
    ) -> dict[date, float]:
        """
        获取指数日收益率

        Args:
            index_code: 指数代码（如 000300.SH 表示沪深 300）
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            {日期: 收益率}，收益率以小数表示（如 0.01 表示 1%）
        """
        ...


@runtime_checkable
class StockPoolPort(Protocol):
    """
    股票池端口协议

    定义股票池操作的接口。
    """

    @abstractmethod
    def get_current_pool(self) -> list[str]:
        """
        获取当前股票池

        Returns:
            股票代码列表
        """
        ...

    @abstractmethod
    def save_pool(
        self,
        stock_codes: list[str],
        regime: str,
        as_of_date: date
    ) -> None:
        """
        保存股票池

        Args:
            stock_codes: 股票代码列表
            regime: 当前的 Regime
            as_of_date: 截止日期
        """
        ...

    @abstractmethod
    def get_latest_pool_info(self) -> dict | None:
        """
        获取最新的股票池信息

        Returns:
            包含股票池元数据的字典，或 None
        """
        ...
