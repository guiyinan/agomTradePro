"""
资产池查询服务

Application层:
- 为模拟盘自动交易引擎提供可投池资产
- 集成资产分析模块的资产池功能
- 筛选有有效信号的资产
"""
import logging
from typing import Dict, List, Optional

from apps.asset_analysis.domain.pool import PoolType
from apps.simulated_trading.application.ports import (
    AssetPoolQueryRepositoryProtocol,
    SignalQueryRepositoryProtocol,
)

logger = logging.getLogger(__name__)


class AssetPoolQueryService:
    """
    资产池查询服务

    提供可投池资产查询，用于自动交易引擎的买入逻辑
    """

    def __init__(
        self,
        asset_pool_repo: AssetPoolQueryRepositoryProtocol,
        signal_repo: SignalQueryRepositoryProtocol,
    ) -> None:
        self.asset_pool_repo = asset_pool_repo
        self.signal_repo = signal_repo

    def get_investable_assets(
        self,
        asset_type: str = "equity",
        min_score: float = 60.0,
        limit: int = 50
    ) -> list[dict]:
        """
        获取可投池资产

        Args:
            asset_type: 资产类型（equity/fund/bond）
            min_score: 最低评分要求
            limit: 最大返回数量

        Returns:
            候选资产列表，每个元素包含:
            {
                'asset_code': str,
                'asset_name': str,
                'asset_type': str,
                'score': float,
                'regime_score': float,
                'policy_score': float,
                'sentiment_score': float,
                'signal_score': float,
                'entry_date': date,
                'entry_reason': str,
            }
        """
        try:
            candidates = self.asset_pool_repo.list_investable_assets(
                asset_type=asset_type,
                min_score=min_score,
                limit=limit,
            )
            logger.info(f"从资产池查询到 {len(candidates)} 个可投资产（类型: {asset_type}, 最低评分: {min_score}）")
            return candidates
        except Exception as e:
            logger.error(f"查询可投池失败: {e}")
            return []

    def get_investable_assets_with_signals(
        self,
        asset_type: str = "equity",
        min_score: float = 60.0,
        limit: int = 50
    ) -> list[dict]:
        """
        获取可投池且有有效信号的资产

        Args:
            asset_type: 资产类型
            min_score: 最低评分
            limit: 最大返回数量

        Returns:
            候选资产列表（包含signal_id）
        """
        # 1. 获取可投池资产
        candidates = self.get_investable_assets(asset_type, min_score, limit)

        if not candidates:
            return []

        # 2. 筛选有有效信号的资产
        asset_codes = [c['asset_code'] for c in candidates]

        # 查询有效信号
        valid_signals = self.signal_repo.get_valid_signal_summaries(asset_codes=asset_codes)

        # 创建信号映射: {asset_code: signal}
        signal_map = {signal['asset_code']: signal for signal in valid_signals}

        # 3. 只保留有信号的资产
        candidates_with_signals = []
        for candidate in candidates:
            signal = signal_map.get(candidate['asset_code'])
            if signal:
                candidate['signal_id'] = signal['signal_id']
                candidate['signal_logic'] = signal['logic_desc']
                candidates_with_signals.append(candidate)

        logger.info(
            f"可投池中有 {len(candidates_with_signals)} 个资产有有效信号 "
            f"(总候选: {len(candidates)})"
        )

        return candidates_with_signals

    def get_asset_pool_type(self, asset_code: str) -> str | None:
        """
        获取资产所在的池类型

        Args:
            asset_code: 资产代码

        Returns:
            池类型（investable/prohibited/watch/candidate）
        """
        try:
            return self.asset_pool_repo.get_latest_pool_type(asset_code)
        except Exception as e:
            logger.error(f"查询资产池类型失败: {asset_code}, 错误: {e}")
            return None

    def get_pool_summary(self, asset_type: str = None) -> dict[str, int]:
        """
        获取资产池摘要统计

        Args:
            asset_type: 资产类型（None表示全部）

        Returns:
            {pool_type: count}
        """
        try:
            summary = self.asset_pool_repo.summarize_pool_counts(asset_type=asset_type)
            return {
                pool_type.value: summary.get(pool_type.value, 0)
                for pool_type in PoolType
            }
        except Exception as e:
            logger.error(f"获取资产池摘要失败: {e}")
            return {}

