"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""

from datetime import date
from decimal import Decimal
from typing import Any, cast

from django.db.models import Count, Q, Sum

from apps.simulated_trading.application.ports import (
    AdminDashboardRealizedPnlSummary,
)
from apps.simulated_trading.domain.entities import (
    SimulatedTrade,
)
from apps.simulated_trading.infrastructure.models import (
    SimulatedTradeModel,
)

from .execution_settlement_plan_binding_repository import (
    build_simulated_trade_execution_receipt,
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

    def sum_realized_pnl_for_closed_trades(self) -> AdminDashboardRealizedPnlSummary:
        """Return executed SELL PnL only when every row has complete cost evidence."""

        complete_sell = Q(
            cost_basis_known=True,
            fee_amounts_known=True,
            realized_pnl__isnull=False,
        )
        summary = SimulatedTradeModel._default_manager.filter(
            action="sell",
            status="executed",
        ).aggregate(
            executed_sell_count=Count("pk"),
            covered_executed_sell_count=Count("pk", filter=complete_sell),
            realized_pnl=Sum("realized_pnl", filter=complete_sell),
        )
        values = cast(dict[str, int | Decimal | None], summary)
        executed_sell_count = int(values["executed_sell_count"] or 0)
        covered_executed_sell_count = int(values["covered_executed_sell_count"] or 0)
        known = covered_executed_sell_count == executed_sell_count
        pnl_value = values["realized_pnl"]
        if executed_sell_count == 0:
            realized_pnl = Decimal("0.00")
        elif known and pnl_value is not None:
            realized_pnl = Decimal(str(pnl_value))
        else:
            known = False
            realized_pnl = None

        return {
            "realized_pnl": realized_pnl,
            "known": known,
            "covered_executed_sell_count": covered_executed_sell_count,
            "executed_sell_count": executed_sell_count,
        }

    def has_incomplete_closed_trade_costs(self, account_id: int | None = None) -> bool:
        """Return whether any executed sell lacks complete PnL evidence."""

        queryset = SimulatedTradeModel._default_manager.filter(
            action="sell",
            status="executed",
        )
        if account_id is not None:
            queryset = queryset.filter(account_id=account_id)
        return (
            queryset.exclude(
                cost_basis_known=True,
                fee_amounts_known=True,
            ).exists()
            or queryset.filter(realized_pnl__isnull=True).exists()
        )

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
        sell_trades = [
            trade for trade in trades if trade.action == "sell" and trade.status == "executed"
        ]
        total_realized_pnl_known = all(
            trade.cost_basis_known is True
            and trade.fee_amounts_known is True
            and trade.realized_pnl is not None
            for trade in sell_trades
        )
        total_realized_pnl = (
            sum(
                (
                    float(trade.realized_pnl)
                    for trade in sell_trades
                    if trade.realized_pnl is not None
                ),
                start=0.0,
            )
            if total_realized_pnl_known
            else None
        )
        return {
            "trades": trades,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_realized_pnl": total_realized_pnl,
            "total_realized_pnl_known": total_realized_pnl_known,
        }

    def get_owned_trade_by_id(
        self,
        *,
        trade_id: int,
        account_id: int,
        user_id: int,
    ) -> SimulatedTrade | None:
        """Return one trade only when its account belongs to the exact user."""

        if (
            type(trade_id) is not int
            or trade_id <= 0
            or type(account_id) is not int
            or account_id <= 0
            or type(user_id) is not int
            or user_id <= 0
        ):
            return None
        model = (
            SimulatedTradeModel._default_manager.using("default")
            .select_related("account")
            .filter(pk=trade_id, account_id=account_id, account__user_id=user_id)
            .first()
        )
        if model is None:
            return None
        build_simulated_trade_execution_receipt(model)
        return SimulatedTradeMapper.to_entity(model)

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
