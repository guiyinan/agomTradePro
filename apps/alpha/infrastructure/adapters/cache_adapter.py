"""
Cache Alpha Provider

从数据库缓存读取 Alpha 评分的 Provider。
优先级较高，因为缓存数据稳定且快速。
"""

import logging
from datetime import date, timedelta
from typing import List, Optional

from ...domain.entities import AlphaResult, StockScore
from ...domain.interfaces import AlphaProviderStatus
from .base import BaseAlphaProvider, provider_safe


logger = logging.getLogger(__name__)

try:
    from ...infrastructure.models import AlphaScoreCacheModel
except Exception:  # pragma: no cover - fallback for import-time edge cases
    AlphaScoreCacheModel = None


def _get_cache_model():
    if AlphaScoreCacheModel is not None:
        return AlphaScoreCacheModel
    from ...infrastructure.models import AlphaScoreCacheModel as cache_model
    return cache_model


class CacheAlphaProvider(BaseAlphaProvider):
    """
    缓存 Alpha 提供者

    从 AlphaScoreCache 数据库表读取历史缓存数据。
    优先级为 10，仅次于 Qlib。

    Attributes:
        priority: 10（高优先级）
        max_staleness_days: 5 天（缓存可以接受更旧的数据）

    Example:
        >>> provider = CacheAlphaProvider()
        >>> result = provider.get_stock_scores("csi300", date.today())
        >>> if result.success:
        ...     print(f"Found {len(result.scores)} cached scores")
    """

    def __init__(self, max_staleness_days: int = 5):
        """
        初始化缓存 Provider

        Args:
            max_staleness_days: 最大可接受的数据陈旧天数（默认 5 天）
        """
        super().__init__()
        self._max_staleness_days = max_staleness_days

    @property
    def name(self) -> str:
        """Provider 名称"""
        return "cache"

    @property
    def priority(self) -> int:
        """优先级"""
        return 10

    @property
    def max_staleness_days(self) -> int:
        """最大陈旧天数"""
        return self._max_staleness_days

    @provider_safe(default_success=False)
    def health_check(self) -> AlphaProviderStatus:
        """
        健康检查

        检查数据库连接和缓存表是否存在。

        Returns:
            Provider 状态
        """
        try:
            cache_model = _get_cache_model()

            # 检查是否有缓存数据
            has_recent_cache = cache_model.objects.filter(
                created_at__gte=date.today() - timedelta(days=7)
            ).exists()

            if has_recent_cache:
                return AlphaProviderStatus.AVAILABLE
            else:
                return AlphaProviderStatus.DEGRADED

        except Exception as e:
            logger.error(f"Cache health check failed: {e}")
            return AlphaProviderStatus.UNAVAILABLE

    @provider_safe()
    def get_stock_scores(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30
    ) -> AlphaResult:
        """
        从缓存获取股票评分

        1. 首先尝试精确匹配日期
        2. 如果没有，尝试最近的有效缓存
        3. 检查 staleness，如果过期返回 degraded

        Args:
            universe_id: 股票池标识
            intended_trade_date: 计划交易日期
            top_n: 返回前 N 只

        Returns:
            AlphaResult
        """
        cache_model = _get_cache_model()

        # 1. 尝试精确匹配
        cache = cache_model.objects.filter(
            universe_id=universe_id,
            intended_trade_date=intended_trade_date
        ).order_by("-created_at").first()

        # 2. 如果没有精确匹配，尝试最近的有效缓存（向前查找）
        if not cache:
            cache = cache_model.objects.filter(
                universe_id=universe_id,
                intended_trade_date__lte=intended_trade_date
            ).order_by("-intended_trade_date", "-created_at").first()

        if not cache:
            return self._create_error_result(
                f"未找到 {universe_id} 的缓存数据",
                status="unavailable"
            )

        # 3. 检查 staleness
        staleness_days = cache.get_staleness_days()
        is_stale = staleness_days > self.max_staleness_days

        # 4. 解析评分
        scores = self._parse_scores(cache.scores, top_n)
        if not scores:
            return self._create_error_result(
                f"{universe_id} 缓存存在但评分为空或损坏",
                status="unavailable",
            )

        if is_stale:
            return self._create_degraded_result(
                scores=scores,
                staleness_days=staleness_days,
                reason=f"缓存数据过期 {staleness_days} 天（最大允许 {self.max_staleness_days} 天）"
            )

        return self._create_success_result(
            scores=scores,
            staleness_days=staleness_days,
            metadata={
                "cache_date": cache.intended_trade_date.isoformat(),
                "asof_date": cache.asof_date.isoformat(),
                "provider_source": cache.provider_source,
                "created_at": cache.created_at.isoformat(),
            }
        )

    def _parse_scores(self, raw_scores: list, top_n: int) -> List[StockScore]:
        """
        解析原始评分数据

        Args:
            raw_scores: 原始 JSON 数据
            top_n: 返回前 N 只

        Returns:
            StockScore 列表
        """
        scores = []
        for item in raw_scores[:top_n]:
            try:
                payload = dict(item)
                payload.setdefault("source", "cache")
                scores.append(StockScore.from_dict(payload))
            except Exception as e:
                logger.warning(f"解析评分失败: {item}, error: {e}")
                continue

        return scores

    def get_available_dates(
        self,
        universe_id: str,
        start_date: date,
        end_date: date
    ) -> List[date]:
        """
        获取指定日期范围内的可用缓存日期

        Args:
            universe_id: 股票池标识
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            可用日期列表
        """
        cache_model = _get_cache_model()

        caches = cache_model.objects.filter(
            universe_id=universe_id,
            intended_trade_date__gte=start_date,
            intended_trade_date__lte=end_date
        ).values_list("intended_trade_date", flat=True).distinct()

        return sorted(set(caches))

    def get_latest_cache_date(self, universe_id: str) -> Optional[date]:
        """
        获取指定股票池的最新缓存日期

        Args:
            universe_id: 股票池标识

        Returns:
            最新缓存日期，如果没有则返回 None
        """
        cache_model = _get_cache_model()

        cache = cache_model.objects.filter(
            universe_id=universe_id
        ).order_by("-intended_trade_date").first()

        return cache.intended_trade_date if cache else None

    def clear_stale_cache(
        self,
        universe_id: str,
        days_to_keep: int = 30
    ) -> int:
        """
        清理过期缓存

        Args:
            universe_id: 股票池标识
            days_to_keep: 保留最近多少天的缓存

        Returns:
            删除的记录数
        """
        cache_model = _get_cache_model()

        cutoff_date = date.today() - timedelta(days=days_to_keep)

        deleted, _ = cache_model.objects.filter(
            universe_id=universe_id,
            intended_trade_date__lt=cutoff_date
        ).delete()

        logger.info(f"清理了 {deleted} 条过期缓存（{universe_id}）")
        return deleted

