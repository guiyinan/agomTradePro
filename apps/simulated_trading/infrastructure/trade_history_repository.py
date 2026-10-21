"""Read-only ownership queries for simulated trade history."""

from django.db.models import Q

from apps.simulated_trading.domain.entities import SimulatedTrade
from apps.simulated_trading.infrastructure.models import SimulatedTradeModel

from .execution_settlement_plan_binding_repository import (
    build_simulated_trade_execution_receipt,
)
from .order_reservation_fill_trade_read_guard import validate_v4_trade_history
from .trade_mapper import SimulatedTradeMapper


class DjangoTradeHistoryRepository:
    """Own receipt-aware ownership and Admin protection queries for Trades."""

    def get_admin_read_only_trade_ids(self, trade_ids: tuple[int, ...]) -> frozenset[int]:
        """Return selected Trades carrying a V4 marker or immutable fill receipt."""

        selected_ids = tuple(
            trade_id for trade_id in trade_ids if type(trade_id) is int and trade_id > 0
        )
        if not selected_ids:
            return frozenset()
        rows = SimulatedTradeModel._default_manager.filter(pk__in=selected_ids).filter(
            Q(settlement_plan_binding_version=4) | Q(fill_receipt__isnull=False)
        )
        return frozenset(int(trade_id) for trade_id in rows.values_list("pk", flat=True))

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
        validate_v4_trade_history(
            SimulatedTradeModel._default_manager.using("default").filter(
                pk=trade_id,
                account_id=account_id,
                account__user_id=user_id,
            )
        )
        if model.settlement_plan_binding_version != 4:
            build_simulated_trade_execution_receipt(model)
        return SimulatedTradeMapper.to_entity(model)
