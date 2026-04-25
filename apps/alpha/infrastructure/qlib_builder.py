from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from shared.infrastructure.tushare_client import create_tushare_pro_client

logger = logging.getLogger(__name__)

UNIVERSE_INDEX_CODE_MAP: dict[str, str] = {
    "csi300": "000300.SH",
    "csi500": "000905.SH",
    "sse50": "000016.SH",
    "csi1000": "000852.SH",
}

INDEX_CODES_FOR_BUILD: tuple[str, ...] = (
    "000016.SH",
    "000300.SH",
    "000852.SH",
    "000905.SH",
)


@dataclass(frozen=True)
class QlibBuildSummary:
    """Summary for a qlib data build run."""

    requested_target_date: date
    effective_target_date: date | None
    latest_local_date_before: date | None
    latest_local_date_after: date | None
    calendar_days_written: int
    instrument_files_written: int
    feature_series_written: int
    stock_count: int
    universe_count: int
    warning_messages: tuple[str, ...] = ()


def inspect_latest_trade_date(provider_uri: str) -> date | None:
    """Inspect the latest local qlib trade date from the day calendar file."""
    calendar_path = _calendar_path(Path(provider_uri).expanduser())
    if not calendar_path.exists():
        return None

    latest_line = None
    with calendar_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            normalized = line.strip()
            if normalized:
                latest_line = normalized

    if not latest_line:
        return None
    return date.fromisoformat(latest_line[:10])


def normalize_qlib_symbol(ts_code: str) -> str:
    """Convert tushare code into qlib instrument file symbol."""
    market, code = ts_code.split(".", 1)[1], ts_code.split(".", 1)[0]
    return f"{market.upper()}{code}"


def normalize_feature_symbol(ts_code: str) -> str:
    """Convert tushare code into qlib feature directory symbol."""
    market, code = ts_code.split(".", 1)[1], ts_code.split(".", 1)[0]
    return f"{market.lower()}{code}"


def resolve_effective_trade_date(
    requested_trade_date: date,
    latest_available_date: date | None,
    *,
    max_forward_gap_days: int = 10,
) -> tuple[date, dict[str, object]]:
    """Resolve a safe qlib prediction date and explicit metadata."""
    if latest_available_date is None:
        raise RuntimeError("本地 Qlib 数据目录为空，无法执行实时推理")

    if requested_trade_date <= latest_available_date:
        return requested_trade_date, {
            "effective_trade_date": requested_trade_date.isoformat(),
            "trade_date_adjusted": False,
        }

    if requested_trade_date > latest_available_date + timedelta(days=max_forward_gap_days):
        raise RuntimeError(
            f"本地 Qlib 数据最新交易日为 {latest_available_date.isoformat()}，"
            f"早于请求交易日 {requested_trade_date.isoformat()}，请先同步 Qlib 数据"
        )

    return latest_available_date, {
        "requested_trade_date": requested_trade_date.isoformat(),
        "effective_trade_date": latest_available_date.isoformat(),
        "trade_date_adjusted": True,
        "trade_date_adjust_reason": (
            f"请求交易日 {requested_trade_date.isoformat()} 尚无本地 Qlib 日线，"
            f"已回退到最新可用交易日 {latest_available_date.isoformat()}。"
        ),
    }


