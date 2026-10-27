"""Read-only account-page summaries for simulated trades."""

from decimal import Decimal
from typing import Any

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionHistoryRepositoryProtocol,
)
from apps.simulated_trading.application.ports import AdminDashboardRealizedPnlSummary
from apps.simulated_trading.domain.fee_correction import sum_signed_ledger_money
from apps.simulated_trading.infrastructure.fee_correction_runtime import (
    build_django_fee_correction_repository,
)
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel
from apps.simulated_trading.infrastructure.order_reservation_fill_trade_read_guard import (
    validate_v4_trade_history,
)

from .trade_realized_pnl_summary_repository import DjangoTradeRealizedPnlSummaryRepository


class DjangoTradeSummaryRepository:
    """Preserve the established summary API while splitting global aggregates."""

    def __init__(
        self,
        *,
        fee_correction_history: FeeCorrectionHistoryRepositoryProtocol | None = None,
    ) -> None:
        """Inject the validated effective-history reader used by every summary."""

        self._fee_correction_history = (
            fee_correction_history or build_django_fee_correction_repository()
        )
        self._realized_pnl_summary = DjangoTradeRealizedPnlSummaryRepository(
            fee_correction_history=self._fee_correction_history
        )

    def sum_realized_pnl_for_closed_trades(self) -> AdminDashboardRealizedPnlSummary:
        """Return the guarded global executed-sell PnL summary."""

        return self._realized_pnl_summary.sum_realized_pnl_for_closed_trades()

    def has_incomplete_closed_trade_costs(
        self,
        account_id: int | None = None,
        *,
        using: str = DEFAULT_DB_ALIAS,
    ) -> bool:
        """Return whether executed sells lack complete cost evidence."""

        return self._realized_pnl_summary.has_incomplete_closed_trade_costs(
            account_id,
            using=using,
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
