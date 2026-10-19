"""Read-only financial summaries for simulated trades."""

from decimal import Decimal
from typing import Any, cast

from django.db.models import Count, Q, Sum

from apps.simulated_trading.application.ports import (
    AdminDashboardRealizedPnlSummary,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel


class DjangoTradeSummaryRepository:
    """Own aggregate and account-page summary queries for simulated trades."""

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
