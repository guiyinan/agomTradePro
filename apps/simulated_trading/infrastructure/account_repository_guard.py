"""Parent-lock and account-order-history guards from G1."""

from decimal import Decimal

from django.db import DEFAULT_DB_ALIAS

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.entities import (
    AccountCashReconciliationStatus,
    SimulatedAccount,
)
from apps.simulated_trading.infrastructure.models import (
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
)


def _account_order_scope_changed(
    model: SimulatedAccountModel,
    account: SimulatedAccount,
) -> bool:
    """Detect stale resources or attempts to re-enable a stopped account."""

    cash_status = (
        account.cash_reconciliation_status.value
        if account.cash_reconciliation_status is not None
        else AccountCashReconciliationStatus.UNVERIFIED.value
    )
    try:
        incoming_cash = Decimal(str(account.current_cash))
    except (ArithmeticError, TypeError, ValueError):
        return True
    return any(
        (
            model.current_cash != incoming_cash,
            model.cash_known is not account.cash_known,
            model.cash_reconciliation_status != cash_status,
            model.account_type != account.account_type.value,
            (model.is_active is not account.is_active and account.is_active is not False),
            (
                model.auto_trading_enabled is not account.auto_trading_enabled
                and account.auto_trading_enabled is not False
            ),
        )
    )


def _lock_account_for_order_guard(account_id: int) -> SimulatedAccountModel:
    """Lock the account parent before inspecting or changing its held resources."""

    return (
        SimulatedAccountModel._default_manager.using(DEFAULT_DB_ALIAS)
        .select_for_update()
        .get(pk=account_id)
    )


def _require_order_history_deletable(account_id: int) -> None:
    """Retain terminal order identity before a parent-locked account deletion."""
    if (
        SimulatedOrderReservationModel._base_manager.using(DEFAULT_DB_ALIAS)
        .filter(account_id=account_id)
        .exists()
    ):
        raise SimulatedTradeExecutionBlocked(
            "retained order reservation history prevents deleting this account",
            code="ORDER_RESERVATION_HISTORY_RETAINED",
        )
