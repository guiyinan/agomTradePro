"""Validate complete persisted V4 fill histories before exposing Trade rows."""

from __future__ import annotations

import logging
from collections import defaultdict

from django.db.models import Q, QuerySet

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
)
from apps.simulated_trading.domain.order_reservation_fill_chain import (
    OrderReservationFillChainEntry,
    validate_order_reservation_fill_chain,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    _intent_from_snapshot,
    decode_order_reservation,
    fee_policy_from_snapshot,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    DecodedOrderReservationFillRow,
    read_order_reservation_fill_row,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedTradeModel,
)

_logger = logging.getLogger(__name__)
_SIBLING_SCOPE_QUERY_CHUNK_SIZE = 100


def validate_v4_trade_history(trade_rows: QuerySet[SimulatedTradeModel]) -> None:
    """Fail closed when any selected V4 Trade has an invalid complete parent chain.

    A receipt FK is authoritative evidence that a selected Trade is fill-backed,
    even if its scalar binding version was downgraded. The selected queryset is
    kept as a database subquery so legacy rows outside its owner/account/date
    scope are neither materialized nor treated as parents. Binding JSON only
    locates sibling rows within exact account/reservation pairs; every receipt
    and Trade is decoded before the Domain chain validator recomputes FeeV2.
    Legacy V0–V3 rows without a receipt remain on their existing read path.
    """

    scoped_trade_ids = trade_rows.values("pk")
    receipt_backed_ids = (
        SimulatedOrderFillReceiptModel._default_manager.using("default")
        .filter(trade_id__in=scoped_trade_ids)
        .values("trade_id")
    )
    candidate_rows = list(
        SimulatedTradeModel._default_manager.using("default")
        .filter(pk__in=scoped_trade_ids)
        .filter(Q(settlement_plan_binding_version=4) | Q(pk__in=receipt_backed_ids))
        .select_related("account")
        .order_by("pk")
    )
    if not candidate_rows:
        return

    selected_v4_ids: set[int] = set()
    selected_by_id: dict[int, SimulatedTradeModel] = {}
    for trade in candidate_rows:
        if type(trade) is not SimulatedTradeModel:
            raise _history_error("trade query returned an unexpected model type")
        trade_id = trade.pk
        account_id = trade.account_id
        if type(trade_id) is not int or trade_id <= 0:
            raise _history_error("receipt-backed or V4 Trade id is invalid")
        if type(account_id) is not int or account_id <= 0:
            raise _history_error("receipt-backed or V4 Trade account id is invalid")
        if trade_id in selected_by_id:
            raise _history_error("selected Trade scope contains a duplicate id")
        if trade.settlement_plan_binding_version != 4:
            raise _history_error("a receipt-backed Trade is not V4")
        selected_v4_ids.add(trade_id)
        selected_by_id[trade_id] = trade
    if not selected_v4_ids:
        return

    initial_receipts = list(
        SimulatedOrderFillReceiptModel._default_manager.using("default")
        .filter(trade_id__in=selected_v4_ids)
        .select_related("reservation__account", "trade__account")
        .order_by("reservation_id", "fill_sequence", "pk")
    )
    initial_by_trade: dict[int, SimulatedOrderFillReceiptModel] = {}
    decoded_initial: dict[int, DecodedOrderReservationFillRow] = {}
    for receipt in initial_receipts:
        trade_id = receipt.trade_id
        if trade_id in initial_by_trade:
            raise _history_error("V4 Trade has more than one fill receipt")
        initial_by_trade[trade_id] = receipt
        decoded_initial[trade_id] = _decode_receipt(
            receipt,
            trade_row=selected_by_id[trade_id],
        )
    if set(initial_by_trade) != selected_v4_ids:
        raise _history_error("selected V4 Trade is missing its exact fill receipt")

    reservation_ids = {row.reservation_id for row in decoded_initial.values()}
    receipts = list(
        SimulatedOrderFillReceiptModel._default_manager.using("default")
        .filter(reservation_id__in=reservation_ids)
        .select_related("reservation__account", "trade__account")
        .order_by("reservation_id", "fill_sequence", "pk")
    )
    # Locate sibling Trades from the V4 JSON locator, then validate each against
    # its actual receipt FK below. A tampered/missing receipt cannot be trusted
    # merely because a JSON locator happens to point at the selected parent.
    receipt_trade_ids: set[int] = set()
    grouped: dict[int, list[DecodedOrderReservationFillRow]] = defaultdict(list)
    reservation_by_id: dict[int, SimulatedOrderReservationModel] = {}
    for receipt in receipts:
        decoded = decoded_initial.get(receipt.trade_id)
        if decoded is None:
            if receipt.trade.settlement_plan_binding_version != 4:
                raise _history_error("a parent receipt links to a non-V4 Trade")
            decoded = _decode_receipt(receipt)
        if decoded.reservation_id != receipt.reservation_id:
            raise _history_error("decoded receipt parent differs from its foreign key")
        receipt_trade_ids.add(receipt.trade_id)
        grouped[decoded.reservation_id].append(decoded)
        reservation_by_id[decoded.reservation_id] = receipt.reservation

    sibling_scopes: list[tuple[int, int]] = []
    for reservation_id, reservation_row in reservation_by_id.items():
        account_id = reservation_row.account_id
        if type(account_id) is not int or account_id <= 0:
            raise _history_error("fill reservation account id is invalid")
        if type(reservation_id) is not int or reservation_id <= 0:
            raise _history_error("fill reservation id is invalid")
        sibling_scopes.append((account_id, reservation_id))
    if not sibling_scopes:
        raise _history_error("V4 fill history has no exact account/reservation scope")
    sibling_trade_ids = _sibling_v4_trade_ids(tuple(sibling_scopes))
    if sibling_trade_ids != receipt_trade_ids:
        raise _history_error("V4 Trade and receipt membership differs for a reservation")

    for reservation_id, entries in grouped.items():
        reservation_row = reservation_by_id[reservation_id]
        try:
            plan_snapshot = validated_plan_snapshot(reservation_row)
            intent = _intent_from_snapshot(plan_snapshot)
            reservation = decode_order_reservation(reservation_row)
            fee_policy = fee_policy_from_snapshot(plan_snapshot)
            ordered_entries = tuple(
                OrderReservationFillChainEntry(
                    fill_sequence=entry.fill_sequence,
                    economics=entry.economics,
                )
                for entry in sorted(entries, key=lambda value: value.fill_sequence)
            )
            validate_order_reservation_fill_chain(
                intent=intent,
                stored_intent_payload_hash=reservation_row.intent_payload_hash,
                reservation=reservation,
                fee_policy=fee_policy,
                entries=ordered_entries,
            )
        except (SimulatedTradeExecutionBlocked, SimulatedSettlementContractError) as error:
            raise _history_error(
                "persisted V4 fill parent failed strict validation",
                internal_reason=str(error),
            ) from error


