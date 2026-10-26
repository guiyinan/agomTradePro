"""Application ports for simulated trading."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, NotRequired, Protocol, TypedDict

from apps.simulated_trading.domain.entities import (
    Position,
    SimulatedAccount,
    SimulatedTrade,
)


class AssetPoolServiceProtocol(Protocol):
    """Asset-pool reads required by the auto-trading application service."""

    def get_investable_assets(self, asset_type: str) -> list[dict[str, object]]:
        """Return investable assets for one asset type."""
        ...

    def get_investable_assets_with_signals(
        self,
        asset_type: str,
        min_score: float,
        limit: int,
    ) -> list[dict[str, object]]:
        """Return investable assets that have active signals."""
        ...

    def get_asset_pool_type(self, asset_code: str) -> str | None:
        """Return the latest pool type for one asset."""
        ...


class SignalServiceProtocol(Protocol):
    """Signal snapshot reads required by auto-trading evaluation."""

    def get_signal_snapshot(self, signal_id: int) -> dict[str, Any] | None:
        """Return a signal snapshot by identifier."""
        ...


class PriceProviderProtocol(Protocol):
    """Historical price reads required by auto-trading evaluation."""

    def get_price(self, asset_code: str, trade_date: date) -> float | None:
        """Return an optional price for the requested date."""
        ...

    def require_price(self, asset_code: str, trade_date: date) -> float:
        """Return a required price or raise when it is unavailable."""
        ...


@dataclass(frozen=True)
class PositionPriceRefreshInput:
    """One price result passed without replacing its source clock with task time."""

    asset_code: str
    asset_type: str
    price: float
    source: str | None
    freshness: str
    as_of: date | None
    observed_at: datetime | None


class PositionPriceRefreshRepositoryProtocol(Protocol):
    """Refresh one account's valuation fields from a complete latest-price scope."""

    def update_position_prices_for_account(
        self,
        account_id: int,
        price_by_code: dict[str, PositionPriceRefreshInput],
    ) -> int:
        """Apply prices to fresh locked positions and return updated position rows."""
        ...


@dataclass(frozen=True)
class AccountPerformanceUpdate:
    """One bounded update to derived account performance fields."""

    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    winning_trades: int


class AccountPerformanceRepositoryProtocol(Protocol):
    """Persist account performance metrics without replacing ledger fields."""

    def update_performance_metrics(
        self,
        *,
        account_id: int,
        expected_account: SimulatedAccount,
        metrics: AccountPerformanceUpdate,
    ) -> None:
        """Update only derived metrics after checking the locked account snapshot."""
        ...


class InactiveAccountRepositoryProtocol(Protocol):
    """Apply an inactive-account decision after rechecking under the parent lock."""

    def get_active_accounts(self) -> list[SimulatedAccount]:
        """Return account targets for the bounded inactive-account scan."""
        ...

    def deactivate_if_inactive_since(self, account_id: int, cutoff_date: date) -> bool:
        """Deactivate only if the fresh stored last-trade date is past the cutoff."""
        ...


class RegimeServiceProtocol(Protocol):
    """Current market regime reads required by auto-trading."""

    def get_current_regime(self) -> str:
        """Return the current regime identifier."""
        ...


class AutoTradingTradeRepositoryProtocol(Protocol):
    """Trade persistence required by execution and daily net-value updates."""

    def save(self, trade: SimulatedTrade) -> int:
        """Persist one simulated trade."""
        ...

    def get_by_account(self, account_id: int) -> list[SimulatedTrade]:
        """Return trades for one account."""
        ...

    def count_by_execution_date(self, account_id: int, execution_date: date) -> int:
        """Count trades executed for an account on one date."""
        ...


class AutomaticBuyOrderExecutor(Protocol):
    """Submit an automatic BUY through the selected transactional executor."""

    def execute(
        self,
        account_id: int,
        asset_code: str,
        asset_name: str,
        asset_type: str,
        quantity: int,
        price: float,
        reason: str = "",
        signal_id: int | None = None,
        execution_date: date | None = None,
    ) -> SimulatedTrade:
        """Return only a confirmed, owner-scoped persisted trade."""
        ...


class AutomaticSellOrderExecutor(Protocol):
    """Submit an automatic SELL through the selected transactional executor."""

    def execute(
        self,
        account_id: int,
        asset_code: str,
        quantity: int,
        price: float,
        reason: str = "",
        execution_date: date | None = None,
    ) -> SimulatedTrade:
        """Return only a confirmed, owner-scoped persisted trade."""
        ...


class AdminDashboardRealizedPnlSummary(TypedDict):
    """Keep immutable PnL values separate from the effective correction overlay."""

    realized_pnl: Decimal | None
    known: bool
    covered_executed_sell_count: int
    executed_sell_count: int
    effective_realized_pnl: Decimal | None
    effective_known: bool
    effective_covered_executed_sell_count: int


