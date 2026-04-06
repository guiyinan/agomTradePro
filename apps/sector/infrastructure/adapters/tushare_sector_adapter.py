"""
Legacy Tushare sector adapter backed by persisted sector facts.

The class keeps the old public API so sector workflows do not change, while the
implementation now delegates to the unified internal store.
"""

from __future__ import annotations

import pandas as pd

from .akshare_sector_adapter import AKShareSectorAdapter


class TushareSectorAdapter:
    """Compatibility facade reusing the internal sector fact store."""

    def __init__(self):
        self._delegate = AKShareSectorAdapter()

    def fetch_sw_industry_classify(self, level: str = "L1") -> pd.DataFrame:
        return self._delegate.fetch_sw_industry_classify(level=level)

    def fetch_sector_index_daily(
        self,
        sector_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        df = self._delegate.fetch_sector_index_daily(
            sector_code=sector_code,
            start_date=start_date,
            end_date=end_date,
        )
        if df.empty:
            return df
        return df.rename(columns={"open": "open_price"})

    def fetch_sector_constituents(self, sector_code: str) -> pd.DataFrame:
        from apps.sector.infrastructure.models import SectorConstituentModel, SectorInfoModel

        normalized_code = sector_code.replace(".SI", "")
        sector = (
            SectorInfoModel._default_manager.filter(sector_code=normalized_code)
            .values("sector_code")
            .first()
        )
        if sector is None:
            return pd.DataFrame()
        rows = list(
            SectorConstituentModel._default_manager.filter(
                sector_code=sector["sector_code"],
            )
            .values("stock_code", "enter_date", "exit_date")
            .order_by("stock_code", "-enter_date")
        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).rename(
            columns={
                "stock_code": "con_code",
                "enter_date": "in_date",
                "exit_date": "out_date",
            }
        )

    def fetch_all_sector_index_daily(
        self,
        sector_codes: list,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        df = self._delegate.fetch_all_sector_index_daily(
            sector_codes=sector_codes,
            start_date=start_date,
            end_date=end_date,
        )
        if df.empty:
            return df
        return df.rename(columns={"open": "open_price"})
