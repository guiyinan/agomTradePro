"""
资产池管理服务

提供资产池分类、管理和统计功能。
"""

import logging
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

    def _get_asset_code(self, asset) -> str:
        """获取资产代码（兼容不同资产类型）"""
        return getattr(asset, 'asset_code', None) or \
               getattr(asset, 'stock_code', None) or \
               getattr(asset, 'fund_code', None) or \
               getattr(asset, 'bond_code', '')

    def _get_asset_name(self, asset) -> str:
        """获取资产名称（兼容不同资产类型）"""
        return getattr(asset, 'asset_name', None) or \
               getattr(asset, 'stock_name', None) or \
               getattr(asset, 'fund_name', None) or \
               getattr(asset, 'bond_name', '')

    def __init__(self):
        """初始化分类器"""
        # 默认配置（可从数据库加载）
        self.configs: dict[PoolCategory, PoolConfig] = {
            PoolCategory.EQUITY: PoolConfig(
                pool_type=PoolType.INVESTABLE,
                asset_category=PoolCategory.EQUITY,
                min_total_score=60.0,
                min_regime_score=50.0,
                min_policy_score=50.0,
                max_total_score=30.0,
                max_regime_score=40.0,
                max_policy_score=40.0,
                max_pe_ratio=50.0,
                max_pb_ratio=10.0,
            ),
            PoolCategory.FUND: PoolConfig(
                pool_type=PoolType.INVESTABLE,
                asset_category=PoolCategory.FUND,
                min_total_score=65.0,
                min_regime_score=55.0,
                min_policy_score=50.0,
                max_total_score=35.0,
                max_regime_score=40.0,
                max_policy_score=40.0,
            ),
            PoolCategory.BOND: PoolConfig(
                pool_type=PoolType.INVESTABLE,
                asset_category=PoolCategory.BOND,
                min_total_score=60.0,
                min_regime_score=50.0,
                min_policy_score=60.0,  # 债券对政策更敏感
                max_total_score=30.0,
                max_regime_score=40.0,
                max_policy_score=40.0,
            ),
        }

    def classify(
        self,
        asset: AssetScore,
        context: ScoreContext
    ) -> PoolEntry:
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
        if not config:
            # 使用默认配置
            config = PoolConfig(
                pool_type=PoolType.INVESTABLE,
                asset_category=category
            )

        # 判断资产池类型
        pool_type = self._determine_pool_type(asset, config)

        # 确定入池原因
        entry_reason = self._determine_entry_reason(asset, pool_type)

        return PoolEntry(
            asset_type=category,
            asset_code=self._get_asset_code(asset),
            asset_name=self._get_asset_name(asset),
            pool_type=pool_type,
            total_score=asset.total_score,
            regime_score=asset.regime_score,
            policy_score=asset.policy_score,
            sentiment_score=asset.sentiment_score,
            signal_score=asset.signal_score,
            entry_reason=entry_reason,
            risk_level=asset.risk_level,
            sector=getattr(asset, 'sector', None),
            market_cap=getattr(asset, 'market_cap', None),
            pe_ratio=getattr(asset, 'pe_ratio', None),
            pb_ratio=getattr(asset, 'pb_ratio', None),
            context={
                'regime': context.current_regime,
                'policy_level': context.policy_level,
                'sentiment_index': context.sentiment_index,
            },
        )

    def _get_category(self, asset_type) -> PoolCategory:
        """将 AssetType 转换为 PoolCategory（支持enum和string）"""
        # 处理字符串类型
        if isinstance(asset_type, str):
            type_mapping = {
                'equity': PoolCategory.EQUITY,
                'fund': PoolCategory.FUND,
                'bond': PoolCategory.BOND,
                'wealth': PoolCategory.WEALTH,
                'commodity': PoolCategory.COMMODITY,
                'index': PoolCategory.INDEX,
            }
            return type_mapping.get(asset_type.lower(), PoolCategory.EQUITY)

        # 处理枚举类型
        mapping = {
            AssetType.EQUITY: PoolCategory.EQUITY,
            AssetType.FUND: PoolCategory.FUND,
            AssetType.BOND: PoolCategory.BOND,
            AssetType.COMMODITY: PoolCategory.COMMODITY,
            AssetType.INDEX: PoolCategory.INDEX,
        }
        return mapping.get(asset_type, PoolCategory.EQUITY)

    def _determine_pool_type(self, asset: AssetScore, config: PoolConfig) -> PoolType:
        """确定资产池类型"""
        # 1. 检查是否禁投
        if config.is_prohibited(
            asset.total_score,
            asset.regime_score,
            asset.policy_score
        ):
            return PoolType.PROHIBITED

        # 2. 检查是否可投
        if config.is_investable(
            asset.total_score,
            asset.regime_score,
            asset.policy_score
        ):
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

        reasons = []

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

    def __init__(self):
        """初始化管理器"""
        self.classifier = AssetPoolClassifier()

    def create_pools(
        self,
        scored_assets: list[AssetScore],
        context: ScoreContext,
        asset_category: PoolCategory
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
        pools = {
            PoolType.INVESTABLE: [],
            PoolType.PROHIBITED: [],
            PoolType.WATCH: [],
            PoolType.CANDIDATE: [],
        }

        for asset in scored_assets:
            entry = self.classifier.classify(asset, context)
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
        asset_category: PoolCategory
    ) -> list[PoolStatistics]:
        """
        计算资产池统计信息

        Args:
            pools: 资产池字典
            asset_category: 资产类别

        Returns:
            统计信息列表
        """
        stats = []

        for pool_type, entries in pools.items():
            if not entries:
                continue

            # 计算平均分
            avg_total = sum(e.total_score for e in entries) / len(entries)
            avg_regime = sum(e.regime_score for e in entries) / len(entries)
            avg_policy = sum(e.policy_score for e in entries) / len(entries)

            # 计算行业分布
            sector_dist = {}
            for entry in entries:
                if entry.sector:
                    sector_dist[entry.sector] = sector_dist.get(entry.sector, 0) + 1

            stats.append(PoolStatistics(
                pool_type=pool_type,
                asset_category=asset_category,
                total_count=len(entries),
                avg_score=avg_total,
                avg_regime_score=avg_regime,
                avg_policy_score=avg_policy,
                sector_distribution=sector_dist,
                last_updated=date.today(),
            ))

        return stats

    def get_pool_summary(
        self,
        pools: dict[PoolType, list[PoolEntry]]
    ) -> dict[str, any]:
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