class AdminDashboardTradeStatisticsRepositoryProtocol(Protocol):
    """Read only trade statistics used by the simulated-trading admin summary."""

    def count_trade_models(self) -> int:
        """Return the number of trade rows."""
        ...

    def summarize_trade_models_for_date(self, execution_date: date) -> dict[str, int]:
        """Return buy and sell row counts for one execution date."""
        ...

    def sum_realized_pnl_for_closed_trades(self) -> AdminDashboardRealizedPnlSummary:
        """Return executed SELL PnL with its completeness and coverage."""
        ...


class AssetPoolQueryRepositoryProtocol(Protocol):
    """资产池查询仓储接口。"""

    def list_investable_assets(
        self,
        asset_type: str,
        min_score: float,
        limit: int,
    ) -> list[dict[str, object]]: ...

    def get_latest_pool_type(self, asset_code: str) -> str | None: ...

    def summarize_pool_counts(self, asset_type: str | None = None) -> dict[str, int]: ...


class SignalQueryRepositoryProtocol(Protocol):
    """信号只读查询接口。"""

    def get_valid_signal_summaries(
        self,
        asset_codes: list[str] | None = None,
    ) -> list[dict[str, object]]: ...

    def get_signal_snapshot(self, signal_id: int) -> dict[str, object] | None: ...

    def get_signal_invalidation_payload(self, signal_id: int) -> tuple[str | None, str]: ...


@dataclass(frozen=True)
class PositionExitAdvice:
    """Unified exit advice for one held asset."""

    asset_code: str
    should_exit: bool = False
    should_reduce: bool = False
    quantity: int | None = None
    reason_code: str = ""
    reason_text: str = ""
    source: str = ""
    recommendation_id: str = ""
    target_price_low: float | None = None
    target_price_high: float | None = None
    stop_loss_price: float | None = None


class PositionExitAdvisorProtocol(Protocol):
    """Provide unified exit advice for simulated holdings."""

    def get_exit_advices(
        self,
        account_id: int,
        positions: list[object],
        as_of_date: date,
    ) -> list[PositionExitAdvice]: ...


class ExecutionLinkRecorderProtocol(Protocol):
    """Record links between simulated executions and system recommendations."""

    def record_execution(
        self,
        *,
        recommendation_id: str | None,
        transaction_id: int,
        account_id: int,
        security_code: str,
        actual_action: str,
        executed_at: datetime,
        match_if_missing: bool = False,
        notes: str = "",
    ) -> dict[str, object] | None: ...


class DailyNetValueWritePayload(TypedDict):
    """Canonical fields persisted for one daily net-value observation."""

    net_value: float
    cash: float
    market_value: float
    daily_return: float
    cumulative_return: float
    drawdown: float
    total_trades: int
    positions_count: int


class DailyNetValueRecord(TypedDict):
    """Typed daily net-value row with separate stored and effective metrics."""

    record_date: date
    net_value: Decimal
    cash: Decimal
    market_value: Decimal
    daily_return: float | None
    cumulative_return: float | None
    drawdown: float | None
    total_trades: int
    positions_count: int
    correction_event_watermark: int | None
    correction_event_watermark_sha256: str | None
    correction_coverage_known: bool
    original_net_value: NotRequired[Decimal]
    original_cash: NotRequired[Decimal]
    original_daily_return: NotRequired[float | None]
    original_cumulative_return: NotRequired[float | None]
    original_drawdown: NotRequired[float | None]
    correction_overlay_applied: NotRequired[bool]
    effective_metrics_known: NotRequired[bool]
    effective_metrics_reason_code: NotRequired[str | None]


class PreviousDailyNetValueRecord(TypedDict):
    """Reduced row used by previous-day calculations."""

    record_date: date
    net_value: Decimal
    cumulative_return: float | None
    correction_coverage_known: bool


class DailyNetValueAccountRepositoryProtocol(Protocol):
    """Account operations required by the daily net-value service."""

    def get_by_id(self, account_id: int) -> SimulatedAccount | None: ...

    def update_performance_metrics(
        self,
        *,
        account_id: int,
        expected_account: SimulatedAccount,
        metrics: AccountPerformanceUpdate,
    ) -> None: ...


class DailyNetValuePositionRepositoryProtocol(Protocol):
    """Position operations required by the daily net-value service."""

    def get_by_account(self, account_id: int) -> list[Position]: ...


class DailyNetValueTradeRepositoryProtocol(Protocol):
    """Trade operations required by the daily net-value service."""

    def get_by_account(self, account_id: int) -> list[SimulatedTrade]: ...

    def count_by_execution_date(self, account_id: int, execution_date: date) -> int: ...


class DailyNetValueRepositoryProtocol(Protocol):
    """日净值查询/写入接口。"""

    def upsert_daily_record(
        self,
        account_id: int,
        record_date: date,
        payload: DailyNetValueWritePayload,
        *,
        expected_account: SimulatedAccount,
    ) -> bool: ...

    def list_daily_records(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[DailyNetValueRecord]: ...

    def get_latest_record_before(
        self,
        account_id: int,
        current_date: date,
    ) -> PreviousDailyNetValueRecord | None: ...

    def get_max_net_value_before(self, account_id: int, before_date: date) -> float | None: ...
