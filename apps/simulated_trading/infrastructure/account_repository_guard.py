"""Parent-lock and account-order-history guards from G1."""

from dataclasses import fields
from decimal import Decimal

from django.db import DEFAULT_DB_ALIAS
from django.db.models import Q

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.entities import (
    AccountCashReconciliationStatus,
    SimulatedAccount,
)
from apps.simulated_trading.infrastructure.account_mapper import SimulatedAccountMapper
from apps.simulated_trading.infrastructure.models import (
    LocalDailyMatchModel,
    SimulatedAccountModel,
    SimulatedOrderFillReceiptModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from core.exceptions import BusinessLogicError


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


def _require_account_snapshot_matches(
    model: SimulatedAccountModel,
    expected: SimulatedAccount,
    *,
    ignored_fields: frozenset[str] = frozenset(),
) -> None:
    """Reject a stale entity before a caller writes its narrowly owned fields."""

    actual = SimulatedAccountMapper.to_entity(model)
    changed_fields = [
        field.name
        for field in fields(SimulatedAccount)
        if field.name not in ignored_fields
        and getattr(actual, field.name) != getattr(expected, field.name)
    ]
    if changed_fields:
        raise BusinessLogicError(
            "账户快照已变化，拒绝使用旧实体覆盖当前状态",
            code="ACCOUNT_FINANCIAL_SNAPSHOT_CHANGED",
            details={
                "account_id": expected.account_id,
                "changed_fields": changed_fields,
            },
        )


def _require_order_history_deletable(account_id: int) -> None:
    """Retain terminal order identity before a parent-locked account deletion."""
    if (
        LocalDailyMatchModel._base_manager.using(DEFAULT_DB_ALIAS)
        .filter(Q(account_id=account_id) | Q(reservation__account_id=account_id))
        .exists()
    ):
        raise SimulatedTradeExecutionBlocked(
            "retained local daily match evidence prevents deleting this account",
            code="ORDER_RESERVATION_HISTORY_RETAINED",
        )
    if (
        SimulatedOrderReservationModel._base_manager.using(DEFAULT_DB_ALIAS)
        .filter(account_id=account_id)
        .exists()
    ):
        raise SimulatedTradeExecutionBlocked(
            "retained order reservation history prevents deleting this account",
            code="ORDER_RESERVATION_HISTORY_RETAINED",
        )


def _require_reset_fill_history_absent(account_id: int) -> None:
    """Keep immutable fill evidence and V4 trade markers when resetting a ledger."""

    has_receipt = (
        SimulatedOrderFillReceiptModel._base_manager.using(DEFAULT_DB_ALIAS)
        .filter(Q(reservation__account_id=account_id) | Q(trade__account_id=account_id))
        .exists()
    )
    has_v4_trade = (
        SimulatedTradeModel._base_manager.using(DEFAULT_DB_ALIAS)
        .filter(account_id=account_id, settlement_plan_binding_version=4)
        .exists()
    )
    has_local_match = (
        LocalDailyMatchModel._base_manager.using(DEFAULT_DB_ALIAS)
        .filter(Q(account_id=account_id) | Q(reservation__account_id=account_id))
        .exists()
    )
    if has_receipt or has_v4_trade or has_local_match:
        raise SimulatedTradeExecutionBlocked(
            "persisted fill history prevents resetting this simulated account",
            code="ORDER_FILL_HISTORY_RETAINED",
        )
