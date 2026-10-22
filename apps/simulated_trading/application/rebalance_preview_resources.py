"""Reconcile a locked account snapshot with current preview valuation evidence."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

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


def projected_position_amount(
    *,
    positions: tuple[Position, ...],
    targets: dict[str, Mapping[str, object]],
    items: list[RebalancePlanPreviewItem],
    prices: dict[str, MarketPriceResult | None],
    portfolio_value: Decimal | None,
) -> Decimal | None:
    """Sum target and unchanged holdings from the same quote snapshot."""

    if portfolio_value is None:
        return None
    item_by_code = {
        code: item for item in items if (code := _normalized_code(item.asset_code)) is not None
    }
    amounts: list[Decimal | None] = []
    seen_codes: set[str] = set()
    for position in positions:
        code = _normalized_code(position.asset_code)
        if code is None or code in seen_codes:
            return None
        seen_codes.add(code)
        if code in targets:
            item = item_by_code.get(code)
            amounts.append(item.target_amount if item is not None else None)
            continue
        quantity = _decimal_value(position.quantity)
        price = _price_decimal(prices.get(code))
        if quantity is None or quantity < 0:
            return None
        amounts.append(
            Decimal("0") if quantity == 0 else quantity * price if price is not None else None
        )
    for code in targets:
        if code not in seen_codes:
            item = item_by_code.get(code)
            amounts.append(item.target_amount if item is not None else None)
    return calculate_projected_position_amount(tuple(amounts))


__all__: tuple[str, ...] = (
    "projected_position_amount",
    "resource_snapshot_matches",
    "snapshot_cash_values",
)
