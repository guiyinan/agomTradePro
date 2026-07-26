"""
资产池管理服务

提供资产池分类、管理和统计功能。
"""

import logging
import math
from datetime import date

from apps.asset_analysis.domain.entities import AssetScore, AssetType
from apps.asset_analysis.domain.pool import (
    EntryReason,
    PoolCategory,
    PoolConfig,
    PoolEntry,
    PoolStatistics,
    PoolType,
)
from apps.asset_analysis.domain.value_objects import ScoreContext

logger = logging.getLogger(__name__)


class AssetPoolClassifier:
    """
    资产池分类器

    根据评分结果将资产分类到不同的资产池。
    """

    def __init__(self, configs: list[PoolConfig]) -> None:
        """初始化分类器"""
        self.configs: dict[PoolCategory, PoolConfig] = {}
        for config in configs:
            if config.asset_category in self.configs:
                raise ValueError(f"Duplicate active pool config for {config.asset_category.value}")
            self.configs[config.asset_category] = config

    def classify(self, asset: AssetScore, context: ScoreContext) -> PoolEntry:
        """
        将资产分类到合适的资产池

        Args:
            asset: 已评分的资产
            context: 评分上下文

        Returns:
            资产池条目
        """
        # 确定资产类别
        category = self._get_category(asset.asset_type)

        # 获取配置
        config = self.configs.get(category)
        if config is None:
            raise ValueError(f"Missing active pool config for {category.value}")

        self._validate_asset(asset)

        # 判断资产池类型
        pool_type = self._determine_pool_type(asset, config)

        # 确定入池原因
        entry_reason = self._determine_entry_reason(asset, pool_type)

        return PoolEntry(
            asset_type=category,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            pool_type=pool_type,
            total_score=asset.total_score,
            regime_score=asset.regime_score,
            policy_score=asset.policy_score,
            sentiment_score=asset.sentiment_score,
            signal_score=asset.signal_score,
            entry_reason=entry_reason,
            risk_level=asset.risk_level,
            sector=asset.sector,
            market_cap=asset.custom_scores.get("market_cap"),
            pe_ratio=asset.custom_scores.get("pe_ratio"),
            pb_ratio=asset.custom_scores.get("pb_ratio"),
            context={
                "regime": context.current_regime,
                "policy_level": context.policy_level,
                "sentiment_index": context.sentiment_index,
            },
        )

    @staticmethod
    def _get_category(asset_type: AssetType) -> PoolCategory:
        """Convert a supported AssetType without silently changing categories."""
        mapping = {
            AssetType.EQUITY: PoolCategory.EQUITY,
            AssetType.FUND: PoolCategory.FUND,
            AssetType.BOND: PoolCategory.BOND,
            AssetType.COMMODITY: PoolCategory.COMMODITY,
            AssetType.INDEX: PoolCategory.INDEX,
        }
        category = mapping.get(asset_type)
        if category is None:
            raise ValueError(f"Unsupported pool asset type: {asset_type.value}")
        return category

    @staticmethod
    def _validate_asset(asset: AssetScore) -> None:
        if not asset.asset_code.strip() or not asset.asset_name.strip():
            raise ValueError("Pool asset code and name cannot be empty")
        for field_name in (
            "total_score",
            "regime_score",
            "policy_score",
            "sentiment_score",
            "signal_score",
        ):
            value = getattr(asset, field_name)
            if not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError(f"{field_name} must be finite and from 0 to 100")

    def _determine_pool_type(self, asset: AssetScore, config: PoolConfig) -> PoolType:
        """确定资产池类型"""
        # 1. 检查是否禁投
        if config.is_prohibited(asset.total_score, asset.regime_score, asset.policy_score):
            return PoolType.PROHIBITED

        # 2. 检查是否可投
        if config.is_investable(asset.total_score, asset.regime_score, asset.policy_score):
            return PoolType.INVESTABLE

        # 3. 检查是否观察
        if config.is_watch(asset.total_score):
            return PoolType.WATCH

        # 4. 默认候选池
        return PoolType.CANDIDATE

    def _determine_entry_reason(self, asset: AssetScore, pool_type: PoolType) -> EntryReason | None:
        """确定入池原因"""
        if pool_type == PoolType.PROHIBITED:
            return None

        reasons: list[EntryReason] = []

        # 高评分
        if asset.total_score >= 80:
            reasons.append(EntryReason.HIGH_SCORE)

        # Regime 匹配
        if asset.regime_score >= 75:
            reasons.append(EntryReason.REGIME_MATCH)

        # 政策友好
        if asset.policy_score >= 75:
            reasons.append(EntryReason.POLICY_FAVORABLE)

        # 情绪正面
        if asset.sentiment_score >= 70:
            reasons.append(EntryReason.SENTIMENT_POSITIVE)

        # 信号触发
        if asset.signal_score >= 60:
            reasons.append(EntryReason.SIGNAL_TRIGGERED)

        # 返回优先级最高的原因
        if reasons:
            return reasons[0]

        return EntryReason.MANUAL_ADD


