"""Collect confirmed automatic trades and stable per-account execution issues."""

from dataclasses import dataclass, field

from apps.simulated_trading.application.automatic_trade_execution import (
    AutomaticTradeExecutionPreflightBlocked,
)
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingIssue,
    AutoTradingIssueKind,
    build_account_auto_trading_outcome,
)


@dataclass(slots=True)
class AccountAutoTradingState:
    """Collect confirmed trades and stable issues for one account run."""

    account_id: int
    buy_count: int = 0
    sell_count: int = 0
    issues: list[AutoTradingIssue] = field(default_factory=list)

    def add_issue(
        self,
        *,
        kind: AutoTradingIssueKind,
        stage: str,
        code: str,
        asset_code: str | None = None,
        effects_indeterminate: bool = False,
    ) -> None:
        """Add one stable issue without exception text."""

        self.issues.append(
            AutoTradingIssue(
                kind=kind,
                stage=stage,
                code=code,
                asset_code=asset_code,
                effects_indeterminate=effects_indeterminate,
            )
        )

    def confirm_trade(self, action: str) -> None:
        """Count a use-case return immediately as a confirmed trade."""

        if action == "buy":
            self.buy_count += 1
        elif action == "sell":
            self.sell_count += 1
        else:
            raise ValueError("action must be buy or sell")

    @property
    def effects_indeterminate(self) -> bool:
        """Whether another order would depend on an uncertain account ledger."""
        return any(issue.effects_indeterminate for issue in self.issues)

    @property
    def must_stop(self) -> bool:
        """Stop further account work after unknown effects or unavailable scope."""
        return self.effects_indeterminate or any(
            issue.code
            in {
                "AUTO_TRADE_OWNER_CHANGED",
                "AUTO_TRADE_OWNER_UNAVAILABLE",
                "AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE",
            }
            for issue in self.issues
        )

    def record_execution_error(self, *, action: str, asset_code: str, error: Exception) -> None:
        """Separate verified pre-write blocks from uncertain execution effects."""
        blocked = isinstance(error, AutomaticTradeExecutionPreflightBlocked)
        self.add_issue(
            kind=AutoTradingIssueKind.BLOCKED if blocked else AutoTradingIssueKind.FAILED,
            stage=f"{action}_execution",
            code=(
                error.code
                if isinstance(error, AutomaticTradeExecutionPreflightBlocked)
                else f"{action.upper()}_EXECUTION_OUTCOME_UNKNOWN"
            ),
            asset_code=asset_code,
            effects_indeterminate=not blocked,
        )

    def build(self) -> AccountAutoTradingOutcome:
        """Build the immutable account outcome accumulated so far."""

        return build_account_auto_trading_outcome(
            self.account_id,
            buy_count=self.buy_count,
            sell_count=self.sell_count,
            issues=tuple(self.issues),
        )
