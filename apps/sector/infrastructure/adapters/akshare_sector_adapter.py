"""AKShare-backed sector adapter with local-table fallback."""

from __future__ import annotations

import importlib
import logging
import re
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol, cast

import numpy as np

from apps.data_center.application.public import get_sector_membership_repository_port
from apps.data_center.composition import get_akshare_module
from apps.sector.infrastructure.models import SectorIndexModel, SectorInfoModel

logger = logging.getLogger(__name__)

DataFramePayload = Any
_SECTOR_CODE_PATTERN = re.compile(r"^\d{6}(?:\.SI)?$")
_STOCK_CODE_PATTERN = re.compile(r"^\d{6}(?:\.(?:SH|SZ|BJ))?$")
_ADAPTER_EXCEPTIONS = (
    ArithmeticError,
    AttributeError,
    ConnectionError,
    KeyError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


class PandasModuleProtocol(Protocol):
    """Minimal pandas surface used at the external dataframe boundary."""

    def DataFrame(self, data: object = None) -> DataFramePayload:
        """Construct one dataframe."""
        ...

    def to_datetime(self, values: object, *, errors: str) -> DataFramePayload:
        """Normalize datetime-like external values."""
        ...

    def to_numeric(self, values: object, *, errors: str) -> DataFramePayload:
        """Normalize numeric-like external values."""
        ...

    def concat(
        self,
        frames: list[DataFramePayload],
        *,
        ignore_index: bool,
    ) -> DataFramePayload:
        """Concatenate normalized dataframes."""
        ...


class AKShareSectorProtocol(Protocol):
    """Minimal dynamic AKShare surface used by the sector adapter."""

    def __getattr__(self, name: str) -> Callable[[], DataFramePayload]: ...

    def index_hist_sw(
        self,
        *,
        symbol: str,
        period: str,
    ) -> DataFramePayload:
        """Return Shenwan sector index history."""
        ...


pd = cast(PandasModuleProtocol, importlib.import_module("pandas"))


def _normalize_level(level: str) -> str:
    mapping = {
        "L1": "SW1",
        "L2": "SW2",
        "L3": "SW3",
        "SW1": "SW1",
        "SW2": "SW2",
        "SW3": "SW3",
    }
    normalized = str(level).strip().upper()
    if normalized not in mapping:
        raise ValueError("sector_level_invalid")
    return mapping[normalized]


def _normalize_sector_code(sector_code: object) -> str:
    normalized = str(sector_code).strip().upper()
    if _SECTOR_CODE_PATTERN.fullmatch(normalized) is None:
        raise ValueError("sector_code_invalid")
    return normalized.removesuffix(".SI")


def _normalize_external_sector_code(sector_code: object) -> str | None:
    try:
        return _normalize_sector_code(sector_code)
    except ValueError:
        return None


def _parse_date_input(raw: str) -> date:
    normalized = str(raw).strip()
    if len(normalized) > 10 or any(ord(character) < 32 for character in normalized):
        raise ValueError("sector_date_invalid")
    if "-" in normalized or "/" in normalized:
        return date.fromisoformat(normalized.replace("/", "-"))
    if len(normalized) != 8 or not normalized.isascii() or not normalized.isdigit():
        raise ValueError("sector_date_invalid")
    return date.fromisoformat(f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:8]}")


def _validate_date_range(start_date: str, end_date: str) -> tuple[date, date]:
    """Return one ordered plain-date range."""

    start = _parse_date_input(start_date)
    end = _parse_date_input(end_date)
    if start > end:
        raise ValueError("sector_date_range_invalid")
    return start, end


