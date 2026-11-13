"""Exact validation helpers for the locked reservation repository."""

from __future__ import annotations

from decimal import Decimal

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationBook,
    OrderReservationRequest,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_balance_repository import (
    read_locked_corporate_action_tax_payable,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    current_order_reservation_book,
    fee_policy_from_snapshot,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_sqlite_precision import (
    PrecisionFamily,
    require_sqlite_values,
)
from core.exceptions import BusinessLogicError


def require_exact_order_retry(
    *,
    row: SimulatedOrderReservationModel,
    intent: SimulatedTradeIntent,
    request: OrderReservationRequest,
    reservation: OrderReservation,
) -> None:
    """Compare the complete stored intent and fee-bound reservation identity."""

    policy = fee_policy_from_snapshot(validated_plan_snapshot(row))
    expected = request.identity(fee_policy_hash=policy.content_hash)
    if (
        row.intent_payload_hash != intent.request_payload_hash
        or row.reservation_request_hash != expected.request_payload_hash
        or reservation.identity != expected
    ):
        raise SimulatedTradeIdempotencyConflict(
            "order key is already bound to a different exact intent or fee budget"
        )


def require_locked_reservation_source_precision(
    *,
    account: SimulatedAccountModel,
    position: PositionModel | None,
    pending_rows: list[SimulatedTradeModel],
    using: str,
) -> None:
    """Validate all known locked financial values before they enter the ledger."""

    values: list[tuple[str, object, PrecisionFamily]] = []
    if account.cash_known is True:
        values.append(("account.current_cash", account.current_cash, "money"))
    if position is not None:
        if position.available_quantity_known is True:
            values.append(("position.available_quantity", position.available_quantity, "quantity"))
        if position.valuation_known is True:
            values.extend(
                (
                    ("position.quantity", position.quantity, "quantity"),
                    ("position.total_cost", position.total_cost, "money"),
                    ("position.market_value", position.market_value, "money"),
                    ("position.current_price", position.current_price, "price"),
                    ("position.avg_cost", position.avg_cost, "price"),
                )
            )
    values.extend(("pending_trade.quantity", row.quantity, "quantity") for row in pending_rows)
    require_sqlite_values(values=tuple(values), using=using)


def validate_reservation_storage_text(intent: SimulatedTradeIntent) -> None:
    """Reject identity values wider than the existing reservation columns."""

    if (
        len(intent.security_id) > 64
        or len(intent.asset_code) > 20
        or len(intent.asset_name) > 100
        or len(intent.asset_type) > 20
        or len(intent.market) > 20
        or len(intent.board) > 20
    ):
        raise SimulatedTradeExecutionBlocked(
            "simulated order identity exceeds reservation storage dimensions",
            code="ORDER_RESERVATION_REQUEST_INVALID",
        )


def validate_reservation_owner_row(
    *, row: SimulatedOrderReservationModel, account: SimulatedAccountModel, user_id: int
) -> None:
    """Reject a reservation whose account or owner changed after the request."""

    if (
        row.account_id != account.pk
        or row.owner_user_id != user_id
        or account.user_id != user_id
        or account.account_type != "simulated"
    ):
        raise SimulatedTradeAccountScopeUnavailable()


def build_locked_tax_aware_reservation_book(
    *,
    account: SimulatedAccountModel,
    position: PositionModel | None,
    active_rows: list[SimulatedOrderReservationModel],
    target: SimulatedOrderReservationModel | None,
    security_id: str,
    asset_code: str,
    using: str,
) -> OrderReservationBook:
    """Join verified debt with the locked cash book without changing gross cash or holds."""
    if type(account.user_id) is not int:
        raise SimulatedTradeAccountScopeUnavailable()
    tax_cash_unavailable: Decimal | None
    try:
        tax_cash_unavailable = read_locked_corporate_action_tax_payable(
            account=account, using=using
        )
    except BusinessLogicError as error:
        if error.code != "TAX_ASSESSMENT_NOT_APPLIED":
            raise
        tax_cash_unavailable = None
    return current_order_reservation_book(
        account=account,
        owner_user_id=account.user_id,
        position=position,
        active_rows=active_rows,
        target=target,
        security_id=security_id,
        asset_code=asset_code,
        tax_cash_unavailable=tax_cash_unavailable,
    )
