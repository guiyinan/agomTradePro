"""Run one explicitly bounded account-stop-loss check without other trade legs."""

from collections.abc import Callable, Sequence
from datetime import date
from typing import Protocol

from apps.simulated_trading.application.auto_trading_account_stop_loss import (
    execute_qualified_account_stop_loss_if_configured,
)
from apps.simulated_trading.application.auto_trading_outcome_state import AccountAutoTradingState
from apps.simulated_trading.application.ports import AutomaticSellOrderExecutor
from apps.simulated_trading.application.use_cases import PositionRepositoryProtocol
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingIssueKind,
)
from apps.simulated_trading.domain.entities import Position, SimulatedAccount, SimulatedTrade


class AccountStopLossCheckHost(Protocol):
    """Expose the existing engine ports needed by the bounded stop-loss path."""

    position_repo: PositionRepositoryProtocol
    sell_use_case: AutomaticSellOrderExecutor

    def _record_confirmed_execution_link(
        self,
        state: AccountAutoTradingState,
        *,
        trade: SimulatedTrade,
        account_id: int,
        asset_code: str,
        action: str,
        recommendation_id: str | None,
        match_if_missing: bool,
        notes: str,
    ) -> None:
        """Record the ordinary execution link after a confirmed SELL."""
        ...

    def _record_performance_outcome(
        self,
        account_id: int,
        trade_date: date,
        state: AccountAutoTradingState,
    ) -> None:
        """Record account performance after the stop-loss path finishes."""
        ...


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


def execute_account_stop_loss_only(
    host: AccountStopLossCheckHost,
    account: SimulatedAccount,
    trade_date: date,
    state: AccountAutoTradingState,
) -> AccountAutoTradingOutcome:
    """Execute explicit account thresholds without entering strategy or legacy paths."""

    try:
        positions = host.position_repo.get_by_account(account.account_id)
    except Exception:
        state.add_issue(
            kind=AutoTradingIssueKind.FAILED,
            stage="position_read",
            code="ACCOUNT_POSITION_READ_FAILED",
        )
        return state.build()

    def confirmed(trade: SimulatedTrade, position: Position) -> None:
        """Record an ordinary execution link only after a confirmed stop-loss write."""

        host._record_confirmed_execution_link(
            state,
            trade=trade,
            account_id=account.account_id,
            asset_code=position.asset_code,
            action="sell",
            recommendation_id=None,
            match_if_missing=False,
            notes="Explicit account-stop-loss-only simulation check",
        )

    run_account_stop_loss_check(
        account=account,
        positions=positions,
        trade_date=trade_date,
        sell_executor=host.sell_use_case,
        state=state,
        on_confirmed=confirmed,
    )
    host._record_performance_outcome(account.account_id, trade_date, state)
    return state.build()
