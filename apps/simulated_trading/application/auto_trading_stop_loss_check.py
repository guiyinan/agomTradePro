"""Run one explicitly bounded account-stop-loss check without other trade legs."""

from collections.abc import Callable, Sequence
from datetime import date

from apps.simulated_trading.application.auto_trading_account_stop_loss import (
    execute_qualified_account_stop_loss_if_configured,
)
from apps.simulated_trading.application.auto_trading_outcome_state import AccountAutoTradingState
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingIssueKind,
)
from apps.simulated_trading.domain.entities import Position, SimulatedAccount, SimulatedTrade


def run_account_stop_loss_check(
    *,
    account: SimulatedAccount,
    positions: Sequence[Position],
    trade_date: date,
    sell_executor: object,
    state: AccountAutoTradingState,
    on_confirmed: Callable[[SimulatedTrade, Position], None],
) -> AccountAutoTradingOutcome:
    """Check account thresholds only; never inspect strategy, BUY pools or legacy exits."""

    for position in positions:
        result = execute_qualified_account_stop_loss_if_configured(
            position=position,
            account=account,
            trade_date=trade_date,
            exit_advice=None,
            sell_executor=sell_executor,
        )
        if not result.handled:
            state.add_issue(
                kind=AutoTradingIssueKind.BLOCKED,
                stage="account_stop_loss",
                code="ACCOUNT_STOP_LOSS_NOT_CONFIGURED",
                asset_code=position.asset_code,
            )
        elif result.block_code is not None:
            state.add_issue(
                kind=AutoTradingIssueKind.BLOCKED,
                stage="account_stop_loss",
                code=result.block_code,
                asset_code=position.asset_code,
            )
        elif result.error is not None:
            state.record_execution_error(
                action="sell", asset_code=position.asset_code, error=result.error
            )
        elif result.trade is not None:
            state.confirm_trade("sell")
            on_confirmed(result.trade, position)
        if state.must_stop:
            break
    return state.build()
