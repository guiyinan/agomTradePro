"""
资产池查询服务

Application层:
- 为模拟盘自动交易引擎提供可投池资产
- 集成资产分析模块的资产池功能
- 筛选有有效信号的资产
"""

import logging
import math

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
        limit: int = 50,
    ) -> list[dict[str, object]]:
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
        normalized_asset_type = asset_type.strip().lower()
        if not normalized_asset_type or not math.isfinite(min_score) or limit <= 0:
            return []

        try:
            candidates = self.asset_pool_repo.list_investable_assets(
                asset_type=normalized_asset_type,
                min_score=min_score,
                limit=min(limit, 500),
            )
            logger.info(
                "从资产池查询到 %s 个可投资产（类型: %s, 最低评分: %s）",
                len(candidates),
                normalized_asset_type,
                min_score,
            )
            return candidates
        except Exception:
            logger.exception("查询可投池失败")
            return []

    def get_investable_assets_with_signals(
        self,
        asset_type: str = "equity",
        min_score: float = 60.0,
        limit: int = 50,
    ) -> list[dict[str, object]]:
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
        normalized_candidates: list[dict[str, object]] = []
        for candidate in candidates:
            asset_code = self._normalize_asset_code(candidate.get("asset_code"))
            if not asset_code:
                continue
            normalized_candidate = dict(candidate)
            normalized_candidate["asset_code"] = asset_code
            normalized_candidates.append(normalized_candidate)

        if not normalized_candidates:
            return []

        asset_codes = [str(candidate["asset_code"]) for candidate in normalized_candidates]

        # 查询有效信号
        valid_signals = self.signal_repo.get_valid_signal_summaries(asset_codes=asset_codes)

        # Repository 按时间倒序返回；同资产只保留第一条（最新）信号。
        signal_map: dict[str, dict[str, object]] = {}
        for signal in valid_signals:
            signal_asset_code = self._normalize_asset_code(signal.get("asset_code"))
            if signal_asset_code and signal_asset_code not in signal_map:
                signal_map[signal_asset_code] = signal

        # 3. 只保留有信号的资产
        candidates_with_signals: list[dict[str, object]] = []
        for candidate in normalized_candidates:
            matched_signal = signal_map.get(str(candidate["asset_code"]))
            if not matched_signal:
                continue
            signal_id = matched_signal.get("signal_id", matched_signal.get("id"))
            if not isinstance(signal_id, int) or isinstance(signal_id, bool):
                logger.warning(
                    "忽略缺少有效 signal_id 的资产信号: %s",
                    candidate["asset_code"],
                )
                continue
            enriched_candidate = dict(candidate)
            enriched_candidate["signal_id"] = signal_id
            enriched_candidate["signal_logic"] = str(matched_signal.get("logic_desc") or "")
            candidates_with_signals.append(enriched_candidate)

        logger.info(
            f"可投池中有 {len(candidates_with_signals)} 个资产有有效信号 "
            f"(总候选: {len(normalized_candidates)})"
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
        normalized_asset_code = self._normalize_asset_code(asset_code)
        if not normalized_asset_code:
            return None
        try:
            return self.asset_pool_repo.get_latest_pool_type(normalized_asset_code)
        except Exception:
            logger.exception("查询资产池类型失败: %s", normalized_asset_code)
            return None

    def get_pool_summary(self, asset_type: str | None = None) -> dict[str, int]:
        """
        获取资产池摘要统计

        Args:
            asset_type: 资产类型（None表示全部）

        Returns:
            {pool_type: count}
        """
        try:
            summary = self.asset_pool_repo.summarize_pool_counts(asset_type=asset_type)
            return {pool_type.value: summary.get(pool_type.value, 0) for pool_type in PoolType}
        except Exception:
            logger.exception("获取资产池摘要失败")
            return {}

    @staticmethod
    def _normalize_asset_code(value: object) -> str:
        """Return the canonical asset code used to join pools and signals."""

        return str(value or "").strip().upper()
