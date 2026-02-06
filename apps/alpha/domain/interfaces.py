"""
Alpha Provider Protocol Interface

定义 Alpha 提供者的抽象接口，实现 Provider 模式。
支持多个 Alpha 信号源，并自动降级。

仅使用 Python 标准库。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Dict, List, Optional


class AlphaProviderStatus(Enum):
    """
    Alpha 提供者状态枚举

    定义 Provider 的健康状态，用于降级决策。
    """

    AVAILABLE = "available"
    """可用：Provider 正常工作，数据新鲜"""

    DEGRADED = "degraded"
    """降级：Provider 可用但数据过期或质量下降"""

    UNAVAILABLE = "unavailable"
    """不可用：Provider 故障或无法访问"""


class AlphaProvider(ABC):
    """
    Alpha 提供者抽象接口

    定义 Alpha 信号提供者的标准接口，支持多种信号源：
    - Qlib（机器学习模型）
    - Cache（历史缓存）
    - Simple（简单因子）
    - ETF（ETF 成分股）

    所有 Provider 必须实现此接口，并通过 AlphaProviderRegistry 注册。
    注册中心按 priority 排序，实现自动降级链路。

    Attributes:
        name: Provider 名称（唯一标识）
        priority: 优先级（数字越小优先级越高）
        max_staleness_days: 最大可接受的数据陈旧天数
        max_latency_ms: 最大可接受的延迟（毫秒）

    Example:
        >>> provider = QlibAlphaProvider()
        >>> print(f"Provider: {provider.name}, Priority: {provider.priority}")
        >>> status = provider.health_check()
        >>> if status == AlphaProviderStatus.AVAILABLE:
        ...     result = provider.get_stock_scores("csi300", date.today(), 30)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Provider 名称

        Returns:
            唯一的 Provider 标识符
        """
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        """
        Provider 优先级

        数字越小，优先级越高。
        建议优先级范围：
        - Qlib: 1-10
        - Cache: 10-100
        - Simple: 100-1000
        - ETF: 1000+

        Returns:
            优先级数值
        """
        pass

    @property
    def max_staleness_days(self) -> int:
        """
        最大可接受的数据陈旧天数

        超过此天数的数据将被视为过期，触发降级。

        Returns:
            最大陈旧天数（默认 2 天）
        """
        return 2

    @property
    def max_latency_ms(self) -> int:
        """
        最大可接受的延迟（毫秒）

        超过此延迟的请求将被视为 DEGRADED。

        Returns:
            最大延迟毫秒数（默认 1500ms）
        """
        return 1500

    @abstractmethod
    def health_check(self) -> AlphaProviderStatus:
        """
        健康检查

        检查 Provider 是否可用，包括：
        - 数据源连接
        - 必需的资源（模型、缓存等）
        - 数据新鲜度

        Returns:
            Provider 状态
        """
        pass

    @abstractmethod
    def get_stock_scores(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30
    ) -> "AlphaResult":
        """
        获取股票评分

        根据指定的股票池和日期，返回股票评分列表。

        Args:
            universe_id: 股票池标识（如 "csi300", "csi500"）
            intended_trade_date: 期望的交易日期
            top_n: 返回前 N 只股票（默认 30）

        Returns:
            AlphaResult 包含评分列表和元数据

        Raises:
            Exception: 实现时应捕获异常并返回失败的 AlphaResult
        """
        pass

    @abstractmethod
    def get_factor_exposure(
        self,
        stock_code: str,
        trade_date: date
    ) -> Dict[str, float]:
        """
        获取因子暴露

        获取指定股票在指定日期的因子暴露度。

        Args:
            stock_code: 股票代码
            trade_date: 交易日期

        Returns:
            因子名称到暴露度的映射

        Example:
            >>> provider.get_factor_exposure("000001.SH", date.today())
            {"momentum": 0.75, "value": 0.5, "quality": 0.8}
        """
        pass

    def supports(self, universe_id: str) -> bool:
        """
        检查是否支持指定的股票池

        默认实现支持所有股票池。子类可覆盖以限制支持范围。

        Args:
            universe_id: 股票池标识

        Returns:
            是否支持
        """
        return True


class AlphaProviderRegistry(ABC):
    """
    Alpha Provider 注册中心抽象接口

    管理 Provider 的注册、获取和降级逻辑。
    """

    @abstractmethod
    def register(self, provider: AlphaProvider) -> None:
        """
        注册 Provider

        Args:
            provider: 要注册的 Provider
        """
        pass

    @abstractmethod
    def get_provider(self, name: str) -> Optional[AlphaProvider]:
        """
        获取指定名称的 Provider

        Args:
            name: Provider 名称

        Returns:
            Provider 实例，如果不存在则返回 None
        """
        pass

    @abstractmethod
    def get_all_providers(self) -> List[AlphaProvider]:
        """
        获取所有已注册的 Provider

        Returns:
            Provider 列表（按优先级排序）
        """
        pass

    @abstractmethod
    def get_active_providers(self) -> List[AlphaProvider]:
        """
        获取所有可用的 Provider

        Returns:
            可用 Provider 列表（按优先级排序）
        """
        pass