def _sibling_v4_trade_ids(
    parent_scopes: tuple[tuple[int, int], ...],
) -> set[int]:
    """Find V4 Trades whose exact account/reservation pair is a validated parent."""

    if type(parent_scopes) is not tuple or not parent_scopes:
        raise _history_error("V4 sibling parent scopes are invalid")
    unique_scopes: set[tuple[int, int]] = set()
    for scope in parent_scopes:
        if type(scope) is not tuple or len(scope) != 2:
            raise _history_error("V4 sibling parent scope is malformed")
        account_id, reservation_id = scope
        if type(account_id) is not int or account_id <= 0:
            raise _history_error("V4 sibling account id is invalid")
        if type(reservation_id) is not int or reservation_id <= 0:
            raise _history_error("V4 sibling reservation id is invalid")
        unique_scopes.add((account_id, reservation_id))

    ordered_scopes = tuple(sorted(unique_scopes))
    sibling_trade_ids: set[int] = set()
    for offset in range(0, len(ordered_scopes), _SIBLING_SCOPE_QUERY_CHUNK_SIZE):
        chunk = ordered_scopes[offset : offset + _SIBLING_SCOPE_QUERY_CHUNK_SIZE]
        sibling_scope: Q | None = None
        for account_id, reservation_id in chunk:
            exact_scope = Q(
                account_id=account_id,
                settlement_plan_binding_payload__reservation_id=reservation_id,
            )
            sibling_scope = exact_scope if sibling_scope is None else sibling_scope | exact_scope
        if sibling_scope is None:
            raise _history_error("V4 sibling parent scope chunk is empty")
        matching_trade_ids = (
            SimulatedTradeModel._default_manager.using("default")
            .filter(settlement_plan_binding_version=4)
            .filter(sibling_scope)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        for trade_id in matching_trade_ids:
            if type(trade_id) is not int or trade_id <= 0:
                raise _history_error("V4 sibling Trade id is invalid")
            sibling_trade_ids.add(trade_id)
    return sibling_trade_ids


def _decode_receipt(
    receipt: SimulatedOrderFillReceiptModel,
    *,
    trade_row: SimulatedTradeModel | None = None,
) -> DecodedOrderReservationFillRow:
    """Decode a receipt against the exact selected Trade when one was supplied."""

    reservation = receipt.reservation
    linked_trade = receipt.trade
    selected_trade = linked_trade if trade_row is None else trade_row
    account = reservation.account
    owner_id = account.user_id
    trade_owner_id = linked_trade.account.user_id
    if (
        reservation.account_id != linked_trade.account_id
        or account.account_type != "simulated"
        or type(owner_id) is not int
        or owner_id <= 0
        or reservation.owner_user_id != owner_id
        or linked_trade.account.account_type != "simulated"
        or type(trade_owner_id) is not int
        or trade_owner_id != owner_id
    ):
        raise _history_error("V4 fill receipt is outside its simulated owner/account")
    try:
        return read_order_reservation_fill_row(
            reservation_row=reservation,
            receipt_row=receipt,
            trade_row=selected_trade,
        )
    except (SimulatedTradeExecutionBlocked, SimulatedSettlementContractError) as error:
        raise _history_error(
            "V4 fill receipt failed strict row validation",
            internal_reason=str(error),
        ) from error


def _history_error(
    message: str,
    *,
    internal_reason: str | None = None,
) -> SimulatedTradeExecutionBlocked:
    """Log an internal validation reason and return a stable user-facing error."""

    _logger.error(
        "Persisted simulated fill history validation blocked: %s",
        internal_reason or message,
        extra={"code": "ORDER_RESERVATION_FILL_HISTORY_INVALID"},
    )
    return SimulatedTradeExecutionBlocked(
        "成交记录校验未通过，请先核对该账户的成交记录",
        code="ORDER_RESERVATION_FILL_HISTORY_INVALID",
    )


__all__: tuple[str, ...] = ("validate_v4_trade_history",)
