"""Application ports for simulated trading."""

from datetime import date
from typing import Dict, List, Optional, Protocol, Tuple


class AssetPoolQueryRepositoryProtocol(Protocol):
    """资产池查询仓储接口。"""

    def list_investable_assets(
        self,
        asset_type: str,
        min_score: float,
        limit: int,
    ) -> List[dict]:
        ...

    def get_latest_pool_type(self, asset_code: str) -> Optional[str]:
        ...

    def summarize_pool_counts(self, asset_type: Optional[str] = None) -> Dict[str, int]:
        ...


class SignalQueryRepositoryProtocol(Protocol):
    """信号只读查询接口。"""

    def get_valid_signal_summaries(self, asset_codes: Optional[List[str]] = None) -> List[dict]:
        ...

    def get_signal_snapshot(self, signal_id: int) -> Optional[dict]:
        ...

    def get_signal_invalidation_payload(self, signal_id: int) -> Tuple[Optional[str], str]:
        ...


class DailyNetValueRepositoryProtocol(Protocol):
    """日净值查询/写入接口。"""

    def upsert_daily_record(self, account_id: int, record_date: date, payload: Dict[str, object]) -> None:
        ...

    def list_daily_records(
        self,
        account_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, object]]:
        ...

    def get_latest_record_before(self, account_id: int, current_date: date) -> Optional[Dict[str, object]]:
        ...

    def get_max_net_value_before(self, account_id: int, before_date: date) -> Optional[float]:
        ...
