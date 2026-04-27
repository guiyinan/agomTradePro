"""
资产分析模块 - Infrastructure 层仓储实现

本模块包含仓储的具体实现，使用 Django ORM 进行数据持久化。
仓储实现了 Domain 层定义的 Protocol 接口。
"""

from datetime import date
from typing import Dict, List, Optional, Union

from apps.asset_analysis.domain.entities import AssetScore, AssetSize, AssetStyle, AssetType
from apps.asset_analysis.domain.interfaces import (
    AssetRepositoryProtocol,
    WeightConfigRepositoryProtocol,
)
from apps.asset_analysis.domain.pool import PoolType
from apps.asset_analysis.domain.value_objects import WeightConfig
from apps.asset_analysis.infrastructure.models import (
    AssetAnalysisAlert,
    AssetPoolEntry,
    AssetScoringLog,
    WeightConfigModel,
)
from shared.infrastructure.asset_analysis_registry import (
    get_asset_analysis_market_registry,
)


class AssetRepositoryFactory:
    """
    资产仓储工厂

    根据资产类型返回对应的仓储实例。
    """

    _repositories = {
        "fund": None,  # 延迟加载，避免循环导入
        "equity": None,
        "bond": None,
        "commodity": None,
        "index": None,
        "sector": None,
    }

    @classmethod
    def get_repository(cls, asset_type: str) -> AssetRepositoryProtocol:
        """
        获取指定资产类型的仓储

        Args:
            asset_type: 资产类型（fund/equity/bond等）

        Returns:
            对应的资产仓储实例

        Raises:
            ValueError: 不支持的资产类型
        """
        if asset_type not in cls._repositories:
            raise ValueError(f"不支持的资产类型: {asset_type}")

        # 延迟加载仓储实例
        if cls._repositories[asset_type] is None:
            if asset_type in ("fund", "equity"):
                cls._repositories[asset_type] = (
                    get_asset_analysis_market_registry().get_asset_repository(asset_type)
                )
            elif asset_type in ("bond", "commodity", "index", "sector"):
                # 对于尚未实现的资产类型，使用空仓储
                cls._repositories[asset_type] = EmptyAssetRepository()
            else:
                raise ValueError(f"不支持的资产类型: {asset_type}")

        return cls._repositories[asset_type]


class EmptyAssetRepository(AssetRepositoryProtocol):
    """
    空资产仓储（用于未实现的资产类型）
    """

    def get_assets_by_filter(self, asset_type: str, filters: dict, max_count: int = 100) -> list:
        """返回空列表"""
        return []

    def get_asset_by_code(self, asset_type: str, asset_code: str) -> Optional:
        """返回 None"""
        return None


