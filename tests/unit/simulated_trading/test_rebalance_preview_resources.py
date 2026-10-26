"""Focused risk projection tests for active simulated-order reservations."""

from __future__ import annotations

from decimal import Decimal

from apps.simulated_trading.application.rebalance_preview_resources import (
    active_buy_notional_for_asset,
    projected_position_amount,
)
from apps.simulated_trading.application.rebalance_resource_snapshot import (
    ActiveRebalanceReservation,
)


def _projected_amount(
    reservations: tuple[ActiveRebalanceReservation, ...],
) -> Decimal | None:
    """Project an empty holdings/target set plus the supplied locked holds."""

    return projected_position_amount(
        positions=(),
        targets={},
        items=[],
        prices={},
        portfolio_value=Decimal("1000.00"),
        active_reservations=reservations,
    )


def test_projection_adds_only_exact_active_buy_notional_and_never_nets_sell_holds() -> None:
    """A BUY contributes gross exposure; an unfilled SELL cannot release it."""

    projected = _projected_amount(
        (
            ActiveRebalanceReservation(
                reservation_id=1,
                asset_code="600000.SH",
                security_id="fixture:SH:600000.SH",
                side="buy",
                remaining_cash=Decimal("65.50"),
                remaining_shares=Decimal("0.000000"),
                remaining_buy_notional=Decimal("60.00"),
            ),
            ActiveRebalanceReservation(
                reservation_id=2,
                asset_code="000001.SZ",
                security_id="fixture:SZ:000001.SZ",
                side="sell",
                remaining_cash=Decimal("0.00"),
                remaining_shares=Decimal("10.000000"),
                remaining_buy_notional=None,
            ),
        )
    )

    assert projected == Decimal("60.00")


def test_missing_active_buy_notional_keeps_total_exposure_unknown() -> None:
    """A reservation without provable remaining notional cannot pass a cap."""

    projected = _projected_amount(
        (
            ActiveRebalanceReservation(
                reservation_id=3,
                asset_code="600000.SH",
                security_id="fixture:SH:600000.SH",
                side="buy",
                remaining_cash=Decimal("100.00"),
                remaining_shares=Decimal("0.000000"),
                remaining_buy_notional=None,
            ),
        )
    )

    assert projected is None


def test_per_asset_notional_sums_same_symbol_buys_without_using_cash_or_sell_holds() -> None:
    """Only the matching security's remaining BUY notional enters its own cap."""

    reservations = (
        ActiveRebalanceReservation(
            reservation_id=10,
            asset_code="600000.SH",
            security_id="fixture:SH:600000.SH",
            side="buy",
            remaining_cash=Decimal("99.00"),
            remaining_shares=Decimal("0.000000"),
            remaining_buy_notional=Decimal("60.00"),
        ),
        ActiveRebalanceReservation(
            reservation_id=11,
            asset_code="600000.SH",
            security_id="fixture:SH:600000.SH",
            side="buy",
            remaining_cash=Decimal("45.00"),
            remaining_shares=Decimal("0.000000"),
            remaining_buy_notional=Decimal("40.00"),
        ),
        ActiveRebalanceReservation(
            reservation_id=12,
            asset_code="600000.SH",
            security_id="fixture:SH:600000.SH",
            side="sell",
            remaining_cash=Decimal("0.00"),
            remaining_shares=Decimal("5.000000"),
            remaining_buy_notional=None,
        ),
        ActiveRebalanceReservation(
            reservation_id=13,
            asset_code="000001.SZ",
            security_id="fixture:SZ:000001.SZ",
            side="buy",
            remaining_cash=Decimal("500.00"),
            remaining_shares=Decimal("0.000000"),
            remaining_buy_notional=Decimal("500.00"),
        ),
    )

    assert active_buy_notional_for_asset(
        asset_code="600000.sh",
        active_reservations=reservations,
    ) == Decimal("100.00")
    assert active_buy_notional_for_asset(
        asset_code="000001.SZ",
        active_reservations=reservations,
    ) == Decimal("500.00")


def test_unknown_same_symbol_notional_is_scoped_to_that_asset() -> None:
    """A known unrelated order remains usable for its own per-asset cap input."""

    reservations = (
        ActiveRebalanceReservation(
            reservation_id=20,
            asset_code="600000.SH",
            security_id="fixture:SH:600000.SH",
            side="buy",
            remaining_cash=Decimal("100.00"),
            remaining_shares=Decimal("0.000000"),
            remaining_buy_notional=None,
        ),
        ActiveRebalanceReservation(
            reservation_id=21,
            asset_code="000001.SZ",
            security_id="fixture:SZ:000001.SZ",
            side="buy",
            remaining_cash=Decimal("30.00"),
            remaining_shares=Decimal("0.000000"),
            remaining_buy_notional=Decimal("25.00"),
        ),
    )

    assert (
        active_buy_notional_for_asset(
            asset_code="600000.SH",
            active_reservations=reservations,
        )
        is None
    )
    assert active_buy_notional_for_asset(
        asset_code="000001.SZ",
        active_reservations=reservations,
    ) == Decimal("25.00")
