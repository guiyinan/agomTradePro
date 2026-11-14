"""Exact validation and persistence helpers for the locked reservation repository."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import cast

from django.utils import timezone

from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    TaxCashCoverageSnapshot,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.domain.execution_current_reference import SettlementExecutionPlanV3
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_identity import SettlementExecutionPlanV2
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    TradeFeeBreakdown,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationBook,
    OrderReservationRequest,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    JSONValue,
    current_order_reservation_book,
    fee_policy_from_snapshot,
    snapshot_digest,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_sqlite_precision import (
    PrecisionFamily,
    require_sqlite_values,
)


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
    tax_coverage: TaxCashCoverageSnapshot | None = None,
) -> OrderReservationBook:
    """Publish spendable cash only with independently complete current tax coverage.

    Historical retry and cancellation do not need current source access and may
    retain an unknown spendable balance while returning their original result.
    """
    if type(account.user_id) is not int:
        raise SimulatedTradeAccountScopeUnavailable()
    tax_cash_unavailable: Decimal | None = None
    if tax_coverage is not None:
        tax_coverage.verify_for(tax_coverage.query, as_of=timezone.now())
        if (
            tax_coverage.query.physical_account_id != account.pk
            or tax_coverage.query.owner_user_id != account.user_id
        ):
            raise SimulatedTradeAccountScopeUnavailable()
        tax_cash_unavailable = tax_coverage.tax_cash_unavailable
    del using
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


def persist_order_reservation_model(
    *,
    using: str,
    validate_values: Callable[[tuple[tuple[str, object, PrecisionFamily], ...]], None],
    account: SimulatedAccountModel,
    intent: SimulatedTradeIntent,
    reservation: OrderReservation,
    fee_policy: SimulatedFeePolicyV2,
    fee_breakdown: TradeFeeBreakdown,
    plan_snapshot: dict[str, JSONValue],
    book_cash: Decimal | None,
    sellable_shares: Decimal | None,
    source_snapshot_at: datetime,
    plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
) -> SimulatedOrderReservationModel:
    """Persist prepared fields inside the caller-owned, already locked transaction."""

    validate_reservation_storage_text(intent)
    if (
        type(account.pk) is not int
        or type(account.user_id) is not int
        or account.pk != intent.account_id
        or account.user_id != intent.user_id
    ):
        raise SimulatedTradeAccountScopeUnavailable()
    schedule = fee_policy.fee_schedule_v1
    validate_values(
        (
            ("quantity", reservation.quantity, "quantity"),
            ("limit_price", reservation.limit_price, "price"),
            ("notional", reservation.notional, "money"),
            ("fee_estimate", reservation.fee_estimate, "money"),
            ("fee_budget", reservation.fee_budget, "money"),
            ("commission_estimate", fee_breakdown.commission, "money"),
            ("transfer_fee_estimate", fee_breakdown.transfer_fee, "money"),
            ("stamp_duty_estimate", fee_breakdown.stamp_duty, "money"),
            ("slippage_estimate", fee_breakdown.slippage, "money"),
            ("cash_reserved", reservation.cash_reserved, "money"),
            ("shares_reserved", reservation.shares_reserved, "quantity"),
            ("filled_quantity", reservation.filled_quantity, "quantity"),
            ("cash_consumed", reservation.cash_consumed, "money"),
            ("shares_consumed", reservation.shares_consumed, "quantity"),
            ("cash_released", reservation.cash_released, "money"),
            ("shares_released", reservation.shares_released, "quantity"),
            ("source_book_cash", book_cash, "money"),
            ("source_sellable_quantity", sellable_shares, "quantity"),
        )
    )
    row = SimulatedOrderReservationModel(
        account=account,
        owner_user_id=intent.user_id,
        idempotency_key=intent.idempotency_key,
        intent_payload_hash=intent.request_payload_hash,
        reservation_request_hash=reservation.identity.request_payload_hash,
        security_id=intent.security_id,
        asset_code=intent.asset_code,
        asset_name=intent.asset_name,
        side=reservation.side.value,
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        quantity=reservation.quantity,
        limit_price=reservation.limit_price,
        notional=reservation.notional,
        fee_estimate=reservation.fee_estimate,
        fee_budget=reservation.fee_budget,
        commission_estimate=fee_breakdown.commission,
        transfer_fee_estimate=fee_breakdown.transfer_fee,
        stamp_duty_estimate=fee_breakdown.stamp_duty,
        slippage_estimate=fee_breakdown.slippage,
        cash_reserved=reservation.cash_reserved,
        shares_reserved=reservation.shares_reserved,
        filled_quantity=reservation.filled_quantity,
        cash_consumed=reservation.cash_consumed,
        shares_consumed=reservation.shares_consumed,
        cash_released=reservation.cash_released,
        shares_released=reservation.shares_released,
        fee_policy_id=fee_policy.policy_id,
        fee_policy_version=fee_policy.policy_version,
        fee_config_id=schedule.config_id,
        fee_policy_hash=fee_policy.content_hash,
        plan_snapshot_version=1,
        plan_snapshot=cast(dict[str, object], plan_snapshot),
        plan_snapshot_hash=snapshot_digest(plan_snapshot),
        source_book_cash=book_cash,
        source_sellable_quantity=sellable_shares,
        source_snapshot_at=source_snapshot_at,
        market_session=plan.market_session,
        settlement_lag_sessions=plan.settlement_lag_sessions,
        settlement_release_date=plan.settlement_release_date,
        reserved_at=reservation.reserved_at,
        status=reservation.status.value,
        cancelled_at=None,
    )
    row.save(using=using, force_insert=True)
    if type(row.pk) is not int or row.pk <= 0:
        raise SimulatedTradeExecutionBlocked(
            "database did not return the new reservation identity",
            code="ORDER_RESERVATION_STORAGE_UNKNOWN",
        )
    row.refresh_from_db(using=using)
    return row