class DjangoWeightConfigRepository(WeightConfigRepositoryProtocol):
    """
    权重配置仓储实现

    使用 Django ORM 存储和查询权重配置。
    """

    def get_active_weights(
        self, asset_type: str | None = None, market_condition: str | None = None
    ) -> WeightConfig:
        """
        获取当前生效的权重配置

        优先级：
        1. 匹配 asset_type + market_condition 的配置
        2. 匹配 asset_type 的配置
        3. 通用配置（asset_type 为空）
        4. 默认权重（如果数据库无配置）
        """
        query = WeightConfigModel._default_manager.filter(is_active=True)

        # 1. 优先匹配特定条件
        if asset_type and market_condition:
            specific = (
                query.filter(asset_type=asset_type, market_condition=market_condition)
                .order_by("-priority")
                .first()
            )
            if specific:
                return self._to_entity(specific)

        # 2. 其次匹配资产类型
        if asset_type:
            type_specific = query.filter(asset_type=asset_type).order_by("-priority").first()
            if type_specific:
                return self._to_entity(type_specific)

        # 3. 最后使用通用配置
        general = query.filter(asset_type__isnull=True).order_by("-priority").first()
        if general:
            return self._to_entity(general)

        # 4. 降级到默认值
        return WeightConfig()

    def list_all_configs(self) -> list[dict]:
        """
        列出所有权重配置

        Returns:
            配置列表
        """
        configs = WeightConfigModel._default_manager.all().order_by("-priority", "-created_at")

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
        asset_type: str | None = None,
        market_condition: str | None = None,
        is_active: bool = True,
        priority: int = 0,
    ) -> None:
        """
        保存权重配置

        如果配置已存在则更新，否则创建新配置。
        """
        config, created = WeightConfigModel._default_manager.get_or_create(
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
            },
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

    这是一个适配器仓储，根据资产类型委托给具体的资产仓储。
    """

    def get_assets_by_filter(self, asset_type: str, filters: dict, max_count: int = 100) -> list:
        """
        根据过滤条件获取资产列表

        委托给具体资产类型的仓储实现。
        """
        repo = AssetRepositoryFactory.get_repository(asset_type)
        return repo.get_assets_by_filter(asset_type, filters, max_count)

    def get_asset_by_code(self, asset_type: str, asset_code: str) -> Optional:
        """
        根据代码获取资产

        委托给具体资产类型的仓储实现。
        """
        repo = AssetRepositoryFactory.get_repository(asset_type)
        return repo.get_asset_by_code(asset_type, asset_code)


class DjangoAssetPoolQueryRepository:
    """资产池只读查询仓储。"""

    def list_investable_assets(
        self,
        asset_type: str,
        min_score: float,
        limit: int,
    ) -> list[dict]:
        pool_entries = AssetPoolEntry._default_manager.filter(
            pool_type=PoolType.INVESTABLE.value,
            asset_category=asset_type,
            is_active=True,
            total_score__gte=min_score,
        ).order_by("-total_score")[:limit]

        candidates = []
        for entry in pool_entries:
            candidates.append(
                {
                    "asset_code": entry.asset_code,
                    "asset_name": entry.asset_name,
                    "asset_type": asset_type,
                    "score": entry.total_score,
                    "regime_score": entry.regime_score,
                    "policy_score": entry.policy_score,
                    "sentiment_score": entry.sentiment_score,
                    "signal_score": entry.signal_score,
                    "entry_date": entry.entry_date,
                    "entry_reason": entry.entry_reason,
                    "risk_level": entry.risk_level,
                }
            )
        return candidates

    def get_latest_pool_type(self, asset_code: str) -> str | None:
        entry = (
            AssetPoolEntry._default_manager.filter(
                asset_code=asset_code,
                is_active=True,
            )
            .order_by("-entry_date")
            .first()
        )
        return entry.pool_type if entry else None

    def resolve_asset_names(self, codes: list[str]) -> dict[str, str]:
        """Resolve asset names from active asset-pool entries."""
        normalized_codes = [str(code).upper() for code in codes if code]
        if not normalized_codes:
            return {}

        rows = (
            AssetPoolEntry._default_manager.filter(
                asset_code__in=normalized_codes,
                is_active=True,
            )
            .values("asset_code", "asset_name")
            .distinct()
        )
        return {
            str(row["asset_code"]).upper(): row["asset_name"]
            for row in rows
            if row.get("asset_code") and row.get("asset_name")
        }

    def summarize_pool_counts(self, asset_type: str | None = None) -> dict[str, int]:
        queryset = AssetPoolEntry._default_manager.filter(is_active=True)
        if asset_type:
            queryset = queryset.filter(asset_category=asset_type)
        return {
            pool_type.value: queryset.filter(pool_type=pool_type.value).count()
            for pool_type in PoolType
        }


class AssetAnalysisLogRepository:
    """ORM-backed repository for asset-analysis scoring logs and alerts."""

    def create_scoring_log(self, payload: dict) -> int:
        """Create one scoring log row and return its id."""

        log = AssetScoringLog._default_manager.create(**payload)
        return int(log.id)

    def create_alert(self, payload: dict) -> int:
        """Create one analysis alert row and return its id."""

        alert = AssetAnalysisAlert._default_manager.create(**payload)
        return int(alert.id)

    def list_unresolved_alerts(
        self,
        *,
        severity: str | None = None,
        alert_type: str | None = None,
        limit: int = 100,
    ) -> list[AssetAnalysisAlert]:
        """Return unresolved alerts with optional filters."""

        queryset = AssetAnalysisAlert._default_manager.filter(is_resolved=False)
        if severity:
            queryset = queryset.filter(severity=severity)
        if alert_type:
            queryset = queryset.filter(alert_type=alert_type)
        return list(queryset.order_by("-created_at")[:limit])

    def resolve_alert(
        self,
        *,
        alert_id: int,
        resolved_by: int,
        resolved_at,
        resolution_notes: str | None = None,
    ) -> bool:
        """Mark one alert as resolved."""

        updated = AssetAnalysisAlert._default_manager.filter(id=alert_id).update(
            is_resolved=True,
            resolved_at=resolved_at,
            resolved_by=resolved_by,
            resolution_notes=resolution_notes,
        )
        return updated > 0
