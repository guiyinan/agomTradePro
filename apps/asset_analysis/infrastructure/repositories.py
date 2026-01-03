"""
资产分析模块 - Infrastructure 层仓储实现

本模块包含仓储的具体实现，使用 Django ORM 进行数据持久化。
仓储实现了 Domain 层定义的 Protocol 接口。
"""

from typing import Optional, List

from apps.asset_analysis.domain.interfaces import WeightConfigRepositoryProtocol, AssetRepositoryProtocol
from apps.asset_analysis.domain.value_objects import WeightConfig
from apps.asset_analysis.infrastructure.models import WeightConfigModel


class DjangoWeightConfigRepository(WeightConfigRepositoryProtocol):
    """
    权重配置仓储实现

    使用 Django ORM 存储和查询权重配置。
    """

    def get_active_weights(
        self,
        asset_type: Optional[str] = None,
        market_condition: Optional[str] = None
    ) -> WeightConfig:
        """
        获取当前生效的权重配置

        优先级：
        1. 匹配 asset_type + market_condition 的配置
        2. 匹配 asset_type 的配置
        3. 通用配置（asset_type 为空）
        4. 默认权重（如果数据库无配置）
        """
        query = WeightConfigModel.objects.filter(is_active=True)

        # 1. 优先匹配特定条件
        if asset_type and market_condition:
            specific = query.filter(
                asset_type=asset_type,
                market_condition=market_condition
            ).order_by("-priority").first()
            if specific:
                return self._to_entity(specific)

        # 2. 其次匹配资产类型
        if asset_type:
            type_specific = query.filter(
                asset_type=asset_type
            ).order_by("-priority").first()
            if type_specific:
                return self._to_entity(type_specific)

        # 3. 最后使用通用配置
        general = query.filter(
            asset_type__isnull=True
        ).order_by("-priority").first()
        if general:
            return self._to_entity(general)

        # 4. 降级到默认值
        return WeightConfig()

    def list_all_configs(self) -> List[dict]:
        """
        列出所有权重配置

        Returns:
            配置列表
        """
        configs = WeightConfigModel.objects.all().order_by("-priority", "-created_at")

        return [
            {
                "name": c.name,
                "description": c.description,
                "regime_weight": c.regime_weight,
                "policy_weight": c.policy_weight,
                "sentiment_weight": c.sentiment_weight,
                "signal_weight": c.signal_weight,
                "asset_type": c.asset_type,
                "market_condition": c.market_condition,
                "is_active": c.is_active,
                "priority": c.priority,
            }
            for c in configs
        ]

    def save_config(
        self,
        name: str,
        regime_weight: float,
        policy_weight: float,
        sentiment_weight: float,
        signal_weight: float,
        asset_type: Optional[str] = None,
        market_condition: Optional[str] = None,
        is_active: bool = True,
        priority: int = 0
    ) -> None:
        """
        保存权重配置

        如果配置已存在则更新，否则创建新配置。
        """
        config, created = WeightConfigModel.objects.get_or_create(
            name=name,
            defaults={
                "description": f"{name} 权重配置",
                "regime_weight": regime_weight,
                "policy_weight": policy_weight,
                "sentiment_weight": sentiment_weight,
                "signal_weight": signal_weight,
                "asset_type": asset_type,
                "market_condition": market_condition,
                "is_active": is_active,
                "priority": priority,
            }
        )

        if not created:
            # 更新现有配置
            config.regime_weight = regime_weight
            config.policy_weight = policy_weight
            config.sentiment_weight = sentiment_weight
            config.signal_weight = signal_weight
            config.asset_type = asset_type
            config.market_condition = market_condition
            config.is_active = is_active
            config.priority = priority
            config.save()

    @staticmethod
    def _to_entity(model: WeightConfigModel) -> WeightConfig:
        """
        ORM 模型转换为 Domain 实体

        Args:
            model: WeightConfigModel 实例

        Returns:
            WeightConfig 值对象
        """
        return WeightConfig(
            regime_weight=model.regime_weight,
            policy_weight=model.policy_weight,
            sentiment_weight=model.sentiment_weight,
            signal_weight=model.signal_weight,
        )


class DjangoAssetRepository(AssetRepositoryProtocol):
    """
    资产仓储实现（通用）

    这是一个基础实现，具体的资产类型（Fund、Equity）应该
    继承此类或实现自己的仓储。
    """

    def get_assets_by_filter(
        self,
        asset_type: str,
        filters: dict,
        max_count: int = 100
    ) -> List:
        """
        根据过滤条件获取资产列表

        这是一个通用实现，实际使用时需要根据具体的资产类型
        （Fund、Equity 等）进行适配。
        """
        # 这里需要根据具体的资产类型进行查询
        # 例如：对于基金，查询 FundModel
        # 对于股票，查询 EquityModel

        # 作为一个占位实现，返回空列表
        # 实际的 Fund/Equity 模块应该实现自己的仓储
        return []

    def get_asset_by_code(self, asset_type: str, asset_code: str) -> Optional:
        """
        根据代码获取资产

        这是一个通用实现，实际使用时需要根据具体的资产类型
        （Fund、Equity 等）进行适配。
        """
        return None
