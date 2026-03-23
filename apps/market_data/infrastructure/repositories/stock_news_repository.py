"""
股票新闻数据仓储

负责将标准化的 StockNewsItem 持久化到数据库，支持去重。
"""

import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import List

from apps.market_data.domain.entities import StockNewsItem
from apps.market_data.infrastructure.models import StockNewsModel

logger = logging.getLogger(__name__)


class StockNewsRepository:
    """股票新闻持久化仓储"""

    def save(self, item: StockNewsItem) -> bool:
        """保存单条新闻（去重）

        Returns:
            True 如果新增保存，False 如果已存在
        """
        _, created = StockNewsModel.objects.get_or_create(
            news_id=item.news_id,
            defaults={
                "stock_code": item.stock_code,
                "title": item.title,
                "content": item.content,
                "published_at": item.published_at,
                "url": item.url or "",
                "source": item.source,
            },
        )
        return created

    def save_batch(self, items: list[StockNewsItem]) -> int:
        """批量保存新闻（去重）

        Returns:
            新增保存的条数
        """
        new_count = 0
        for item in items:
            try:
                if self.save(item):
                    new_count += 1
            except Exception:
                logger.exception("保存新闻失败: %s %s", item.stock_code, item.news_id)
        return new_count

    def get_recent(
        self, stock_code: str, days: int = 3, limit: int = 50
    ) -> list[StockNewsItem]:
        """获取最近 N 天的新闻"""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        qs = (
            StockNewsModel.objects.filter(
                stock_code=stock_code,
                published_at__gte=cutoff,
            )
            .order_by("-published_at")[:limit]
        )
        return [self._to_entity(m) for m in qs]

    def count_recent(self, stock_code: str, days: int = 3) -> int:
        """统计最近 N 天的新闻数量"""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        return StockNewsModel.objects.filter(
            stock_code=stock_code,
            published_at__gte=cutoff,
        ).count()

    @staticmethod
    def _to_entity(model: StockNewsModel) -> StockNewsItem:
        return StockNewsItem(
            stock_code=model.stock_code,
            news_id=model.news_id,
            title=model.title,
            content=model.content,
            published_at=model.published_at,
            url=model.url or None,
            source=model.source,
        )
