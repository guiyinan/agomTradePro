"""
Base Policy Adapter - Protocol Definition

定义政策数据适配器的接口协议。
"""

from abc import ABC, abstractmethod
from datetime import date

from ...domain.entities import PolicyEvent


class PolicyAdapterProtocol(ABC):
    """
    政策数据适配器协议

    定义从外部数据源获取政策事件的接口
    """

    @abstractmethod
    def fetch_policy_events(
        self,
        start_date: date | None = None,
        end_date: date | None = None
    ) -> list[PolicyEvent]:
        """
        获取政策事件列表

        Args:
            start_date: 起始日期（None 表示不限）
            end_date: 结束日期（None 表示不限）

        Returns:
            List[PolicyEvent]: 政策事件列表
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        检查适配器是否可用

        Returns:
            bool: 是否可用
        """
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """
        获取数据源名称

        Returns:
            str: 数据源名称
        """
        pass


class PolicyAdapterError(Exception):
    """政策适配器异常基类"""
    pass


class PolicySourceUnavailableError(PolicyAdapterError):
    """数据源不可用异常"""
    pass


class PolicyParsingError(PolicyAdapterError):
    """数据解析异常"""
    pass