class AssetPoolManager:
    """
    资产池管理器

    负责资产池的创建、更新和统计。
    """

    def __init__(self, configs: list[PoolConfig]) -> None:
        """初始化管理器"""
        self.classifier = AssetPoolClassifier(configs)

    def create_pools(
        self,
        scored_assets: list[AssetScore],
        context: ScoreContext,
        asset_category: PoolCategory,
    ) -> dict[PoolType, list[PoolEntry]]:
        """
        根据评分结果创建资产池

        Args:
            scored_assets: 已评分的资产列表
            context: 评分上下文
            asset_category: 资产类别

        Returns:
            按资产池类型分组的资产字典
        """
        pools: dict[PoolType, list[PoolEntry]] = {
            PoolType.INVESTABLE: [],
            PoolType.PROHIBITED: [],
            PoolType.WATCH: [],
            PoolType.CANDIDATE: [],
        }

        for asset in scored_assets:
            entry = self.classifier.classify(asset, context)
            if entry.asset_type != asset_category:
                raise ValueError(
                    f"Asset category mismatch: expected {asset_category.value}, "
                    f"got {entry.asset_type.value}"
                )
            pools[entry.pool_type].append(entry)

        logger.info(
            f"资产池创建完成: "
            f"可投{len(pools[PoolType.INVESTABLE])}, "
            f"禁投{len(pools[PoolType.PROHIBITED])}, "
            f"观察{len(pools[PoolType.WATCH])}, "
            f"候选{len(pools[PoolType.CANDIDATE])}"
        )

        return pools

    def calculate_statistics(
        self,
        pools: dict[PoolType, list[PoolEntry]],
        asset_category: PoolCategory,
    ) -> list[PoolStatistics]:
        """
        计算资产池统计信息

        Args:
            pools: 资产池字典
            asset_category: 资产类别

        Returns:
            统计信息列表
        """
        stats: list[PoolStatistics] = []

        for pool_type, entries in pools.items():
            if not entries:
                continue

            # 计算平均分
            avg_total = sum(e.total_score for e in entries) / len(entries)
            avg_regime = sum(e.regime_score for e in entries) / len(entries)
            avg_policy = sum(e.policy_score for e in entries) / len(entries)

            # 计算行业分布
            sector_dist: dict[str, int] = {}
            for entry in entries:
                if entry.sector:
                    sector_dist[entry.sector] = sector_dist.get(entry.sector, 0) + 1

            stats.append(
                PoolStatistics(
                    pool_type=pool_type,
                    asset_category=asset_category,
                    total_count=len(entries),
                    avg_score=avg_total,
                    avg_regime_score=avg_regime,
                    avg_policy_score=avg_policy,
                    sector_distribution=sector_dist,
                    last_updated=date.today(),
                )
            )

        return stats

    def get_pool_summary(
        self,
        pools: dict[PoolType, list[PoolEntry]],
    ) -> dict[str, int]:
        """
        获取资产池摘要

        Args:
            pools: 资产池字典

        Returns:
            摘要信息字典
        """
        return {
            "investable_count": len(pools.get(PoolType.INVESTABLE, [])),
            "prohibited_count": len(pools.get(PoolType.PROHIBITED, [])),
            "watch_count": len(pools.get(PoolType.WATCH, [])),
            "candidate_count": len(pools.get(PoolType.CANDIDATE, [])),
            "total_count": sum(len(entries) for entries in pools.values()),
        }
