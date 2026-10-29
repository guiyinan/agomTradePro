"""Exact settlement port contracts for the stock-selection backtest engine.

The engine may optionally delegate one candidate trade to the ordinary
simulated settlement path through these contracts. This module is stdlib-only
and never imports the providing application.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from enum import Enum
from typing import Protocol

_CENT_QUANTUM = Decimal("0.01")
_VERIFY_PRECISION = 80


class StockTradeSettlementContractError(ValueError):
    """Raised when an injected settlement quote violates its exact contract."""


class StockTradeSide(Enum):
    """Trade sides understood by the stock-selection backtest engine."""

    BUY = "buy"
    SELL = "sell"


class SettlementSlippagePolicy(Enum):
    """Declare where slippage is charged so it is never applied twice."""

    FEE_COMPONENT = "fee_component"
    ALREADY_IN_PRICE = "already_in_price"


@dataclass(frozen=True)
class StockTradeSettlementRequest:
    """One exact candidate trade handed to the injected settlement port."""

    stock_code: str
    side: StockTradeSide
    quantity: int
    price: Decimal
    trade_date: date
    available_cash: Decimal


@dataclass(frozen=True)
class StockTradeSettlementQuote:
    """One exact settled execution returned by the injected settlement port."""

    stock_code: str
    side: StockTradeSide
    executed_quantity: int
    executed_price: Decimal
    commission: Decimal
    transfer_fee: Decimal
    stamp_duty: Decimal
    slippage: Decimal
    amount: Decimal
    cash_delta: Decimal
    trade_date: date
    market_session: date
    release_session: date | None


class StockTradeSettlementPort(Protocol):
    """Quote one exact backtest trade through the ordinary settlement path."""

    def quote(self, request: StockTradeSettlementRequest) -> StockTradeSettlementQuote:
        """Return one exact quote for the request or raise a typed block."""
        ...


def _require_finite_nonnegative(value: Decimal, field_name: str) -> None:
    if type(value) is not Decimal or not value.is_finite() or value < 0:
        raise StockTradeSettlementContractError(
            f"{field_name} must be a finite nonnegative Decimal"
        )


def _require_finite_positive(value: Decimal, field_name: str) -> None:
    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        raise StockTradeSettlementContractError(f"{field_name} must be a finite positive Decimal")


def _require_cent_valued(value: Decimal, field_name: str) -> None:
    if value != value.quantize(_CENT_QUANTUM):
        raise StockTradeSettlementContractError(
            f"{field_name} must be representable in exact ledger cents"
        )


def _validate_request(request: StockTradeSettlementRequest) -> None:
    """Reject a malformed candidate request before any quote is trusted."""

    if type(request) is not StockTradeSettlementRequest:
        raise StockTradeSettlementContractError("settlement request has an invalid contract type")
    code = request.stock_code
    if (
        type(code) is not str
        or not code
        or code.strip() != code
        or any(character.isspace() for character in code)
    ):
        raise StockTradeSettlementContractError("stock_code must be a bounded canonical token")
    if type(request.side) is not StockTradeSide:
        raise StockTradeSettlementContractError("side must be an explicit StockTradeSide")
    if type(request.quantity) is not int or request.quantity <= 0:
        raise StockTradeSettlementContractError("quantity must be a positive exact integer")
    if type(request.trade_date) is not date:
        raise StockTradeSettlementContractError("trade_date must be an exact date")
    _require_finite_positive(request.price, "price")
    _require_finite_nonnegative(request.available_cash, "available_cash")
    _require_cent_valued(request.available_cash, "available_cash")


def validate_settlement_quote(
    *,
    request: StockTradeSettlementRequest,
    quote: StockTradeSettlementQuote,
    slippage_policy: SettlementSlippagePolicy,
) -> None:
    """Reject an injected quote that does not exactly honor its request.

    Identity, quantity, price, notional, fee arithmetic, cash arithmetic, and
    session fields must match the request exactly; partial quantities or
    rewritten fields are never applied silently. All verification arithmetic
    runs under a bounded local context, independent of ambient precision.
    """

    if type(slippage_policy) is not SettlementSlippagePolicy:
        raise StockTradeSettlementContractError(
            "slippage policy must be an explicit SettlementSlippagePolicy"
        )
    if type(quote) is not StockTradeSettlementQuote:
        raise StockTradeSettlementContractError("settlement quote has an invalid contract type")
    with localcontext() as context:
        context.prec = _VERIFY_PRECISION
        _validate_request(request)
        if quote.stock_code != request.stock_code:
            raise StockTradeSettlementContractError(
                "settlement quote stock_code differs from the request"
            )
        if quote.side is not request.side:
            raise StockTradeSettlementContractError(
                "settlement quote side differs from the request"
            )
        if quote.trade_date != request.trade_date:
            raise StockTradeSettlementContractError(
                "settlement quote trade_date differs from the request"
            )
        if type(quote.executed_quantity) is not int or quote.executed_quantity != request.quantity:
            raise StockTradeSettlementContractError(
                "settlement quote quantity differs from the exact request"
            )
        _require_finite_positive(quote.executed_price, "executed_price")
        if quote.executed_price != request.price:
            raise StockTradeSettlementContractError(
                "settlement quote price differs from the submitted price"
            )
        fee_components: tuple[tuple[str, Decimal], ...] = (
            ("commission", quote.commission),
            ("transfer_fee", quote.transfer_fee),
            ("stamp_duty", quote.stamp_duty),
            ("slippage", quote.slippage),
        )
        for field_name, component in fee_components:
            _require_finite_nonnegative(component, field_name)
            _require_cent_valued(component, field_name)
        _require_finite_positive(quote.amount, "amount")
        _require_cent_valued(quote.amount, "amount")
        expected_amount = (Decimal(quote.executed_quantity) * quote.executed_price).quantize(
            _CENT_QUANTUM,
            rounding=ROUND_HALF_EVEN,
        )
        if quote.amount != expected_amount:
            raise StockTradeSettlementContractError(
                "settlement quote amount differs from quantity times execution price"
            )
        if type(quote.cash_delta) is not Decimal or not quote.cash_delta.is_finite():
            raise StockTradeSettlementContractError("cash_delta must be a finite Decimal")
        _require_cent_valued(quote.cash_delta, "cash_delta")
        if (
            slippage_policy is SettlementSlippagePolicy.ALREADY_IN_PRICE
            and quote.slippage != Decimal("0")
        ):
            raise StockTradeSettlementContractError(
                "in-price slippage policy forbids a nonzero slippage fee component"
            )
        total_fee = quote.commission + quote.transfer_fee + quote.stamp_duty + quote.slippage
        expected_cash_delta = (
            -(quote.amount + total_fee)
            if request.side is StockTradeSide.BUY
            else quote.amount - total_fee
        )
        if quote.cash_delta != expected_cash_delta:
            raise StockTradeSettlementContractError(
                "settlement quote cash_delta differs from amount and fee components"
            )
        if type(quote.market_session) is not date:
            raise StockTradeSettlementContractError("market_session must be an exact date")
        if quote.market_session != request.trade_date:
            raise StockTradeSettlementContractError(
                "market_session differs from the requested exchange trade date"
            )
        if request.side is StockTradeSide.BUY:
            if quote.release_session is None or type(quote.release_session) is not date:
                raise StockTradeSettlementContractError(
                    "BUY quote requires an exact release session"
                )
            if quote.release_session < quote.market_session:
                raise StockTradeSettlementContractError(
                    "release session precedes its market session"
                )
        elif quote.release_session is not None:
            raise StockTradeSettlementContractError("SELL quote cannot carry a buy release session")
