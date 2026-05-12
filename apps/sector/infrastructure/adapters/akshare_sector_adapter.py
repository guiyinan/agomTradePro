"""AKShare-backed sector adapter with local-table fallback."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from apps.sector.infrastructure.models import (
    SectorConstituentModel,
    SectorIndexModel,
    SectorInfoModel,
)
from core.integration.akshare_sdk import get_akshare_module

logger = logging.getLogger(__name__)


def _normalize_level(level: str) -> str:
    mapping = {"L1": "SW1", "L2": "SW2", "L3": "SW3", "SW1": "SW1", "SW2": "SW2", "SW3": "SW3"}
    return mapping.get(level, level)


def _normalize_sector_code(sector_code: object) -> str:
    return str(sector_code).replace(".SI", "").strip()


def _parse_date_input(raw: str) -> date:
    if "-" in raw or "/" in raw:
        return date.fromisoformat(raw.replace("/", "-"))
    return date.fromisoformat(f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}")


def _load_local_sector_classify(level: str) -> pd.DataFrame:
    rows = list(
        SectorInfoModel._default_manager.filter(is_active=True, level=level)
        .values("sector_code", "sector_name", "level", "parent_code")
        .order_by("sector_code")
    )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _load_local_sector_index_daily(
    sector_code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    start = _parse_date_input(start_date)
    end = _parse_date_input(end_date)
    rows = list(
        SectorIndexModel._default_manager.filter(
            sector_code=sector_code,
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
    return pd.DataFrame(rows) if rows else pd.DataFrame()


class AKShareSectorAdapter:
    """Primary sector adapter backed by live AKShare SW data."""

    _LEVEL_FN_MAP = {
        "SW1": "sw_index_first_info",
        "SW2": "sw_index_second_info",
        "SW3": "sw_index_third_info",
    }

    def __init__(self) -> None:
        self._ak = None

    def _get_ak(self):
        if self._ak is None:
            self._ak = get_akshare_module()
        return self._ak

    def _fetch_remote_sector_classify(self, level: str) -> pd.DataFrame:
        function_name = self._LEVEL_FN_MAP.get(level)
        if function_name is None:
            return pd.DataFrame()

        fetcher = getattr(self._get_ak(), function_name, None)
        if fetcher is None:
            return pd.DataFrame()

        raw = fetcher()
        if raw is None or raw.empty:
            return pd.DataFrame()

        mapped = pd.DataFrame(
            {
                "sector_code": raw["行业代码"].map(_normalize_sector_code),
                "sector_name": raw["行业名称"].astype(str).str.strip(),
                "level": level,
                "parent_code": (
                    raw["上级行业"].map(_normalize_sector_code)
                    if "上级行业" in raw.columns
                    else None
                ),
            }
        )
        if "parent_code" in mapped.columns:
            mapped["parent_code"] = mapped["parent_code"].replace({"nan": None, "None": None})
        return mapped.dropna(subset=["sector_code", "sector_name"])

    def fetch_sw_industry_classify(self, level: str = "L1") -> pd.DataFrame:
        normalized_level = _normalize_level(level)
        try:
            remote = self._fetch_remote_sector_classify(normalized_level)
            if not remote.empty:
                return remote
        except Exception as exc:
            logger.warning("AKShare sector classify fetch failed for %s: %s", normalized_level, exc)
        return _load_local_sector_classify(normalized_level)

    def fetch_sector_list(self) -> pd.DataFrame:
        return self.fetch_sw_industry_classify(level="SW1")

    def fetch_sector_index_daily(
        self,
        sector_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        normalized_code = _normalize_sector_code(sector_code)
        start = _parse_date_input(start_date)
        end = _parse_date_input(end_date)

        try:
            raw = self._get_ak().index_hist_sw(symbol=normalized_code, period="day")
            if raw is not None and not raw.empty:
                frame = raw.copy()
                frame["trade_date"] = pd.to_datetime(frame["日期"], errors="coerce").dt.date
                frame["open_price"] = pd.to_numeric(frame["开盘"], errors="coerce")
                frame["high"] = pd.to_numeric(frame["最高"], errors="coerce")
                frame["low"] = pd.to_numeric(frame["最低"], errors="coerce")
                frame["close"] = pd.to_numeric(frame["收盘"], errors="coerce")
                frame["volume"] = pd.to_numeric(frame["成交量"], errors="coerce")
                frame["amount"] = pd.to_numeric(frame["成交额"], errors="coerce")
                frame = frame.dropna(subset=["trade_date", "close"])
                frame = frame[
                    (frame["trade_date"] >= start) &
                    (frame["trade_date"] <= end)
                ].sort_values("trade_date")
                if not frame.empty:
                    frame["change_pct"] = frame["close"].pct_change().fillna(0.0) * 100.0
                    frame["turnover_rate"] = None
                    return frame[
                        [
                            "trade_date",
                            "open_price",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "amount",
                            "change_pct",
                            "turnover_rate",
                        ]
                    ]
        except Exception as exc:
            logger.warning("AKShare sector index fetch failed for %s: %s", normalized_code, exc)

        return _load_local_sector_index_daily(normalized_code, start_date, end_date)

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
            frames.append(df.assign(sector_code=_normalize_sector_code(sector_code)))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
