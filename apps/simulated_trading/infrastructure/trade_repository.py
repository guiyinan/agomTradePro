"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""

from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Sum

from apps.simulated_trading.domain.entities import (
    SimulatedTrade,
)
from apps.simulated_trading.infrastructure.models import (
    SimulatedTradeModel,
)

from .repository_helpers import _require_saved_id
from .trade_mapper import SimulatedTradeMapper


class DjangoTradeRepository:
    """交易记录Repository实现"""

    def create_trade_record(self, **payload: Any) -> SimulatedTradeModel:
        """Create one ORM trade row and return it."""

        return SimulatedTradeModel._default_manager.create(**payload)

    def save(self, trade: SimulatedTrade) -> int:
        """
        保存交易记录

        Returns:
            交易ID
        """
        model = SimulatedTradeMapper.to_model(trade)
        model.id = None  # 确保是新记录
        model.save()
        return _require_saved_id(model.id, "simulated trade")

    def get_by_account(self, account_id: int) -> list[SimulatedTrade]:
        """获取账户的所有交易记录"""
        models = SimulatedTradeModel._default_manager.filter(account_id=account_id).order_by(
            "-execution_date", "-execution_time"
        )
        return [SimulatedTradeMapper.to_entity(m) for m in models]

    def count_trade_models(self) -> int:
        """Return the total number of trade ORM rows."""

        return int(SimulatedTradeModel._default_manager.count())

    def summarize_trade_models_for_date(self, execution_date: date) -> dict[str, int]:
        """Return buy/sell counts for one execution date."""

        queryset = SimulatedTradeModel._default_manager.filter(execution_date=execution_date)
        return {
            "buy_count": int(queryset.filter(action="buy").count()),
            "sell_count": int(queryset.filter(action="sell").count()),
        }

    def sum_realized_pnl_for_closed_trades(self) -> Decimal:
        """Return aggregated realized pnl for completed sell trades."""

        total = SimulatedTradeModel._default_manager.filter(
            action="sell",
            realized_pnl__isnull=False,
        ).aggregate(total=Sum("realized_pnl"))
        return Decimal(str(total["total"] or 0))

    def list_trade_models_for_account(self, account_id: int, limit: int | None = None) -> list[Any]:
        """Return trade ORM rows for template rendering."""

        queryset = SimulatedTradeModel._default_manager.filter(account_id=account_id)
        if limit is not None:
            queryset = queryset[:limit]
        return list(queryset)

    def get_trade_model_summary_for_account(
        self,
        account_id: int,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return trade rows plus lightweight counts for account trade pages."""

        queryset = SimulatedTradeModel._default_manager.filter(account_id=account_id)
        buy_count = queryset.filter(action="buy").count()
        sell_count = queryset.filter(action="sell").count()
        trades = list(queryset[:limit])
        total_realized_pnl = sum(float(trade.realized_pnl or 0) for trade in trades)
        return {
            "trades": trades,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_realized_pnl": total_realized_pnl,
        }

    def get_by_date_range(
        self,
        account_id: int,
        start_date: date,
        end_date: date,
    ) -> list[SimulatedTrade]:
        """获取日期范围内的交易记录。"""

        models = SimulatedTradeModel._default_manager.filter(
            account_id=account_id,
            execution_date__gte=start_date,
            execution_date__lte=end_date,
        ).order_by("-execution_date", "-execution_time")
        return [SimulatedTradeMapper.to_entity(m) for m in models]

    def get_by_asset(self, account_id: int, asset_code: str) -> list[SimulatedTrade]:
        """获取特定资产的所有交易记录。"""

        models = SimulatedTradeModel._default_manager.filter(
            account_id=account_id,
            asset_code=asset_code,
        ).order_by("-execution_date", "-execution_time")
        return [SimulatedTradeMapper.to_entity(m) for m in models]

    def count_by_execution_date(self, account_id: int, execution_date: date) -> int:
        """按执行日期统计交易数。"""

        return int(
            SimulatedTradeModel._default_manager.filter(
                account_id=account_id,
                execution_date=execution_date,
            ).count()
        )
