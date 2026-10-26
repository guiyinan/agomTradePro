"""Reconcile a locked account snapshot with current preview valuation evidence."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from apps.account.application.market_price_contracts import MarketPriceResult
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreviewItem,
)
from apps.simulated_trading.application.rebalance_preview_valuation import (
    _decimal_value,
    _known_cash,
    _normalized_code,
    _price_decimal,
)
from apps.simulated_trading.application.rebalance_resource_snapshot import (
    ActiveRebalanceReservation,
    RebalanceResourceSnapshot,
)
from apps.simulated_trading.domain.entities import Position, SimulatedAccount
from apps.simulated_trading.domain.rebalance_preview_math import (
    calculate_projected_position_amount,
)


def resource_snapshot_matches(
    *,
    requested_account: SimulatedAccount,
    requested_positions: tuple[Position, ...],
    snapshot: RebalanceResourceSnapshot,
) -> bool:
    """Require the earlier inspection to describe the locked ledger snapshot."""

    if type(requested_account) is not SimulatedAccount or requested_account != snapshot.account:
        return False
    requested_by_code: dict[str, Position] = {}
    snapshot_by_code: dict[str, Position] = {}
    for destination, positions in (
        (requested_by_code, requested_positions),
        (snapshot_by_code, snapshot.positions),
    ):
        for position in positions:
            if type(position) is not Position:
                return False
            code = _normalized_code(position.asset_code)
            if code is None or code in destination:
                return False
            destination[code] = position
    return requested_by_code == snapshot_by_code


def snapshot_cash_values(
    *,
    account: SimulatedAccount,
    active_reservations: tuple[ActiveRebalanceReservation, ...],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Separate ledger cash, every active cash hold, and cash still unreserved."""

    ledger_cash = _known_cash(account)
    reserved_cash = sum(
        (row.remaining_cash for row in active_reservations),
        Decimal("0.00"),
    )
    if ledger_cash is None or reserved_cash > ledger_cash:
        return ledger_cash, reserved_cash, None
    return ledger_cash, reserved_cash, ledger_cash - reserved_cash


def active_buy_notional_for_asset(
    *,
    asset_code: str,
    active_reservations: tuple[ActiveRebalanceReservation, ...],
) -> Decimal | None:
    """Sum only provable active BUY notional for one normalized asset code."""

    normalized_asset_code = _normalized_code(asset_code)
    if normalized_asset_code is None:
        return None
    total = Decimal("0.00")
    for reservation in active_reservations:
        if type(reservation) is not ActiveRebalanceReservation:
            return None
        if (
            reservation.side != "buy"
            or _normalized_code(reservation.asset_code) != normalized_asset_code
        ):
            continue
        if reservation.remaining_buy_notional is None:
            return None
        try:
            total += reservation.remaining_buy_notional
        except (ArithmeticError, InvalidOperation):
            return None
    return total


def projected_position_amount(
    *,
    positions: tuple[Position, ...],
    targets: dict[str, Mapping[str, object]],
    items: list[RebalancePlanPreviewItem],
    prices: dict[str, MarketPriceResult | None],
    portfolio_value: Decimal | None,
    active_reservations: tuple[ActiveRebalanceReservation, ...],
) -> Decimal | None:
    """Sum held value, accepted BUY remainder, and each requested BUY amount.

    Held shares remain exposed until a sale is actually settled. Active BUY
    exposure uses only its remaining accepted-limit notional; fee reserves and
    prior fills are excluded because they are cash or already-held assets.
    """

    if (
        type(portfolio_value) is not Decimal
        or not portfolio_value.is_finite()
        or portfolio_value <= 0
    ):
        return None
    item_by_code: dict[str, RebalancePlanPreviewItem] = {}
    for item in items:
        if item.scope != "asset":
            continue
        code = _normalized_code(item.asset_code)
        if code is None or code in item_by_code:
            return None
        item_by_code[code] = item
    if any(_normalized_code(code) not in item_by_code for code in targets):
        return None

    amounts: list[Decimal | None] = []
    for reservation in active_reservations:
        if type(reservation) is not ActiveRebalanceReservation:
            return None
        if reservation.side == "buy":
            amounts.append(reservation.remaining_buy_notional)

    seen_codes: set[str] = set()
    for position in positions:
        code = _normalized_code(position.asset_code)
        if code is None or code in seen_codes:
            return None
        seen_codes.add(code)
        position_item = item_by_code.get(code)
        if position_item is not None:
            amounts.append(position_item.current_amount)
            continue
        quantity = _decimal_value(position.quantity)
        price = _price_decimal(prices.get(code))
        if quantity is None or quantity < 0:
            return None
        amounts.append(
            Decimal("0") if quantity == 0 else quantity * price if price is not None else None
        )

    for item in items:
        if item.scope == "asset" and item.action == "blocked" and item.status == "blocked":
            if item.target_mode in {"strategy_rule", "user_target_difference"}:
                return None
        if item.scope == "asset" and item.action == "buy":
            amounts.append(item.suggested_amount)
    return calculate_projected_position_amount(tuple(amounts))


def projected_buy_position_amount_by_asset(
    *,
    items: list[RebalancePlanPreviewItem],
    active_reservations: tuple[ActiveRebalanceReservation, ...],
) -> dict[str, Decimal]:
    """Project each BUY's held, reserved, and requested gross exposure amount.

    An asset is omitted when any of its component amounts is unknown. The
    caller must convert known amounts using the same post-fee equity that the
    total-position risk observation uses. This function never substitutes
    cash holds, fees, slippage, or a default zero.
    """

    projections: dict[str, Decimal] = {}
    seen_codes: set[str] = set()
    for item in items:
        if item.scope != "asset" or item.action != "buy":
            continue
        code = _normalized_code(item.asset_code)
        if code is None or code in seen_codes:
            if code is not None:
                projections.pop(code, None)
                seen_codes.add(code)
            continue
        seen_codes.add(code)
        active_notional = active_buy_notional_for_asset(
            asset_code=code,
            active_reservations=active_reservations,
        )
        projected_amount = calculate_projected_position_amount(
            (item.current_amount, active_notional, item.suggested_amount)
        )
        if projected_amount is None:
            continue
        projections[code] = projected_amount
    return projections


__all__: tuple[str, ...] = (
    "active_buy_notional_for_asset",
    "projected_buy_position_amount_by_asset",
    "projected_position_amount",
    "resource_snapshot_matches",
    "snapshot_cash_values",
)
