"""Application ports for simulated trading."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol


class AssetPoolQueryRepositoryProtocol(Protocol):
    """资产池查询仓储接口。"""

    def list_investable_assets(
        self,
        asset_type: str,
        min_score: float,
        limit: int,
    ) -> list[dict]:
        ...

    def get_latest_pool_type(self, asset_code: str) -> str | None:
        ...

    def summarize_pool_counts(self, asset_type: str | None = None) -> dict[str, int]:
        ...


class SignalQueryRepositoryProtocol(Protocol):
    """信号只读查询接口。"""

    def get_valid_signal_summaries(self, asset_codes: list[str] | None = None) -> list[dict]:
        ...

    def get_signal_snapshot(self, signal_id: int) -> dict | None:
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


class PositionExitAdvisorProtocol(Protocol):
    """Provide unified exit advice for simulated holdings."""

    def get_exit_advices(
        self,
        account_id: int,
        positions: list[object],
        as_of_date: date,
    ) -> list[PositionExitAdvice]:
        ...


class DailyNetValueRepositoryProtocol(Protocol):
    """日净值查询/写入接口。"""

    def upsert_daily_record(self, account_id: int, record_date: date, payload: dict[str, object]) -> None:
        ...

    def list_daily_records(
        self,
        account_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, object]]:
        ...

    def get_latest_record_before(self, account_id: int, current_date: date) -> dict[str, object] | None:
        ...

    def get_max_net_value_before(self, account_id: int, before_date: date) -> float | None:
        ...
