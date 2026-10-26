"""Global executed-sell realized-PnL and cost-completeness reads."""

from decimal import Decimal

from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionHistoryRepositoryProtocol,
)
from apps.simulated_trading.application.ports import AdminDashboardRealizedPnlSummary
from apps.simulated_trading.domain.entities import SimulatedTrade
from apps.simulated_trading.domain.fee_correction import sum_signed_ledger_money
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from apps.simulated_trading.infrastructure.order_reservation_fill_trade_read_guard import (
    validate_v4_trade_history,
)


class DjangoTradeRealizedPnlSummaryRepository:
    """Aggregate original/effective realized PnL with V4 history validation."""

    def __init__(
        self,
        *,
        fee_correction_history: FeeCorrectionHistoryRepositoryProtocol,
    ) -> None:
        """Inject the same validated history reader used by account summaries."""

        self._fee_correction_history = fee_correction_history

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
