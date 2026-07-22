"""Application ports for simulated trading."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, TypedDict

from apps.simulated_trading.domain.entities import (
    Position,
    SimulatedAccount,
    SimulatedTrade,
)


class AssetPoolQueryRepositoryProtocol(Protocol):
    """资产池查询仓储接口。"""

    def list_investable_assets(
        self,
        asset_type: str,
        min_score: float,
        limit: int,
    ) -> list[dict[str, object]]:
        ...

    def get_latest_pool_type(self, asset_code: str) -> str | None:
        ...

    def summarize_pool_counts(self, asset_type: str | None = None) -> dict[str, int]:
        ...


class SignalQueryRepositoryProtocol(Protocol):
    """信号只读查询接口。"""

    def get_valid_signal_summaries(
        self,
        asset_codes: list[str] | None = None,
    ) -> list[dict[str, object]]:
        ...

    def get_signal_snapshot(self, signal_id: int) -> dict[str, object] | None:
        ...

    def get_signal_invalidation_payload(self, signal_id: int) -> tuple[str | None, str]:
        ...


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
    ) -> list[PositionExitAdvice]:
        ...


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
    ) -> dict[str, object] | None:
        ...


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
    """Typed daily net-value row returned by the repository."""

    record_date: date
    net_value: Decimal
    cash: Decimal
    market_value: Decimal
    daily_return: float
    cumulative_return: float
    drawdown: float
    total_trades: int
    positions_count: int


class PreviousDailyNetValueRecord(TypedDict):
    """Reduced row used by previous-day calculations."""

    record_date: date
    net_value: Decimal
    cumulative_return: float


class DailyNetValueAccountRepositoryProtocol(Protocol):
    """Account operations required by the daily net-value service."""

    def get_by_id(self, account_id: int) -> SimulatedAccount | None: ...

    def save(self, account: SimulatedAccount, user_id: int | None = None) -> int: ...


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
    ) -> None: ...

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

    def get_max_net_value_before(self, account_id: int, before_date: date) -> float | None:
        ...
