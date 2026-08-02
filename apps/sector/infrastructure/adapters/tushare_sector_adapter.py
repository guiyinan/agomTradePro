"""
Legacy Tushare sector adapter backed by persisted sector facts.

The class keeps the old public API so sector workflows do not change, while the
implementation now delegates to the unified internal store.
"""

from __future__ import annotations

from datetime import date

from apps.data_center.application.public import get_sector_membership_repository_port

from .akshare_sector_adapter import (
    AKShareSectorAdapter,
    DataFramePayload,
    _normalize_sector_code,
    _validate_date_range,
    pd,
)


class TushareSectorAdapter:
    """Compatibility facade reusing the internal sector fact store."""

    def __init__(self) -> None:
        self._delegate = AKShareSectorAdapter()

    def fetch_sw_industry_classify(self, level: str = "L1") -> DataFramePayload:
        return self._delegate.fetch_sw_industry_classify(level=level)

    def fetch_sector_index_daily(
        self,
        sector_code: str,
        start_date: str,
        end_date: str,
    ) -> DataFramePayload:
        _validate_date_range(start_date, end_date)
        df = self._delegate.fetch_sector_index_daily(
            sector_code=sector_code,
            start_date=start_date,
            end_date=end_date,
        )
        if df.empty:
            return df
        return df.rename(columns={"open": "open_price"})

    def fetch_sector_constituents(self, sector_code: str) -> DataFramePayload:
        normalized_code = _normalize_sector_code(sector_code)
        facts = get_sector_membership_repository_port().get_members(
            normalized_code,
            as_of=date.today(),
        )
        rows = [
            {
                "stock_code": fact.asset_code,
                "enter_date": fact.effective_date,
                "exit_date": fact.expiry_date,
            }
            for fact in facts
        ]
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values(["stock_code", "enter_date"]).rename(
            columns={
                "stock_code": "con_code",
                "enter_date": "in_date",
                "exit_date": "out_date",
            }
        )

    def fetch_all_sector_index_daily(
        self,
        sector_codes: list[str],
        start_date: str,
        end_date: str,
    ) -> DataFramePayload:
        _validate_date_range(start_date, end_date)
        normalized_codes = [_normalize_sector_code(code) for code in sector_codes]
        df = self._delegate.fetch_all_sector_index_daily(
            sector_codes=normalized_codes,
            start_date=start_date,
            end_date=end_date,
        )
        if df.empty:
            return df
        return df.rename(columns={"open": "open_price"})