def _validate_sector_name(sector_name: str) -> str:
    """Return one bounded non-empty sector name for ORM lookup."""

    normalized = str(sector_name).strip()
    if (
        not normalized
        or len(normalized) > 100
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ValueError("sector_name_invalid")
    return normalized


def _load_local_sector_classify(level: str) -> DataFramePayload:
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
) -> DataFramePayload:
    start, end = _validate_date_range(start_date, end_date)
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
        self._ak: AKShareSectorProtocol | None = None

    def _get_ak(self) -> AKShareSectorProtocol:
        if self._ak is None:
            self._ak = cast(AKShareSectorProtocol, get_akshare_module())
        return self._ak

    def _fetch_remote_sector_classify(self, level: str) -> DataFramePayload:
        function_name = self._LEVEL_FN_MAP.get(level)
        if function_name is None:
            return pd.DataFrame()

        fetcher: Callable[[], DataFramePayload] | None = getattr(
            self._get_ak(),
            function_name,
            None,
        )
        if fetcher is None:
            return pd.DataFrame()

        raw = fetcher()
        if raw is None or raw.empty:
            return pd.DataFrame()

        mapped = pd.DataFrame(
            {
                "sector_code": raw["行业代码"].map(_normalize_external_sector_code),
                "sector_name": raw["行业名称"].astype(str).str.strip(),
                "level": level,
                "parent_code": (
                    raw["上级行业"].map(_normalize_external_sector_code)
                    if "上级行业" in raw.columns
                    else None
                ),
            }
        )
        if "parent_code" in mapped.columns:
            mapped["parent_code"] = mapped["parent_code"].replace({"nan": None, "None": None})
        valid_codes = mapped["sector_code"].astype(str).str.fullmatch(r"\d{6}", na=False)
        valid_names = ~mapped["sector_name"].astype(str).str.casefold().isin({"", "nan", "none"})
        return (
            mapped.loc[valid_codes & valid_names]
            .drop_duplicates(subset=["sector_code"], keep="last")
            .sort_values("sector_code")
            .reset_index(drop=True)
        )

    def fetch_sw_industry_classify(self, level: str = "L1") -> DataFramePayload:
        normalized_level = _normalize_level(level)
        try:
            remote = self._fetch_remote_sector_classify(normalized_level)
            if not remote.empty:
                return remote
        except _ADAPTER_EXCEPTIONS as exc:
            logger.warning(
                "AKShare sector classify fetch failed; level=%s; exception_type=%s",
                normalized_level,
                type(exc).__name__,
            )
        return _load_local_sector_classify(normalized_level)

    def fetch_sector_list(self) -> DataFramePayload:
        return self.fetch_sw_industry_classify(level="SW1")

    def fetch_sector_index_daily(
        self,
        sector_code: str,
        start_date: str,
        end_date: str,
    ) -> DataFramePayload:
        normalized_code = _normalize_sector_code(sector_code)
        start, end = _validate_date_range(start_date, end_date)

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
                numeric_columns = [
                    "open_price",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                ]
                for column in numeric_columns:
                    frame.loc[~np.isfinite(frame[column]), column] = np.nan
                frame = frame.dropna(subset=["trade_date", "close"])
                frame = frame[frame["close"] > 0]
                for column in ["open_price", "high", "low", "volume", "amount"]:
                    frame.loc[frame[column] < 0, column] = np.nan
                frame = frame[
                    (frame["trade_date"] >= start) & (frame["trade_date"] <= end)
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
        except _ADAPTER_EXCEPTIONS as exc:
            logger.warning(
                "AKShare sector index fetch failed; sector_code=%s; exception_type=%s",
                normalized_code,
                type(exc).__name__,
            )

        return _load_local_sector_index_daily(normalized_code, start_date, end_date)

    def fetch_sector_constituents(self, sector_name: str) -> DataFramePayload:
        normalized_name = _validate_sector_name(sector_name)
        facts = [
            fact
            for fact in get_sector_membership_repository_port().list_current(as_of=date.today())
            if fact.sector_name.strip() == normalized_name
        ]
        rows = [{"stock_code": fact.asset_code} for fact in facts]
        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame(rows)
        valid_codes = (
            frame["stock_code"]
            .astype(str)
            .str.fullmatch(
                _STOCK_CODE_PATTERN,
                na=False,
            )
        )
        return frame.loc[valid_codes].drop_duplicates(subset=["stock_code"]).assign(stock_name="")

    def fetch_all_sector_codes(self, level: str = "L1") -> list[str]:
        df = self.fetch_sw_industry_classify(level=level)
        return [str(code) for code in df["sector_code"].tolist()] if not df.empty else []

    def fetch_industry_stocks(self, industry_name: str) -> list[str]:
        df = self.fetch_sector_constituents(industry_name)
        return [str(code) for code in df["stock_code"].tolist()] if not df.empty else []

    def fetch_all_sector_index_daily(
        self,
        sector_codes: list[str],
        start_date: str,
        end_date: str,
    ) -> DataFramePayload:
        _validate_date_range(start_date, end_date)
        frames: list[DataFramePayload] = []
        for sector_code in sector_codes:
            try:
                normalized_code = _normalize_sector_code(sector_code)
                df = self.fetch_sector_index_daily(normalized_code, start_date, end_date)
            except _ADAPTER_EXCEPTIONS as exc:
                logger.warning(
                    "Skipping invalid sector index batch item; exception_type=%s",
                    type(exc).__name__,
                )
                continue
            if df is None or df.empty:
                continue
            frames.append(df.assign(sector_code=normalized_code))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
