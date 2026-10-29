"""Independent financial and scope invariants for injected settlement quotes."""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import cast

import pytest

from apps.backtest.application.simulated_trade_settlement import (
    SimulatedSettlementBacktestAdapter,
)
from apps.backtest.domain.stock_selection_backtest import (
    RebalanceFrequency,
    StockSelectionBacktestConfig,
)
from apps.backtest.domain.stock_trade_settlement import (
    SettlementSlippagePolicy,
    StockTradeSettlementContractError,
    StockTradeSettlementQuote,
    StockTradeSettlementRequest,
    StockTradeSide,
    validate_settlement_quote,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    PreparedSimulatedTrade,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import FeeApplicability
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from tests.unit.backtest.test_simulated_trade_settlement import (
    FRIDAY,
    MONDAY,
    PRICEY,
    STOCK,
    _CutoffResolver,
    _engine,
    _fee_policy,
    _RecordingPort,
    _rules,
    _scope,
    _stock_entries,
    _use_case,
)


def _request() -> StockTradeSettlementRequest:
    return StockTradeSettlementRequest(
        stock_code="600000.SH",
        side=StockTradeSide.BUY,
        quantity=100,
        price=Decimal("10.00"),
        trade_date=date(2026, 10, 16),
        available_cash=Decimal("2000.00"),
    )


def _quote() -> StockTradeSettlementQuote:
    return StockTradeSettlementQuote(
        stock_code="600000.SH",
        side=StockTradeSide.BUY,
        executed_quantity=100,
        executed_price=Decimal("10.00"),
        commission=Decimal("5.00"),
        transfer_fee=Decimal("0.02"),
        stamp_duty=Decimal("0.00"),
        slippage=Decimal("1.00"),
        amount=Decimal("1000.00"),
        cash_delta=Decimal("-1006.02"),
        trade_date=date(2026, 10, 16),
        market_session=date(2026, 10, 16),
        release_session=date(2026, 10, 19),
    )


def test_notional_must_describe_the_submitted_shares_and_price() -> None:
    """Self-consistent cash arithmetic cannot mask an undercharged notional."""
    forged = replace(_quote(), amount=Decimal("1.00"), cash_delta=Decimal("-7.02"))
    with pytest.raises(StockTradeSettlementContractError):
        validate_settlement_quote(
            request=_request(),
            quote=forged,
            slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        )


def test_session_must_match_the_requested_exchange_date() -> None:
    """A future session cannot grant a different release timetable."""
    forged = replace(
        _quote(), market_session=date(2026, 10, 20), release_session=date(2026, 10, 21)
    )
    with pytest.raises(StockTradeSettlementContractError):
        validate_settlement_quote(
            request=_request(),
            quote=forged,
            slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        )


def test_valid_quote_checks_ignore_ambient_decimal_precision() -> None:
    """The exact ordinary-plan cents remain valid under a caller's small context."""
    with localcontext() as context:
        context.prec = 3
        validate_settlement_quote(
            request=_request(),
            quote=_quote(),
            slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        )


def test_subcent_fee_cannot_be_applied_to_a_cent_valued_ledger() -> None:
    forged = replace(_quote(), transfer_fee=Decimal("0.021"), cash_delta=Decimal("-1006.021"))
    with pytest.raises(StockTradeSettlementContractError):
        validate_settlement_quote(
            request=_request(),
            quote=forged,
            slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        )


@pytest.mark.parametrize("cash", [Decimal("-1.00"), Decimal("NaN")])
def test_malformed_cash_is_rejected_before_it_can_authorize_a_trade(cash: Decimal) -> None:
    with pytest.raises(StockTradeSettlementContractError):
        validate_settlement_quote(
            request=replace(_request(), available_cash=cash),
            quote=_quote(),
            slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        )


def test_unknown_slippage_policy_cannot_skip_the_explicit_choice() -> None:
    with pytest.raises(StockTradeSettlementContractError):
        validate_settlement_quote(
            request=_request(),
            quote=_quote(),
            slippage_policy=cast(SettlementSlippagePolicy, "fee_component"),
        )


class _WrongAccountPrepare:
    """Return a valid ordinary plan that belongs to another account."""

    def prepare(
        self,
        intent: SimulatedTradeIntent,
        *,
        as_of: datetime | None = None,
    ) -> PreparedSimulatedTrade:
        prepared = _use_case(fee_policy=_fee_policy(slippage=FeeApplicability.APPLIES)).prepare(
            intent, as_of=as_of
        )
        other_intent = replace(intent, account_id=intent.account_id + 1)
        return replace(prepared, plan=replace(prepared.plan, intent=other_intent))


def test_adapter_cannot_relabel_another_account_plan_as_the_requested_account() -> None:
    """Copying request labels into a quote must not hide foreign plan evidence."""
    adapter = SimulatedSettlementBacktestAdapter(
        prepare_capability=_WrongAccountPrepare(),
        scope=_scope(),
        cutoff_resolver=_CutoffResolver(),
        slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
    )
    with pytest.raises(StockTradeSettlementContractError):
        adapter.quote(_request())


def test_engine_cash_is_exact_under_low_caller_precision() -> None:
    """Opt-in financial arithmetic preserves the ordinary settlement cents."""
    port = _RecordingPort(
        SimulatedSettlementBacktestAdapter(
            prepare_capability=_use_case(fee_policy=_fee_policy(slippage=FeeApplicability.APPLIES)),
            scope=_scope(),
            cutoff_resolver=_CutoffResolver(),
            slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        )
    )
    engine = _engine(
        config=StockSelectionBacktestConfig(
            start_date=FRIDAY,
            end_date=MONDAY,
            initial_capital=Decimal("20000"),
            rebalance_frequency=RebalanceFrequency.DAILY,
            max_positions=2,
        ),
        port=port,
        slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        stock_reader=lambda as_of: _stock_entries(
            [STOCK, PRICEY] if as_of < MONDAY else [PRICEY], as_of
        ),
    )
    with localcontext() as context:
        context.prec = 3
        result = engine.run(_rules())
    assert result.equity_curve[-1][1] == Decimal("19959.60")


class _DeficitSellPort:
    """Return valid SELL arithmetic whose fees exceed its gross proceeds."""

    def quote(self, request: StockTradeSettlementRequest) -> StockTradeSettlementQuote:
        return replace(
            _quote(),
            side=StockTradeSide.SELL,
            commission=Decimal("2000.00"),
            transfer_fee=Decimal("0"),
            stamp_duty=Decimal("0"),
            slippage=Decimal("0"),
            cash_delta=Decimal("-1000.00"),
            trade_date=request.trade_date,
            market_session=request.trade_date,
            release_session=None,
        )


def test_sell_fee_deficit_does_not_remove_the_release_guard() -> None:
    """A rejected SELL leaves the engine's tracked holding evidence intact."""
    engine = _engine(
        config=StockSelectionBacktestConfig(start_date=FRIDAY, end_date=MONDAY),
        port=_DeficitSellPort(),
        slippage_policy=SettlementSlippagePolicy.FEE_COMPONENT,
        stock_reader=lambda as_of: _stock_entries([STOCK], as_of),
    )
    engine._pending_release_sessions[STOCK] = MONDAY
    with pytest.raises(StockTradeSettlementContractError, match="cash negative"):
        engine._settled_sell(
            stock_code=STOCK,
            shares=100,
            price=Decimal("10.00"),
            trade_date=MONDAY,
            capital=Decimal("1.00"),
        )
    assert engine._pending_release_sessions == {STOCK: MONDAY}


@pytest.mark.parametrize("policy", [None, "fee_component"])
def test_injected_port_requires_an_explicit_policy_enum(policy: object) -> None:
    """Omitting or string-casting the slippage choice cannot enable a port."""
    with pytest.raises(StockTradeSettlementContractError, match="explicit"):
        _engine(
            config=StockSelectionBacktestConfig(start_date=FRIDAY, end_date=MONDAY),
            port=_DeficitSellPort(),
            slippage_policy=cast(SettlementSlippagePolicy, policy),
            stock_reader=lambda as_of: _stock_entries([STOCK], as_of),
        )
