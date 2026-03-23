"""
资金流向数据仓储

负责将标准化的 CapitalFlowSnapshot 持久化到数据库。
"""

import logging
from datetime import date
from typing import List, Optional

from apps.market_data.domain.entities import CapitalFlowSnapshot
from apps.market_data.infrastructure.models import StockCapitalFlowModel

logger = logging.getLogger(__name__)


class CapitalFlowRepository:
    """资金流向持久化仓储"""

    def save(self, snapshot: CapitalFlowSnapshot) -> None:
        """保存单条资金流向（upsert）"""
        StockCapitalFlowModel.objects.update_or_create(
            stock_code=snapshot.stock_code,
            trade_date=snapshot.trade_date,
            source=snapshot.source,
            defaults={
                "main_net_inflow": snapshot.main_net_inflow,
                "main_net_ratio": snapshot.main_net_ratio,
                "super_large_net_inflow": snapshot.super_large_net_inflow,
                "large_net_inflow": snapshot.large_net_inflow,
                "medium_net_inflow": snapshot.medium_net_inflow,
                "small_net_inflow": snapshot.small_net_inflow,
            },
        )

    def save_batch(self, snapshots: list[CapitalFlowSnapshot]) -> int:
        """批量保存资金流向

        Returns:
            成功保存的条数
        """
        saved = 0
        for snapshot in snapshots:
            try:
                self.save(snapshot)
                saved += 1
            except Exception:
                logger.exception(
                    "保存资金流向失败: %s %s",
                    snapshot.stock_code,
                    snapshot.trade_date,
                )
        return saved

    def get_latest(
        self, stock_code: str, days: int = 5
    ) -> list[CapitalFlowSnapshot]:
        """获取最近 N 天的资金流向"""
        qs = (
            StockCapitalFlowModel.objects.filter(stock_code=stock_code)
            .order_by("-trade_date")[:days]
        )
        return [self._to_entity(m) for m in qs]

    def get_by_date_range(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[CapitalFlowSnapshot]:
        """按日期范围查询资金流向"""
        qs = StockCapitalFlowModel.objects.filter(
            stock_code=stock_code,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        ).order_by("trade_date")
        return [self._to_entity(m) for m in qs]

    @staticmethod
    def _to_entity(model: StockCapitalFlowModel) -> CapitalFlowSnapshot:
        return CapitalFlowSnapshot(
            stock_code=model.stock_code,
            trade_date=model.trade_date,
            main_net_inflow=model.main_net_inflow,
            main_net_ratio=model.main_net_ratio,
            super_large_net_inflow=model.super_large_net_inflow or 0.0,
            large_net_inflow=model.large_net_inflow or 0.0,
            medium_net_inflow=model.medium_net_inflow or 0.0,
            small_net_inflow=model.small_net_inflow or 0.0,
            source=model.source,
        )
