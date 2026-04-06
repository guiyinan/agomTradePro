"""
Legacy sector adapter backed by local sector/data_center facts.

The historical AKShare-facing API is preserved for callers, but all reads now
come from persisted sector tables instead of direct SDK imports.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from apps.sector.infrastructure.models import (
    SectorConstituentModel,
    SectorIndexModel,
    SectorInfoModel,
)


def _normalize_level(level: str) -> str:
    mapping = {"L1": "SW1", "L2": "SW2", "L3": "SW3"}
    return mapping.get(level, level)


class AKShareSectorAdapter:
    """Compatibility adapter for sector reads after data-center cutover."""

    def fetch_sw_industry_classify(self, level: str = "L1") -> pd.DataFrame:
        normalized_level = _normalize_level(level)
        rows = list(
            SectorInfoModel._default_manager.filter(is_active=True, level=normalized_level)
            .values("sector_code", "sector_name", "level", "parent_code")
            .order_by("sector_code")
        )
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def fetch_sector_list(self) -> pd.DataFrame:
        return self.fetch_sw_industry_classify(level="SW1")

    def fetch_sector_index_daily(
        self,
        sector_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        start = date.fromisoformat(start_date.replace("/", "-")) if "-" in start_date else date.fromisoformat(
            f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        )
        end = date.fromisoformat(end_date.replace("/", "-")) if "-" in end_date else date.fromisoformat(
            f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
        )
        rows = list(
            SectorIndexModel._default_manager.filter(
                sector_code=sector_code.replace(".SI", ""),
                trade_date__gte=start,
                trade_date__lte=end,
            )
            .values(
                "trade_date",
                "open_price",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "change_pct",
                "turnover_rate",
            )
            .order_by("trade_date")
        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).rename(columns={"open_price": "open"})

    def fetch_sector_constituents(self, sector_name: str) -> pd.DataFrame:
        sector = (
            SectorInfoModel._default_manager.filter(sector_name=sector_name, is_active=True)
            .values("sector_code")
            .first()
        )
        if sector is None:
            return pd.DataFrame()
        rows = list(
            SectorConstituentModel._default_manager.filter(
                sector_code=sector["sector_code"],
                is_current=True,
            )
            .values("stock_code")
            .order_by("stock_code")
        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).assign(stock_name="")

    def fetch_all_sector_codes(self, level: str = "L1") -> list[str]:
        df = self.fetch_sw_industry_classify(level=level)
        return df["sector_code"].tolist() if not df.empty else []

    def fetch_industry_stocks(self, industry_name: str) -> list[str]:
        df = self.fetch_sector_constituents(industry_name)
        return df["stock_code"].tolist() if not df.empty else []

    def fetch_all_sector_index_daily(
        self,
        sector_codes: list,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for sector_code in sector_codes:
            df = self.fetch_sector_index_daily(sector_code, start_date, end_date)
            if df is None or df.empty:
                continue
            frames.append(df.assign(sector_code=sector_code.replace(".SI", "")))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
