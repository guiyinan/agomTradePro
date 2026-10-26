"""Read-only financial summaries for simulated trades."""

from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionHistoryRepositoryProtocol,
)
from apps.simulated_trading.application.ports import (
    AdminDashboardRealizedPnlSummary,
)
from apps.simulated_trading.domain.entities import SimulatedTrade
from apps.simulated_trading.domain.fee_correction import sum_signed_ledger_money
from apps.simulated_trading.infrastructure.fee_correction_runtime import (
    build_django_fee_correction_repository,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from apps.simulated_trading.infrastructure.order_reservation_fill_trade_read_guard import (
    validate_v4_trade_history,
)


class DjangoTradeSummaryRepository:
    """Own aggregate and account-page summary queries for simulated trades."""

    def __init__(
        self,
        *,
        fee_correction_history: FeeCorrectionHistoryRepositoryProtocol | None = None,
    ) -> None:
        """Inject the validated effective-history reader used by every summary."""

        self._fee_correction_history = (
            fee_correction_history or build_django_fee_correction_repository()
        )

    def sum_realized_pnl_for_closed_trades(self) -> AdminDashboardRealizedPnlSummary:
        """Return executed SELL PnL only when every row has complete cost evidence."""

        queryset = SimulatedTradeModel._default_manager.filter(
            action="sell",
            status="executed",
        )
        validate_v4_trade_history(queryset)
        sell_rows = tuple(
            queryset.only(
                "id",
                "account_id",
                "cost_basis_known",
                "fee_amounts_known",
                "realized_pnl",
            )
        )
        executed_sell_count = len(sell_rows)
        if executed_sell_count == 0:
            return {
                "realized_pnl": Decimal("0.00"),
                "known": True,
                "covered_executed_sell_count": 0,
                "executed_sell_count": 0,
                "effective_realized_pnl": Decimal("0.00"),
                "effective_known": True,
                "effective_covered_executed_sell_count": 0,
            }

        as_of = timezone.now()
        projected_by_id: dict[int, SimulatedTrade] = {}
        account_ids = sorted({row.account_id for row in sell_rows})
        for account_id in account_ids:
            projection = self._fee_correction_history.get_account_history(
                account_id=account_id,
                as_of=as_of,
            )
            projected_by_id.update(
                (trade.trade_id, trade)
                for trade in projection.trades
                if trade.action.value == "sell" and trade.status.value == "executed"
            )

        original_values: list[Decimal] = []
        effective_values: list[Decimal] = []
        for row in sell_rows:
            if (
                row.cost_basis_known is True
                and row.fee_amounts_known is True
                and row.realized_pnl is not None
            ):
                original_values.append(Decimal(str(row.realized_pnl)))
            trade = projected_by_id.get(row.pk)
            projected_realized_pnl = trade.current_realized_pnl if trade is not None else None
            if (
                row.cost_basis_known is not True
                or row.fee_amounts_known is not True
                or projected_realized_pnl is None
            ):
                continue
            effective_values.append(Decimal(str(projected_realized_pnl)))
        covered_executed_sell_count = len(original_values)
        effective_covered_count = len(effective_values)
        known = covered_executed_sell_count == executed_sell_count
        effective_known = effective_covered_count == executed_sell_count
        realized_pnl = (
            sum_signed_ledger_money(original_values, "admin.original_realized_pnl")
            if known
            else None
        )
        effective_realized_pnl = (
            sum_signed_ledger_money(effective_values, "admin.effective_realized_pnl")
            if effective_known
            else None
        )

        return {
            "realized_pnl": realized_pnl,
            "known": known,
            "covered_executed_sell_count": covered_executed_sell_count,
            "executed_sell_count": executed_sell_count,
            "effective_realized_pnl": effective_realized_pnl,
            "effective_known": effective_known,
            "effective_covered_executed_sell_count": effective_covered_count,
        }

    def has_incomplete_closed_trade_costs(self, account_id: int | None = None) -> bool:
        """Return whether any executed sell lacks complete PnL evidence."""

        queryset = SimulatedTradeModel._default_manager.filter(
            action="sell",
            status="executed",
        )
        if account_id is not None:
            queryset = queryset.filter(account_id=account_id)
        validate_v4_trade_history(queryset)
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
        validate_v4_trade_history(queryset)
        buy_count = queryset.filter(action="buy").count()
        sell_count = queryset.filter(action="sell").count()
        total_trade_count = queryset.count()
        projection = self._fee_correction_history.get_account_history(
            account_id=account_id,
            as_of=timezone.now(),
        )
        all_trades = projection.trades
        trades = list(reversed(all_trades))[:limit]
        sell_trades = [
            trade
            for trade in all_trades
            if trade.action.value == "sell" and trade.status.value == "executed"
        ]
        original_total_realized_pnl_known = all(
            trade.cost_basis_known is True
            and trade.fee_amounts_known is True
            and trade.realized_pnl is not None
            for trade in sell_trades
        )
        effective_total_realized_pnl_known = all(
            trade.cost_basis_known is True
            and trade.fee_amounts_known is True
            and trade.current_realized_pnl is not None
            for trade in sell_trades
        )
        original_total_realized_pnl = (
            sum_signed_ledger_money(
                tuple(
                    Decimal(str(trade.realized_pnl))
                    for trade in sell_trades
                    if trade.realized_pnl is not None
                ),
                "trade_page.original_realized_pnl",
            )
            if original_total_realized_pnl_known
            else None
        )
        effective_total_realized_pnl = (
            sum_signed_ledger_money(
                tuple(
                    Decimal(str(trade.current_realized_pnl))
                    for trade in sell_trades
                    if trade.current_realized_pnl is not None
                ),
                "trade_page.effective_realized_pnl",
            )
            if effective_total_realized_pnl_known
            else None
        )
        return {
            "trades": trades,
            "total_trade_count": total_trade_count,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_realized_pnl": original_total_realized_pnl,
            "total_realized_pnl_known": original_total_realized_pnl_known,
            "effective_total_realized_pnl": effective_total_realized_pnl,
            "effective_total_realized_pnl_known": effective_total_realized_pnl_known,
        }
