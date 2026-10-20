"""Validate the complete typed economics history for one simulated order."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    TradeFeeBreakdown,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationError,
    OrderReservationRequest,
    OrderReservationStatus,
)
from apps.simulated_trading.domain.order_reservation_fill import (
    OrderReservationFillAccrual,
    OrderReservationFillEconomics,
    _calculate_fill_accrual,
)

_ZERO_MONEY = Decimal("0.00")
_ZERO_SHARES = Decimal("0.000000")


def _need(condition: bool, code: str) -> None:
    """Raise the stable reservation-domain error for a failed chain invariant."""

    if not condition:
        raise OrderReservationError(code)


@dataclass(frozen=True, slots=True)
class OrderReservationFillChainEntry:
    """Pair a persisted one-based receipt sequence with its typed economics."""

    fill_sequence: int
    economics: OrderReservationFillEconomics

    def __post_init__(self) -> None:
        """Reject bool/nonpositive sequence values and invalid economics objects."""

        _need(
            type(self.fill_sequence) is int and self.fill_sequence > 0,
            "FILL_CHAIN_SEQUENCE_INVALID",
        )
        _need(
            type(self.economics) is OrderReservationFillEconomics,
            "FILL_CHAIN_ECONOMICS_INVALID",
        )
        self.economics.__post_init__()


def _validate_parent(
    *,
    intent: SimulatedTradeIntent,
    stored_intent_payload_hash: str,
    reservation: OrderReservation,
    fee_policy: SimulatedFeePolicyV2,
) -> None:
    """Bind the chain inputs to the immutable parent request and frozen FeeV2."""

    _need(type(intent) is SimulatedTradeIntent, "FILL_CHAIN_INTENT_INVALID")
    intent.__post_init__()
    _need(type(reservation) is OrderReservation, "FILL_CHAIN_RESERVATION_INVALID")
    reservation.__post_init__()
    _need(type(fee_policy) is SimulatedFeePolicyV2, "FILL_CHAIN_FEE_POLICY_INVALID")
    fee_policy.__post_init__()
    _need(
        type(stored_intent_payload_hash) is str
        and stored_intent_payload_hash == intent.request_payload_hash,
        "FILL_CHAIN_INTENT_HASH_MISMATCH",
    )
    fee_policy.validate_at(reservation.reserved_at)

    expected_request = OrderReservationRequest(
        account_id=intent.account_id,
        security_id=intent.security_id,
        idempotency_key=intent.idempotency_key,
        side=intent.side,
        quantity=intent.quantity,
        limit_price=intent.price,
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        fee_budget=reservation.fee_budget,
    )
    _need(
        reservation.identity == expected_request.identity(fee_policy_hash=fee_policy.content_hash)
        and reservation.side is expected_request.side
        and reservation.quantity == expected_request.quantity
        and reservation.limit_price == expected_request.limit_price
        and reservation.notional == expected_request.notional,
        "FILL_CHAIN_RESERVATION_POLICY_MISMATCH",
    )
    expected_estimate = fee_policy.calculate_for(
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        side=intent.side,
        amount=expected_request.notional,
        as_of=reservation.reserved_at,
    )
    _need(
        reservation.fee_estimate == expected_estimate.total_fee,
        "FILL_CHAIN_RESERVATION_FEE_MISMATCH",
    )


def _validate_entry_parent(
    *,
    economics: OrderReservationFillEconomics,
    intent: SimulatedTradeIntent,
    reservation: OrderReservation,
    fee_policy: SimulatedFeePolicyV2,
) -> None:
    """Require every immutable fill request field to match the sealed parent."""

    economics.__post_init__()
    _need(
        economics.reservation_identity == reservation.identity
        and economics.user_id == intent.user_id
        and economics.intent_payload_hash == intent.request_payload_hash
        and economics.fee_policy_hash == fee_policy.content_hash
        and economics.side is intent.side
        and economics.asset_code == intent.asset_code
        and economics.asset_type == intent.asset_type
        and economics.market == intent.market
        and economics.board == intent.board
        and economics.limit_price == reservation.limit_price
        and economics.fill_occurred_at >= reservation.reserved_at,
        "FILL_CHAIN_ECONOMICS_PARENT_MISMATCH",
    )


def validate_order_reservation_fill_chain(
    *,
    intent: SimulatedTradeIntent,
    stored_intent_payload_hash: str,
    reservation: OrderReservation,
    fee_policy: SimulatedFeePolicyV2,
    entries: tuple[OrderReservationFillChainEntry, ...],
) -> OrderReservationFillAccrual:
    """Recompute ordered persisted fill quantity, gross, and FeeV2 accruals.

    ``entries`` must contain the complete reservation history decoded by its
    storage owner and ordered by persisted fill sequence. This validator
    checks only typed financial history; it does not authenticate fill sources,
    read balances, prove a calendar, or apply reservation/ledger mutations.
    Terminal parents are accepted when their complete history matches the
    parent's current filled quantity, so an earlier event can be replayed from
    its validated prefix after later fills or cancellation.
    """

    _validate_parent(
        intent=intent,
        stored_intent_payload_hash=stored_intent_payload_hash,
        reservation=reservation,
        fee_policy=fee_policy,
    )
    _need(type(entries) is tuple, "FILL_CHAIN_ENTRIES_INVALID")
    # A policy's minimum commission is not an accrued fill before the first row.
    expected = OrderReservationFillAccrual(
        fill_count=0,
        cumulative_quantity=_ZERO_SHARES,
        cumulative_gross=_ZERO_MONEY,
        cumulative_fees=TradeFeeBreakdown(
            _ZERO_MONEY,
            _ZERO_MONEY,
            _ZERO_MONEY,
            _ZERO_MONEY,
            _ZERO_MONEY,
        ),
    )

    for expected_sequence, entry in enumerate(entries, start=1):
        _need(
            type(entry) is OrderReservationFillChainEntry,
            "FILL_CHAIN_ENTRY_INVALID",
        )
        entry.__post_init__()
        _need(
            entry.fill_sequence == expected_sequence,
            "FILL_CHAIN_SEQUENCE_INVALID",
        )
        economics = entry.economics
        _validate_entry_parent(
            economics=economics,
            intent=intent,
            reservation=reservation,
            fee_policy=fee_policy,
        )
        _need(economics.prior == expected, "FILL_CHAIN_PRIOR_MISMATCH")
        _need(
            not economics.close_order or expected_sequence == len(entries),
            "FILL_CHAIN_CLOSE_NOT_FINAL",
        )

        gross, cumulative, incremental = _calculate_fill_accrual(
            intent=intent,
            reservation=reservation,
            fee_policy=fee_policy,
            quantity=economics.quantity,
            price=economics.price,
            prior=expected,
        )
        _need(
            cumulative.cumulative_quantity <= reservation.quantity,
            "FILL_CHAIN_EXCEEDS_PARENT_QUANTITY",
        )
        _need(
            economics.gross_amount == gross
            and economics.cumulative_state == cumulative
            and economics.incremental_fees == incremental,
            "FILL_CHAIN_ECONOMICS_MISMATCH",
        )
        expected = cumulative

    _need(
        expected.cumulative_quantity == reservation.filled_quantity,
        "FILL_CHAIN_PARENT_QUANTITY_MISMATCH",
    )
    if entries and entries[-1].economics.close_order:
        expected_terminal = (
            OrderReservationStatus.COMPLETED
            if expected.cumulative_quantity == reservation.quantity
            else OrderReservationStatus.CANCELLED
        )
        _need(
            reservation.status is expected_terminal,
            "FILL_CHAIN_TERMINAL_STATUS_MISMATCH",
        )
    return expected


__all__: tuple[str, ...] = (
    "OrderReservationFillChainEntry",
    "validate_order_reservation_fill_chain",
)
