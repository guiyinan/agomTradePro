"""Compose backtest settlement quotes with ordinary simulated preparation.

This explicit integration bridge connects the backtest settlement contract to
the simulated-trading prepare entry. It builds and validates quotes for
shared-planner comparison only; it is not a ledger or database acceptance path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Protocol

from apps.backtest.domain.stock_trade_settlement import (
    SettlementSlippagePolicy,
    StockTradeSettlementContractError,
    StockTradeSettlementQuote,
    StockTradeSettlementRequest,
    StockTradeSide,
    validate_settlement_quote,
)
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.simulated_trading.application.execution_settlement_uow import PreparedSimulatedTrade
from apps.simulated_trading.domain.execution_current_reference import SettlementExecutionPlanV3
from apps.simulated_trading.domain.execution_settlement_identity import SettlementExecutionPlanV2
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
)

_VERIFY_PRECISION = 80


class SimulatedPrepareCapability(Protocol):
    """Narrow read-only view of the ordinary simulated prepare entry."""

    def prepare(
        self,
        intent: SimulatedTradeIntent,
        *,
        as_of: datetime | None = None,
    ) -> PreparedSimulatedTrade:
        """Return one validated prepared trade without applying it."""
        ...


class BacktestCutoffResolver(Protocol):
    """Resolve the exact aware knowledge cutoff for one backtest trade date."""

    def cutoff_for(self, trade_date: date) -> datetime:
        """Return one timezone-aware cutoff instant for the given trade date."""
        ...


@dataclass(frozen=True)
class BacktestSettlementScope:
    """Explicit caller-supplied identity scope for simulated prepare calls."""

    account_id: int
    user_id: int
    security_id: str
    asset_name: str
    asset_type: str
    market: str
    board: str
    reason: str
    signal_id: int | None


class SimulatedSettlementBacktestAdapter:
    """Adapt the backtest settlement port to ordinary simulated prepare calls."""

    def __init__(
        self,
        *,
        prepare_capability: SimulatedPrepareCapability,
        scope: BacktestSettlementScope,
        cutoff_resolver: BacktestCutoffResolver,
        slippage_policy: SettlementSlippagePolicy,
    ) -> None:
        """Require an explicit prepare capability, scope, cutoff, and slippage policy."""

        self._prepare_capability = prepare_capability
        self._scope = scope
        self._cutoff_resolver = cutoff_resolver
        self._slippage_policy = slippage_policy
        self._sequence = 0

    def quote(self, request: StockTradeSettlementRequest) -> StockTradeSettlementQuote:
        """Return a bound ordinary quote independent of caller Decimal precision."""

        if type(self._slippage_policy) is not SettlementSlippagePolicy:
            raise StockTradeSettlementContractError("slippage policy must be explicit")
        with localcontext() as context:
            context.prec = _VERIFY_PRECISION
            quote = self._quote(request)
            validate_settlement_quote(
                request=request, quote=quote, slippage_policy=self._slippage_policy
            )
            return quote

    def _quote(self, request: StockTradeSettlementRequest) -> StockTradeSettlementQuote:
        """Prepare one exact intent and convert its validated plan into a quote.

        The returned quote is built only from the prepared plan's own evidence;
        request labels are never copied over a mismatched plan. Typed fee,
        rule, identity, calendar, and clock blocks from prepare propagate.
        """

        self._sequence += 1
        side = (
            SimulatedTradeSide.BUY
            if request.side is StockTradeSide.BUY
            else SimulatedTradeSide.SELL
        )
        intent = SimulatedTradeIntent(
            account_id=self._scope.account_id,
            user_id=self._scope.user_id,
            idempotency_key=f"backtest-settlement-{self._sequence}",
            side=side,
            security_id=self._scope.security_id,
            asset_code=request.stock_code,
            asset_name=self._scope.asset_name,
            asset_type=self._scope.asset_type,
            market=self._scope.market,
            board=self._scope.board,
            quantity=Decimal(request.quantity),
            price=request.price,
            reason=self._scope.reason,
            signal_id=self._scope.signal_id,
        )
        cutoff = self._cutoff_resolver.cutoff_for(request.trade_date)
        if type(cutoff) is not datetime or cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise StockTradeSettlementContractError(
                "cutoff resolver must return a timezone-aware datetime"
            )
        prepared = self._prepare_capability.prepare(intent, as_of=cutoff)
        if type(prepared) is not PreparedSimulatedTrade:
            raise StockTradeSettlementContractError("prepare returned an invalid contract type")
        plan = prepared.plan
        if type(plan) not in (SettlementExecutionPlanV2, SettlementExecutionPlanV3):
            raise StockTradeSettlementContractError("prepared plan type is unsupported")
        bundle = prepared.execution_bundle
        if type(bundle) is not ExecutionSettlementBundleV3:
            raise StockTradeSettlementContractError("prepared execution bundle type is unsupported")
        try:
            plan.__post_init__()
            plan.validate_at(cutoff)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise StockTradeSettlementContractError(
                "prepared plan failed exact revalidation at the request cutoff"
            ) from error
        if plan.intent != intent:
            raise StockTradeSettlementContractError(
                "prepared plan intent differs from the submitted intent"
            )
        if plan.pre_read_at != cutoff:
            raise StockTradeSettlementContractError(
                "prepared plan evidence cutoff differs from the request cutoff"
            )
        if plan.market_session != request.trade_date:
            raise StockTradeSettlementContractError(
                "prepared market session differs from the request trade date"
            )
        if (
            plan.settlement_bundle_id != bundle.bundle_id
            or plan.settlement_bundle_version != bundle.bundle_version
            or plan.settlement_bundle_hash != bundle.content_hash
        ):
            raise StockTradeSettlementContractError(
                "prepared plan is not bound to its execution bundle"
            )
        with localcontext() as context:
            context.prec = _VERIFY_PRECISION
            fees = plan.fee_breakdown
            total_fee = fees.commission + fees.transfer_fee + fees.stamp_duty + fees.slippage
            if total_fee != fees.total_fee:
                raise StockTradeSettlementContractError(
                    "prepared fee total differs from its components"
                )
            if (
                self._slippage_policy is SettlementSlippagePolicy.ALREADY_IN_PRICE
                and fees.slippage != Decimal("0")
            ):
                raise StockTradeSettlementContractError(
                    "prepared slippage fee would double-charge in-price slippage"
                )
            amount = plan.amount
            cash_delta = (
                -(amount + total_fee) if side is SimulatedTradeSide.BUY else amount - total_fee
            )
        return StockTradeSettlementQuote(
            stock_code=plan.intent.asset_code,
            side=request.side,
            executed_quantity=request.quantity,
            executed_price=plan.intent.price,
            commission=fees.commission,
            transfer_fee=fees.transfer_fee,
            stamp_duty=fees.stamp_duty,
            slippage=fees.slippage,
            amount=amount,
            cash_delta=cash_delta,
            trade_date=request.trade_date,
            market_session=plan.market_session,
            release_session=plan.settlement_release_date,
        )
