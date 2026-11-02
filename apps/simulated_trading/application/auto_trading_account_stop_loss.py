"""Qualified local-market account stop-loss decision and execution orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable

from apps.simulated_trading.application.execution_settlement_uow import (
    AutomaticTradeStopLossMarketObservation,
)
from apps.simulated_trading.application.ports import PositionExitAdvice
from apps.simulated_trading.domain.account_stop_loss import evaluate_account_stop_loss
from apps.simulated_trading.domain.entities import Position, SimulatedAccount, SimulatedTrade


@runtime_checkable
class AccountStopLossSellExecutor(Protocol):
    """Expose the source-qualified account stop-loss route without changing other SELLs."""

    def capture_stop_loss_market(
        self,
        *,
        account_id: int,
        asset_code: str,
        execution_date: date | None,
    ) -> AutomaticTradeStopLossMarketObservation:
        """Read one explicit local-simulation quote for the exact held equity."""

    def execute_account_stop_loss(
        self,
        *,
        account_id: int,
        asset_code: str,
        quantity: int,
        reason: str,
        execution_date: date | None,
        observation: AutomaticTradeStopLossMarketObservation,
    ) -> SimulatedTrade:
        """Apply a stop-loss SELL at the exact quote through the normal ledger UoW."""


@dataclass(frozen=True, slots=True)
class AccountStopLossRouteResult:
    """Describe whether the local account-stop-loss route handled one position."""

    handled: bool
    trade: SimulatedTrade | None = None
    price: Decimal | None = None
    quantity: int | None = None
    block_code: str | None = None
    error: Exception | None = None

    def __post_init__(self) -> None:
        """Keep one result to an exact no-op, block, error, or confirmed trade shape."""

        if type(self.handled) is not bool:
            raise ValueError("handled must be an exact boolean")
        if not self.handled:
            if any(
                value is not None
                for value in (self.trade, self.price, self.quantity, self.block_code, self.error)
            ):
                raise ValueError("unhandled stop-loss result cannot carry an outcome")
            return
        outcomes = (
            self.trade is not None,
            self.block_code is not None,
            self.error is not None,
        )
        if sum(outcomes) > 1:
            raise ValueError("stop-loss result cannot carry conflicting outcomes")
        if self.trade is not None and (
            type(self.trade) is not SimulatedTrade
            or type(self.price) is not Decimal
            or type(self.quantity) is not int
        ):
            raise ValueError("confirmed stop-loss result requires exact trade details")
        if self.block_code is not None and (
            type(self.block_code) is not str or not self.block_code
        ):
            raise ValueError("stop-loss block code is invalid")


def execute_qualified_account_stop_loss_if_configured(
    *,
    position: Position,
    account: SimulatedAccount,
    trade_date: date,
    exit_advice: PositionExitAdvice | None,
    sell_executor: object,
) -> AccountStopLossRouteResult:
    """Evaluate a configured stop-loss using a qualified local quote and submit exact SELL."""

    configured = account.stop_loss_pct
    if configured is None:
        return AccountStopLossRouteResult(handled=False)
    if type(configured) not in (int, float) or type(configured) is bool:
        return AccountStopLossRouteResult(
            handled=True,
            block_code="AUTO_STOP_LOSS_THRESHOLD_INVALID",
        )
    try:
        threshold = Decimal(str(configured))
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        return AccountStopLossRouteResult(
            handled=True,
            block_code="AUTO_STOP_LOSS_THRESHOLD_INVALID",
        )
    if not threshold.is_finite() or threshold < Decimal(0):
        return AccountStopLossRouteResult(
            handled=True,
            block_code="AUTO_STOP_LOSS_THRESHOLD_INVALID",
        )
    if threshold == Decimal(0):
        return AccountStopLossRouteResult(handled=False)
    if (
        exit_advice is not None
        and exit_advice.reason_code != "ACCOUNT_STOP_LOSS"
        and (exit_advice.should_exit or exit_advice.should_reduce)
    ):
        return AccountStopLossRouteResult(handled=False)
    if not isinstance(sell_executor, AccountStopLossSellExecutor):
        return AccountStopLossRouteResult(
            handled=True,
            block_code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
        )
    if position.cost_basis_known is not True:
        return AccountStopLossRouteResult(
            handled=True,
            block_code="POSITION_COST_BASIS_UNKNOWN",
        )
    if position.available_quantity_known is not True:
        return AccountStopLossRouteResult(
            handled=True,
            block_code="SELLABLE_BALANCE_UNKNOWN",
        )
    if (
        type(position.quantity) not in (int, float)
        or type(position.quantity) is bool
        or type(position.total_cost) not in (int, float)
        or type(position.total_cost) is bool
    ):
        return AccountStopLossRouteResult(
            handled=True,
            block_code="AUTO_STOP_LOSS_POSITION_INVALID",
        )
    try:
        quantity_decimal = Decimal(str(position.quantity))
        total_cost = Decimal(str(position.total_cost))
        if (
            not quantity_decimal.is_finite()
            or quantity_decimal <= Decimal(0)
            or quantity_decimal != quantity_decimal.to_integral_value()
            or not total_cost.is_finite()
            or total_cost <= Decimal(0)
        ):
            raise ValueError("held quantity or cost basis is invalid")
        quantity = int(quantity_decimal)
    except (ArithmeticError, InvalidOperation, TypeError, ValueError, OverflowError):
        return AccountStopLossRouteResult(
            handled=True,
            block_code="AUTO_STOP_LOSS_POSITION_INVALID",
        )
    try:
        observation = sell_executor.capture_stop_loss_market(
            account_id=account.account_id,
            asset_code=position.asset_code,
            execution_date=trade_date,
        )
        price = observation.market.market_evidence_v1.reference_price
        if type(price) is not Decimal or not price.is_finite() or price <= Decimal(0):
            raise ValueError("qualified market price is invalid")
        evaluation = evaluate_account_stop_loss(
            price=price,
            quantity=quantity_decimal,
            total_cost=total_cost,
            threshold_pct=threshold,
        )
    except Exception as error:
        return AccountStopLossRouteResult(handled=True, error=error)
    if not evaluation.triggered:
        return AccountStopLossRouteResult(handled=True)
    reason = f"账户止损：本地模拟行情计算浮亏 {evaluation.pnl_pct}%"
    try:
        trade = sell_executor.execute_account_stop_loss(
            account_id=account.account_id,
            asset_code=position.asset_code,
            quantity=quantity,
            reason=reason,
            execution_date=trade_date,
            observation=observation,
        )
    except Exception as error:
        return AccountStopLossRouteResult(handled=True, error=error)
    return AccountStopLossRouteResult(
        handled=True,
        trade=trade,
        price=price,
        quantity=quantity,
    )


__all__: tuple[str, ...] = (
    "AccountStopLossRouteResult",
    "AccountStopLossSellExecutor",
    "execute_qualified_account_stop_loss_if_configured",
)
