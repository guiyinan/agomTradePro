"""
资产分析模块 - Domain 层接口定义

本模块定义 Repository Protocol 接口，遵循依赖倒置原则。
Infrastructure 层实现这些接口，Application 层通过接口调用。
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from apps.asset_analysis.domain.value_objects import WeightConfig


class WeightConfigRepositoryProtocol(ABC):
    """
    权重配置仓储接口

    定义权重配置的读取操作。
    """

    @abstractmethod
    def get_active_weights(
        self,
        asset_type: str | None = None,
        market_condition: str | None = None
    ) -> WeightConfig:
        """
        获取当前生效的权重配置

        Args:
            asset_type: 资产类型（可选）
            market_condition: 市场状态（可选）

        Returns:
            WeightConfig 值对象

        优先级：
        1. 匹配 asset_type + market_condition 的配置
        2. 匹配 asset_type 的配置
        3. 通用配置（asset_type 为空）
        4. 默认权重（如果数据库无配置）
        """
        pass

    @abstractmethod
    def list_all_configs(self) -> list[dict]:
        """
        列出所有权重配置

        Returns:
            配置列表
        """
        pass

    @abstractmethod
    def save_config(
        self,
        name: str,
        regime_weight: float,
        policy_weight: float,
        sentiment_weight: float,
        signal_weight: float,
        asset_type: str | None = None,
        market_condition: str | None = None,
        is_active: bool = True,
        priority: int = 0
    ) -> None:
        """
        保存权重配置

        Args:
            name: 配置名称
            regime_weight: Regime 权重
            policy_weight: Policy 权重
            sentiment_weight: Sentiment 权重
            signal_weight: Signal 权重
            asset_type: 资产类型（可选）
            market_condition: 市场状态（可选）
            is_active: 是否激活
            priority: 优先级
        """
        pass


class AssetRepositoryProtocol(ABC):
    """
    资产仓储接口（通用）

    定义资产的查询操作，支持多种资产类型。
    """

    @abstractmethod
    def get_assets_by_filter(
        self,
        asset_type: str,
        filters: dict,
        max_count: int = 100
    ) -> list:
        """
        根据过滤条件获取资产列表

        Args:
            asset_type: 资产类型（fund/equity/bond等）
            filters: 过滤条件字典
            max_count: 最大返回数量

        Returns:
            资产列表
        """
        pass

    @abstractmethod
    def get_asset_by_code(self, asset_type: str, asset_code: str) -> Optional:
        """
        根据代码获取资产

        Args:
            asset_type: 资产类型
            asset_code: 资产代码

        Returns:
            资产对象，不存在则返回 None
        """
        pass