class TushareQlibBuilder:
    """Build or refresh recent qlib daily data from Tushare."""

    def __init__(self, provider_uri: str, *, pro_client: object | None = None) -> None:
        self._provider_uri = Path(provider_uri).expanduser()
        self._pro = pro_client or create_tushare_pro_client()
        self._calendar_path = _calendar_path(self._provider_uri)
        self._instrument_dir = self._provider_uri / "instruments"
        self._features_dir = self._provider_uri / "features"

    def build_recent_data(
        self,
        *,
        target_date: date,
        universes: Iterable[str],
        lookback_days: int = 400,
    ) -> QlibBuildSummary:
        """Build recent daily qlib data for selected universes."""
        normalized_universes = [
            str(universe).strip().lower()
            for universe in universes
            if str(universe).strip()
        ]
        if not normalized_universes:
            raise ValueError("至少需要一个 universe")

        universe_members = self._fetch_universe_members(normalized_universes, target_date)
        return self._build_recent_data_for_members(
            target_date=target_date,
            universe_members=universe_members,
            lookback_days=lookback_days,
        )

    def build_recent_data_for_codes(
        self,
        *,
        target_date: date,
        stock_codes: Iterable[str],
        universe_id: str = "scoped_portfolios",
        lookback_days: int = 120,
    ) -> QlibBuildSummary:
        """Build recent daily qlib data for an explicit stock-code scope."""
        normalized_codes = sorted(
            {
                str(code).strip().upper()
                for code in stock_codes
                if str(code).strip() and "." in str(code).strip()
            }
        )
        if not normalized_codes:
            raise ValueError("至少需要一个股票代码")

        return self._build_recent_data_for_members(
            target_date=target_date,
            universe_members={str(universe_id).strip().lower(): normalized_codes},
            lookback_days=lookback_days,
        )

    def _build_recent_data_for_members(
        self,
        *,
        target_date: date,
        universe_members: dict[str, list[str]],
        lookback_days: int,
    ) -> QlibBuildSummary:
        """Build qlib data for already-resolved universe members."""
        latest_before = inspect_latest_trade_date(str(self._provider_uri))
        requested_start_date = target_date - timedelta(days=max(lookback_days, 90))

        stock_codes = sorted({code for members in universe_members.values() for code in members})
        if not stock_codes:
            raise RuntimeError("未从 Tushare 获取到任何股票池成分股")

        stock_daily = self._fetch_stock_daily(stock_codes, requested_start_date, target_date)
        if stock_daily.empty:
            raise RuntimeError("未获取到股票日线，无法构建 Qlib 数据")

        effective_target_date = stock_daily["trade_date"].max().date()
        if effective_target_date < target_date:
            logger.warning(
                "Qlib builder requested %s but latest available stock date is %s",
                target_date.isoformat(),
                effective_target_date.isoformat(),
            )

        stock_daily = stock_daily.loc[stock_daily["trade_date"] <= pd.Timestamp(effective_target_date)].copy()
        stock_adj = self._fetch_stock_adj_factor(stock_codes, requested_start_date, effective_target_date)
        scale_reference_adj_map: dict[str, float] = {}
        if latest_before is not None and latest_before < requested_start_date:
            scale_reference_df = self._fetch_stock_adj_factor(stock_codes, latest_before, latest_before)
            if not scale_reference_df.empty:
                latest_reference = (
                    scale_reference_df.sort_values("trade_date")
                    .groupby("ts_code")
                    .tail(1)
                )
                scale_reference_adj_map = {
                    row.ts_code: float(row.adj_factor)
                    for row in latest_reference.itertuples(index=False)
                    if pd.notna(row.adj_factor)
                }
        trade_days = self._fetch_trade_days(requested_start_date, effective_target_date)
        if not trade_days:
            raise RuntimeError("未获取到交易日历，无法构建 Qlib 数据")

        self._ensure_layout()
        calendar_days_written = self._upsert_calendar(trade_days)
        calendar_values = _read_calendar_values(self._calendar_path)
        calendar_index = {calendar_day: idx for idx, calendar_day in enumerate(calendar_values)}

        feature_series_written = 0
        for ts_code, frame in self._merge_stock_frame(stock_daily, stock_adj).groupby("ts_code"):
            written = self._write_stock_features(
                ts_code=ts_code,
                frame=frame.sort_values("trade_date").reset_index(drop=True),
                calendar_index=calendar_index,
                scale_reference_adj_map=scale_reference_adj_map,
            )
            feature_series_written += written

        for index_code in INDEX_CODES_FOR_BUILD:
            index_frame = self._fetch_index_daily(index_code, requested_start_date, effective_target_date)
            if index_frame.empty:
                continue
            written = self._write_index_features(
                ts_code=index_code,
                frame=index_frame.sort_values("trade_date").reset_index(drop=True),
                calendar_index=calendar_index,
            )
            feature_series_written += written

        instrument_files_written = self._upsert_instruments(
            universe_members=universe_members,
            stock_daily=stock_daily,
            effective_target_date=effective_target_date,
        )
        latest_after = inspect_latest_trade_date(str(self._provider_uri))

        warnings: list[str] = []
        if effective_target_date < target_date:
            warnings.append(
                f"Tushare 最新可用日线仅到 {effective_target_date.isoformat()}，"
                f"未达到请求日期 {target_date.isoformat()}。"
            )

        return QlibBuildSummary(
            requested_target_date=target_date,
            effective_target_date=effective_target_date,
            latest_local_date_before=latest_before,
            latest_local_date_after=latest_after,
            calendar_days_written=calendar_days_written,
            instrument_files_written=instrument_files_written,
            feature_series_written=feature_series_written,
            stock_count=len(stock_codes),
            universe_count=len(universe_members),
            warning_messages=tuple(warnings),
        )

    def _ensure_layout(self) -> None:
        self._calendar_path.parent.mkdir(parents=True, exist_ok=True)
        self._instrument_dir.mkdir(parents=True, exist_ok=True)
        self._features_dir.mkdir(parents=True, exist_ok=True)

    def _fetch_trade_days(self, start_date: date, end_date: date) -> list[date]:
        df = self._call_with_retry(
            self._pro.trade_cal,
            exchange="SSE",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            is_open="1",
        )
        if df is None or df.empty:
            return []
        normalized = df.copy()
        normalized["cal_date"] = pd.to_datetime(normalized["cal_date"], format="%Y%m%d")
        normalized = normalized.sort_values("cal_date")
        return [item.date() for item in normalized["cal_date"].tolist()]

    def _fetch_universe_members(
        self,
        universes: list[str],
        target_date: date,
    ) -> dict[str, list[str]]:
        start_date = (target_date - timedelta(days=60)).strftime("%Y%m%d")
        end_date = target_date.strftime("%Y%m%d")
        universe_members: dict[str, list[str]] = {}

        for universe in universes:
            index_code = UNIVERSE_INDEX_CODE_MAP.get(universe)
            if not index_code:
                logger.warning("Unsupported qlib universe for builder: %s", universe)
                continue

            try:
                df = self._call_with_retry(
                    self._pro.index_weight,
                    index_code=index_code,
                    start_date=start_date,
                    end_date=end_date,
                )
            except Exception as exc:
                logger.warning("Failed to fetch index_weight for %s: %s", universe, exc)
                continue
            if df is None or df.empty:
                logger.warning("No index_weight returned for %s", universe)
                continue

            normalized = df.copy()
            normalized["trade_date"] = pd.to_datetime(normalized["trade_date"], format="%Y%m%d")
            latest_weight_date = normalized["trade_date"].max()
            members = (
                normalized.loc[normalized["trade_date"] == latest_weight_date, "con_code"]
                .dropna()
                .astype(str)
                .sort_values()
                .unique()
                .tolist()
            )
            universe_members[universe] = members

        return universe_members

    def _fetch_stock_daily(
        self,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        rows: list[pd.DataFrame] = []
        for ts_code in stock_codes:
            try:
                df = self._call_with_retry(
                    self._pro.daily,
                    ts_code=ts_code,
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                )
            except Exception as exc:
                logger.warning("Failed to fetch daily for %s: %s", ts_code, exc)
                continue
            if df is None or df.empty:
                continue
            normalized = df.copy()
            normalized["trade_date"] = pd.to_datetime(normalized["trade_date"], format="%Y%m%d")
            rows.append(normalized)
        if not rows:
            return pd.DataFrame()
        return pd.concat(rows, ignore_index=True, sort=False)

    def _fetch_stock_adj_factor(
        self,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        rows: list[pd.DataFrame] = []
        for ts_code in stock_codes:
            try:
                df = self._call_with_retry(
                    self._pro.adj_factor,
                    ts_code=ts_code,
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                )
            except Exception as exc:
                logger.warning("Failed to fetch adj_factor for %s: %s", ts_code, exc)
                continue
            if df is None or df.empty:
                continue
            normalized = df.copy()
            normalized["trade_date"] = pd.to_datetime(normalized["trade_date"], format="%Y%m%d")
            rows.append(normalized)
        if not rows:
            return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])
        return pd.concat(rows, ignore_index=True, sort=False)

    def _fetch_index_daily(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        try:
            df = self._call_with_retry(
                self._pro.index_daily,
                ts_code=index_code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
        except Exception as exc:
            logger.warning("Failed to fetch index_daily for %s: %s", index_code, exc)
            return pd.DataFrame()
        if df is None or df.empty:
            return pd.DataFrame()

        normalized = df.copy()
        normalized["trade_date"] = pd.to_datetime(normalized["trade_date"], format="%Y%m%d")
        return normalized

    @staticmethod
    def _merge_stock_frame(
        stock_daily: pd.DataFrame,
        stock_adj: pd.DataFrame,
    ) -> pd.DataFrame:
        if stock_daily.empty:
            return pd.DataFrame()

        merged = stock_daily.merge(
            stock_adj[["ts_code", "trade_date", "adj_factor"]],
            on=["ts_code", "trade_date"],
            how="left",
        )
        merged["adj_factor"] = pd.to_numeric(merged["adj_factor"], errors="coerce")
        return merged

    def _write_stock_features(
        self,
        *,
        ts_code: str,
        frame: pd.DataFrame,
        calendar_index: dict[date, int],
        scale_reference_adj_map: dict[str, float],
    ) -> int:
        factor_series = pd.to_numeric(frame["adj_factor"], errors="coerce")
        if factor_series.notna().sum() == 0:
            return 0

        existing_scale = self._resolve_existing_stock_scale(ts_code, frame)
        if existing_scale is None:
            latest_adj_factor = float(factor_series.dropna().iloc[-1])
            if latest_adj_factor == 0:
                return 0
            scale_values = factor_series / latest_adj_factor
        else:
            reference_adj = scale_reference_adj_map.get(ts_code)
            if reference_adj is None:
                overlap_mask = factor_series.notna()
                if overlap_mask.sum() == 0:
                    return 0
                reference_adj = float(factor_series.loc[overlap_mask].iloc[0])
            base_denominator = reference_adj / existing_scale
            if base_denominator == 0:
                return 0
            scale_values = factor_series / base_denominator

        return self._write_feature_bundle(
            ts_code=ts_code,
            frame=frame,
            scale_values=scale_values,
            calendar_index=calendar_index,
            volume_multiplier=100.0,
        )

    def _write_index_features(
        self,
        *,
        ts_code: str,
        frame: pd.DataFrame,
        calendar_index: dict[date, int],
    ) -> int:
        existing_scale = self._read_existing_factor_scale(ts_code)
        if existing_scale is None:
            first_close = float(pd.to_numeric(frame["close"], errors="coerce").dropna().iloc[0])
            if first_close == 0:
                return 0
            scale_values = pd.Series(1.0 / first_close, index=frame.index, dtype="float64")
        else:
            scale_values = pd.Series(existing_scale, index=frame.index, dtype="float64")

        return self._write_feature_bundle(
            ts_code=ts_code,
            frame=frame,
            scale_values=scale_values,
            calendar_index=calendar_index,
            volume_multiplier=1.0,
        )

    def _write_feature_bundle(
        self,
        *,
        ts_code: str,
        frame: pd.DataFrame,
        scale_values: pd.Series,
        calendar_index: dict[date, int],
        volume_multiplier: float,
    ) -> int:
        feature_symbol = normalize_feature_symbol(ts_code)
        feature_dir = self._features_dir / feature_symbol
        feature_dir.mkdir(parents=True, exist_ok=True)

        bundle = frame.copy()
        bundle["trade_day"] = bundle["trade_date"].dt.date
        bundle["calendar_idx"] = bundle["trade_day"].map(calendar_index)
        bundle = bundle.dropna(subset=["calendar_idx"]).copy()
        if bundle.empty:
            return 0

        bundle["calendar_idx"] = bundle["calendar_idx"].astype(int)
        bundle["scale"] = pd.to_numeric(scale_values.loc[bundle.index], errors="coerce")
        bundle = bundle.dropna(subset=["scale"]).copy()
        if bundle.empty:
            return 0

        numeric_columns = ["open", "high", "low", "close", "vol", "pct_chg"]
        for column in numeric_columns:
            bundle[column] = pd.to_numeric(bundle[column], errors="coerce")

        factor_array = self._build_feature_array(bundle, "scale")
        open_array = self._build_feature_array(bundle, "open", scale_column="scale")
        high_array = self._build_feature_array(bundle, "high", scale_column="scale")
        low_array = self._build_feature_array(bundle, "low", scale_column="scale")
        close_array = self._build_feature_array(bundle, "close", scale_column="scale")
        change_array = self._build_feature_array(
            bundle,
            "pct_chg",
            post_process=lambda values, _: values / 100.0,
        )
        volume_array = self._build_feature_array(
            bundle,
            "vol",
            scale_column="scale",
            post_process=lambda values, scale: (values * volume_multiplier) / scale,
        )

        start_index = int(bundle["calendar_idx"].min())
        self._write_bin(feature_dir / "factor.day.bin", factor_array, start_index)
        self._write_bin(feature_dir / "open.day.bin", open_array, start_index)
        self._write_bin(feature_dir / "high.day.bin", high_array, start_index)
        self._write_bin(feature_dir / "low.day.bin", low_array, start_index)
        self._write_bin(feature_dir / "close.day.bin", close_array, start_index)
        self._write_bin(feature_dir / "change.day.bin", change_array, start_index)
        self._write_bin(feature_dir / "volume.day.bin", volume_array, start_index)
        return 7

    @staticmethod
    def _build_feature_array(
        frame: pd.DataFrame,
        value_column: str,
        *,
        scale_column: str | None = None,
        post_process: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
    ) -> np.ndarray:
        start_index = int(frame["calendar_idx"].min())
        end_index = int(frame["calendar_idx"].max())
        size = end_index - start_index + 1
        values = np.full(size, np.nan, dtype=np.float32)
        relative_index = frame["calendar_idx"].to_numpy(dtype=np.int64) - start_index
        raw_values = frame[value_column].to_numpy(dtype=np.float64)
        scale_values = frame["scale"].to_numpy(dtype=np.float64)
        if scale_column is not None:
            scale_values = frame[scale_column].to_numpy(dtype=np.float64)
        if post_process is None and scale_column is not None:
            raw_values = raw_values * scale_values
        elif post_process is not None:
            raw_values = post_process(raw_values, scale_values)
        values[relative_index] = raw_values.astype(np.float32)
        return values

    def _upsert_calendar(self, trade_days: list[date]) -> int:
        existing = _read_calendar_values(self._calendar_path)
        existing_set = set(existing)
        missing = [item for item in trade_days if item not in existing_set]
        combined = sorted(existing + missing)
        with self._calendar_path.open("w", encoding="utf-8") as fp:
            for item in combined:
                fp.write(f"{item.isoformat()}\n")
        return len(missing)

    def _upsert_instruments(
        self,
        *,
        universe_members: dict[str, list[str]],
        stock_daily: pd.DataFrame,
        effective_target_date: date,
    ) -> int:
        written = 0
        coverage = (
            stock_daily.groupby("ts_code")["trade_date"]
            .agg(["min", "max"])
            .reset_index()
        )
        coverage["min"] = coverage["min"].dt.date
        coverage["max"] = coverage["max"].dt.date
        coverage_map = {
            row.ts_code: (row.min, max(row.max, effective_target_date))
            for row in coverage.itertuples(index=False)
        }

        all_instruments = self._read_instrument_ranges("all")
        for universe, members in universe_members.items():
            ranges = self._read_instrument_ranges(universe)
            for member in members:
                if member not in coverage_map:
                    continue
                start_day, end_day = coverage_map[member]
                symbol = normalize_qlib_symbol(member)
                ranges[symbol] = _merge_ranges(ranges.get(symbol), start_day, end_day)
                all_instruments[symbol] = _merge_ranges(all_instruments.get(symbol), start_day, end_day)
            self._write_instrument_ranges(universe, ranges)
            written += 1

        self._write_instrument_ranges("all", all_instruments)
        written += 1
        return written

    def _read_instrument_ranges(self, market: str) -> dict[str, tuple[date, date]]:
        path = self._instrument_dir / f"{market.lower()}.txt"
        if not path.exists():
            return {}
        ranges: dict[str, tuple[date, date]] = {}
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                normalized = line.strip()
                if not normalized:
                    continue
                symbol, start_text, end_text = normalized.split("\t")[:3]
                ranges[symbol] = (
                    date.fromisoformat(start_text[:10]),
                    date.fromisoformat(end_text[:10]),
                )
        return ranges

    def _write_instrument_ranges(
        self,
        market: str,
        ranges: dict[str, tuple[date, date]],
    ) -> None:
        path = self._instrument_dir / f"{market.lower()}.txt"
        with path.open("w", encoding="utf-8") as fp:
            for symbol in sorted(ranges):
                start_day, end_day = ranges[symbol]
                fp.write(f"{symbol}\t{start_day.isoformat()}\t{end_day.isoformat()}\n")

    def _resolve_existing_stock_scale(
        self,
        ts_code: str,
        frame: pd.DataFrame,
    ) -> float | None:
        existing_scale = self._read_existing_factor_scale(ts_code)
        if existing_scale is None:
            return None
        return existing_scale

    def _read_existing_factor_scale(self, ts_code: str) -> float | None:
        factor_path = self._features_dir / normalize_feature_symbol(ts_code) / "factor.day.bin"
        if not factor_path.exists():
            return None
        values = np.fromfile(factor_path, dtype="<f")
        if values.size <= 1:
            return None
        factor_values = values[1:]
        non_nan = factor_values[~np.isnan(factor_values)]
        if non_nan.size == 0:
            return None
        return float(non_nan[-1])

    @staticmethod
    def _write_bin(path: Path, values: np.ndarray, start_index: int) -> None:
        existing_start: int | None = None
        existing_values = np.array([], dtype=np.float32)
        if path.exists():
            raw = np.fromfile(path, dtype="<f")
            if raw.size > 0:
                existing_start = int(raw[0])
                existing_values = raw[1:].astype(np.float32, copy=False)

        if existing_start is None:
            payload = np.hstack(([float(start_index)], values.astype(np.float32, copy=False)))
            payload.astype("<f").tofile(path)
            return

        end_index = existing_start + len(existing_values) - 1
        new_end_index = start_index + len(values) - 1
        merged_start = min(existing_start, start_index)
        merged_end = max(end_index, new_end_index)
        merged = np.full(merged_end - merged_start + 1, np.nan, dtype=np.float32)

        old_offset = existing_start - merged_start
        merged[old_offset: old_offset + len(existing_values)] = existing_values

        new_offset = start_index - merged_start
        candidate = values.astype(np.float32, copy=False)
        overwrite_mask = ~np.isnan(candidate)
        merged_slice = merged[new_offset: new_offset + len(candidate)]
        merged_slice[overwrite_mask] = candidate[overwrite_mask]
        merged[new_offset: new_offset + len(candidate)] = merged_slice

        payload = np.hstack(([float(merged_start)], merged))
        payload.astype("<f").tofile(path)

    @staticmethod
    def _call_with_retry(func, /, *args, retries: int = 3, delay_seconds: float = 0.6, **kwargs):
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= retries:
                    break
                time.sleep(delay_seconds * attempt)
        if last_error is not None:
            raise last_error
        raise RuntimeError("unexpected retry state")


def _merge_ranges(
    existing: tuple[date, date] | None,
    start_day: date,
    end_day: date,
) -> tuple[date, date]:
    if existing is None:
        return start_day, end_day
    return min(existing[0], start_day), max(existing[1], end_day)


def _calendar_path(provider_uri: Path) -> Path:
    return provider_uri / "calendars" / "day.txt"


def _read_calendar_values(path: Path) -> list[date]:
    if not path.exists():
        return []
    values: list[date] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            normalized = line.strip()
            if normalized:
                values.append(date.fromisoformat(normalized[:10]))
    return values
