from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast

import numpy as np

from apps.alpha.infrastructure.scientific_runtime import get_pandas
from apps.config_center.application import interface_services as config_center_services
from apps.config_center.domain.entities import AlphaUniverseConfig
from apps.data_center.application.public import get_tushare_client

logger = logging.getLogger(__name__)
pd = get_pandas()
_T = TypeVar("_T")
PandasDataFrame = Any
PandasSeries = Any


class _TushareProClient(Protocol):
    def trade_cal(self, **kwargs: object) -> Any: ...
    def index_weight(self, **kwargs: object) -> Any: ...
    def daily(self, **kwargs: object) -> Any: ...
    def adj_factor(self, **kwargs: object) -> Any: ...
    def index_daily(self, **kwargs: object) -> Any: ...


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
    normalized = _normalize_tushare_code(ts_code)
    if normalized is None:
        raise ValueError("Invalid Tushare instrument code")
    code, market = normalized.split(".", 1)
    return f"{market.upper()}{code}"


def normalize_feature_symbol(ts_code: str) -> str:
    """Convert tushare code into qlib feature directory symbol."""
    normalized = _normalize_tushare_code(ts_code)
    if normalized is None:
        raise ValueError("Invalid Tushare instrument code")
    code, market = normalized.split(".", 1)
    return f"{market.lower()}{code}"


def denormalize_qlib_symbol(symbol: str) -> str | None:
    """Convert a qlib instrument symbol into a tushare code."""
    normalized = str(symbol or "").strip().upper()
    if len(normalized) < 3:
        return None
    market = normalized[:2]
    code = normalized[2:]
    if market not in {"SH", "SZ", "BJ"} or not code.isdigit():
        return None
    return f"{code}.{market}"


def _normalize_tushare_code(raw_code: object) -> str | None:
    normalized = str(raw_code or "").strip().upper()
    if re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", normalized) is None:
        return None
    return normalized


def _normalize_universe_id(raw_universe_id: object) -> str | None:
    normalized = str(raw_universe_id or "").strip().lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", normalized) is None:
        return None
    return normalized


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
        self._pro = cast(
            _TushareProClient,
            pro_client if pro_client is not None else get_tushare_client(),
        )
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
        self._validate_build_window(target_date, lookback_days)
        normalized_universes: list[str] = []
        for universe in universes:
            normalized = _normalize_universe_id(universe)
            if normalized is None:
                raise ValueError("Universe ID must use 1-64 lowercase letters, digits, _ or -")
            normalized_universes.append(normalized)
        if not normalized_universes:
            raise ValueError("至少需要一个 universe")

        universe_members, index_codes = self._fetch_universe_members(
            sorted(set(normalized_universes)),
            target_date,
        )
        return self._build_recent_data_for_members(
            target_date=target_date,
            universe_members=universe_members,
            lookback_days=lookback_days,
            index_codes=index_codes,
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
        self._validate_build_window(target_date, lookback_days)
        normalized_universe_id = _normalize_universe_id(universe_id)
        if normalized_universe_id is None:
            raise ValueError("Universe ID must use 1-64 lowercase letters, digits, _ or -")

        normalized_codes: set[str] = set()
        for code in stock_codes:
            normalized_code = _normalize_tushare_code(code)
            if normalized_code is None:
                raise ValueError("Stock codes must use the 000001.SZ Tushare format")
            normalized_codes.add(normalized_code)
        if not normalized_codes:
            raise ValueError("至少需要一个股票代码")

        return self._build_recent_data_for_members(
            target_date=target_date,
            universe_members={normalized_universe_id: sorted(normalized_codes)},
            lookback_days=lookback_days,
            index_codes=(),
        )

    @staticmethod
    def _validate_build_window(target_date: date, lookback_days: int) -> None:
        if target_date > date.today():
            raise ValueError("Qlib build target_date cannot be in the future")
        if (
            isinstance(lookback_days, bool)
            or not isinstance(lookback_days, int)
            or lookback_days <= 0
            or lookback_days > 3650
        ):
            raise ValueError("Qlib build lookback_days must be an integer from 1 to 3650")

    def _build_recent_data_for_members(
        self,
        *,
        target_date: date,
        universe_members: dict[str, list[str]],
        lookback_days: int,
        index_codes: Iterable[str],
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

        stock_daily = stock_daily.loc[
            stock_daily["trade_date"] <= pd.Timestamp(effective_target_date)
        ].copy()
        stock_adj = self._fetch_stock_adj_factor(
            stock_codes, requested_start_date, effective_target_date
        )
        scale_reference_adj_map: dict[str, float] = {}
        if latest_before is not None and latest_before < requested_start_date:
            scale_reference_df = self._fetch_stock_adj_factor(
                stock_codes, latest_before, latest_before
            )
            if not scale_reference_df.empty:
                latest_reference = (
                    scale_reference_df.sort_values("trade_date").groupby("ts_code").tail(1)
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

        for index_code in sorted(set(index_codes)):
            index_frame = self._fetch_index_daily(
                index_code, requested_start_date, effective_target_date
            )
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
        if "cal_date" not in df.columns:
            logger.warning("Invalid trade calendar schema returned by provider")
            return []
        normalized = df.copy()
        normalized["cal_date"] = pd.to_datetime(
            normalized["cal_date"],
            format="%Y%m%d",
            errors="coerce",
        )
        normalized = normalized.loc[
            normalized["cal_date"].notna()
            & (normalized["cal_date"] >= pd.Timestamp(start_date))
            & (normalized["cal_date"] <= pd.Timestamp(end_date))
        ]
        normalized = normalized.sort_values("cal_date")
        return [item.date() for item in normalized["cal_date"].tolist()]

    def _fetch_universe_members(
        self,
        universes: list[str],
        target_date: date,
    ) -> tuple[dict[str, list[str]], list[str]]:
        universe_members: dict[str, list[str]] = {}
        index_codes: set[str] = set()

        for universe in universes:
            try:
                config = config_center_services.get_alpha_universe_config(universe)
            except Exception as exc:
                logger.warning(
                    "Failed to load qlib universe %s from Config Center: %s",
                    universe,
                    type(exc).__name__,
                )
                continue
            if config is None:
                logger.warning("Unsupported qlib universe for builder: %s", universe)
                continue

            if config.source_type != "tushare_index":
                members = self._resolve_configured_universe_members(config)
                if members:
                    universe_members[universe] = members
                continue

            index_code = _normalize_tushare_code(config.filters.get("index_code"))
            if index_code is None:
                logger.warning("Invalid index code configured for qlib universe %s", universe)
                continue
            index_codes.add(index_code)
            members = self._fetch_index_weight_members(
                universe=universe,
                index_code=index_code,
                target_date=target_date,
            )
            if not members:
                members = self._load_local_universe_members(universe)
                if members:
                    logger.warning(
                        "Using local qlib instruments fallback for %s: %s members",
                        universe,
                        len(members),
                    )
            if members:
                universe_members[universe] = members

        return universe_members, sorted(index_codes)

    def _fetch_index_weight_members(
        self,
        *,
        universe: str,
        index_code: str,
        target_date: date,
    ) -> list[str]:
        """Fetch the latest effective constituents for one configured index."""
        try:
            frame = self._call_with_retry(
                self._pro.index_weight,
                index_code=index_code,
                start_date=(target_date - timedelta(days=140)).strftime("%Y%m%d"),
                end_date=target_date.strftime("%Y%m%d"),
            )
        except PermissionError:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to fetch index_weight for %s: %s",
                universe,
                type(exc).__name__,
            )
            return []
        if frame is None or frame.empty:
            logger.warning("No index_weight returned for %s", universe)
            return []
        if not {"trade_date", "con_code"}.issubset(frame.columns):
            logger.warning("Invalid index_weight schema returned for %s", universe)
            return []

        normalized = frame.copy()
        normalized["trade_date"] = pd.to_datetime(
            normalized["trade_date"],
            format="%Y%m%d",
            errors="coerce",
        )
        normalized = normalized.loc[
            normalized["trade_date"].notna()
            & (normalized["trade_date"] <= pd.Timestamp(target_date))
        ]
        if normalized.empty:
            return []
        latest_weight_date = normalized["trade_date"].max()
        members = {
            code
            for raw_code in normalized.loc[
                normalized["trade_date"] == latest_weight_date,
                "con_code",
            ].tolist()
            if (code := _normalize_tushare_code(raw_code)) is not None
        }
        return sorted(members)

    @staticmethod
    def _resolve_configured_universe_members(config: AlphaUniverseConfig) -> list[str]:
        """Resolve a Config Center-managed non-index Alpha/Qlib universe."""
        try:
            raw_members = config_center_services.resolve_alpha_universe_member_codes(
                config.universe_id
            )
        except Exception as exc:
            logger.warning(
                "Failed to resolve configured qlib universe %s: %s",
                config.universe_id,
                type(exc).__name__,
            )
            return []
        members = sorted(
            {
                code
                for raw_code in raw_members
                if (code := _normalize_tushare_code(raw_code)) is not None
            }
        )
        if members:
            logger.info(
                "Resolved custom qlib universe %s from Config Center: %s members",
                config.universe_id,
                len(members),
            )
        return members

    def _load_local_universe_members(self, universe: str) -> list[str]:
        """Load existing qlib instrument members when index_weight is rate-limited."""
        instrument_path = self._instrument_dir / f"{universe}.txt"
        if not instrument_path.exists():
            return []

        members: set[str] = set()
        with instrument_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                raw_symbol = line.strip().split("\t", 1)[0]
                ts_code = denormalize_qlib_symbol(raw_symbol)
                if ts_code:
                    members.add(ts_code)
        return sorted(members)

    def _fetch_stock_daily(
        self,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> PandasDataFrame:
        rows: list[PandasDataFrame] = []
        for ts_code in stock_codes:
            try:
                df = self._call_with_retry(
                    self._pro.daily,
                    ts_code=ts_code,
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                )
            except PermissionError:
                raise
            except Exception as exc:
                logger.warning(
                    "Failed to fetch daily for %s: %s",
                    ts_code,
                    type(exc).__name__,
                )
                continue
            if df is None or df.empty:
                continue
            normalized = self._normalize_daily_frame(
                df,
                requested_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            if normalized.empty:
                continue
            rows.append(normalized)
        if not rows:
            return pd.DataFrame()
        return pd.concat(rows, ignore_index=True, sort=False)

    def _fetch_stock_adj_factor(
        self,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> PandasDataFrame:
        rows: list[PandasDataFrame] = []
        for ts_code in stock_codes:
            try:
                df = self._call_with_retry(
                    self._pro.adj_factor,
                    ts_code=ts_code,
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                )
            except PermissionError:
                raise
            except Exception as exc:
                logger.warning(
                    "Failed to fetch adj_factor for %s: %s",
                    ts_code,
                    type(exc).__name__,
                )
                continue
            if df is None or df.empty:
                continue
            if not {"ts_code", "trade_date", "adj_factor"}.issubset(df.columns):
                logger.warning("Invalid adj_factor schema returned for %s", ts_code)
                continue
            normalized = df.copy()
            normalized["trade_date"] = pd.to_datetime(
                normalized["trade_date"],
                format="%Y%m%d",
                errors="coerce",
            )
            normalized["adj_factor"] = pd.to_numeric(
                normalized["adj_factor"],
                errors="coerce",
            )
            normalized["ts_code"] = normalized["ts_code"].map(_normalize_tushare_code)
            normalized = normalized.loc[
                normalized["trade_date"].notna()
                & (normalized["trade_date"] >= pd.Timestamp(start_date))
                & (normalized["trade_date"] <= pd.Timestamp(end_date))
                & (normalized["ts_code"] == ts_code)
                & np.isfinite(normalized["adj_factor"])
                & (normalized["adj_factor"] > 0)
            ]
            if normalized.empty:
                continue
            rows.append(normalized)
        if not rows:
            return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])
        return pd.concat(rows, ignore_index=True, sort=False)

    def _fetch_index_daily(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> PandasDataFrame:
        try:
            df = self._call_with_retry(
                self._pro.index_daily,
                ts_code=index_code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
        except PermissionError:
            raise
        except Exception as exc:
            logger.warning(
                "Failed to fetch index_daily for %s: %s",
                index_code,
                type(exc).__name__,
            )
            return pd.DataFrame()
        if df is None or df.empty:
            return pd.DataFrame()
        return self._normalize_daily_frame(
            df,
            requested_code=index_code,
            start_date=start_date,
            end_date=end_date,
        )

    @staticmethod
    def _normalize_daily_frame(
        frame: PandasDataFrame,
        *,
        requested_code: str,
        start_date: date,
        end_date: date,
    ) -> PandasDataFrame:
        """Validate provider daily rows before they affect Qlib availability."""
        required_columns = {
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "vol",
            "pct_chg",
        }
        if not required_columns.issubset(frame.columns):
            logger.warning("Invalid daily schema returned for %s", requested_code)
            return pd.DataFrame()

        normalized = frame.copy()
        normalized["ts_code"] = normalized["ts_code"].map(_normalize_tushare_code)
        normalized["trade_date"] = pd.to_datetime(
            normalized["trade_date"],
            format="%Y%m%d",
            errors="coerce",
        )
        numeric_columns = ["open", "high", "low", "close", "vol", "pct_chg"]
        for column in numeric_columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

        finite_prices = np.isfinite(normalized[["open", "high", "low", "close"]]).all(axis=1)
        valid_prices = (
            finite_prices
            & (normalized[["open", "high", "low", "close"]] > 0).all(axis=1)
            & (normalized["high"] >= normalized[["open", "low", "close"]].max(axis=1))
            & (normalized["low"] <= normalized[["open", "high", "close"]].min(axis=1))
        )
        valid_volume = np.isfinite(normalized["vol"]) & (normalized["vol"] >= 0)
        valid_change = np.isfinite(normalized["pct_chg"])
        return normalized.loc[
            normalized["trade_date"].notna()
            & (normalized["trade_date"] >= pd.Timestamp(start_date))
            & (normalized["trade_date"] <= pd.Timestamp(end_date))
            & (normalized["ts_code"] == requested_code)
            & valid_prices
            & valid_volume
            & valid_change
        ].copy()

    @staticmethod
    def _merge_stock_frame(
        stock_daily: PandasDataFrame,
        stock_adj: PandasDataFrame,
    ) -> PandasDataFrame:
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
        frame: PandasDataFrame,
        calendar_index: dict[date, int],
        scale_reference_adj_map: dict[str, float],
    ) -> int:
        factor_series = pd.to_numeric(frame["adj_factor"], errors="coerce")
        factor_series = factor_series.where(np.isfinite(factor_series) & (factor_series > 0))
        if factor_series.notna().sum() == 0:
            return 0

        existing_scale = self._resolve_existing_stock_scale(ts_code, frame)
        if existing_scale is None:
            latest_adj_factor = float(factor_series.dropna().iloc[-1])
            if not math.isfinite(latest_adj_factor) or latest_adj_factor <= 0:
                return 0
            scale_values = factor_series / latest_adj_factor
        else:
            if not math.isfinite(existing_scale) or existing_scale <= 0:
                return 0
            reference_adj = scale_reference_adj_map.get(ts_code)
            if reference_adj is None:
                overlap_mask = factor_series.notna()
                if overlap_mask.sum() == 0:
                    return 0
                reference_adj = float(factor_series.loc[overlap_mask].iloc[0])
            if not math.isfinite(reference_adj) or reference_adj <= 0:
                return 0
            base_denominator = reference_adj / existing_scale
            if not math.isfinite(base_denominator) or base_denominator <= 0:
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
        frame: PandasDataFrame,
        calendar_index: dict[date, int],
    ) -> int:
        existing_scale = self._read_existing_factor_scale(ts_code)
        if existing_scale is None:
            close_values = pd.to_numeric(frame["close"], errors="coerce")
            close_values = close_values.where(
                np.isfinite(close_values) & (close_values > 0)
            ).dropna()
            if close_values.empty:
                return 0
            first_close = float(close_values.iloc[0])
            if not math.isfinite(first_close) or first_close <= 0:
                return 0
            scale_values = pd.Series(1.0 / first_close, index=frame.index, dtype="float64")
        else:
            if not math.isfinite(existing_scale) or existing_scale <= 0:
                return 0
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
        frame: PandasDataFrame,
        scale_values: PandasSeries,
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
        bundle = bundle.loc[np.isfinite(bundle["scale"]) & (bundle["scale"] > 0)].copy()
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
        frame: PandasDataFrame,
        value_column: str,
        *,
        scale_column: str | None = None,
        post_process: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
    ) -> np.ndarray:
        start_index = int(frame["calendar_idx"].min())
        end_index = int(frame["calendar_idx"].max())
        size = end_index - start_index + 1
        values: np.ndarray = np.full(size, np.nan, dtype=np.float32)
        relative_index = frame["calendar_idx"].to_numpy(dtype=np.int64) - start_index
        raw_values = frame[value_column].to_numpy(dtype=np.float64)
        scale_values = frame["scale"].to_numpy(dtype=np.float64)
        if scale_column is not None:
            scale_values = frame[scale_column].to_numpy(dtype=np.float64)
        if post_process is None and scale_column is not None:
            raw_values = raw_values * scale_values
        elif post_process is not None:
            raw_values = post_process(raw_values, scale_values)
        raw_values = np.where(np.isfinite(raw_values), raw_values, np.nan)
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
        stock_daily: PandasDataFrame,
        effective_target_date: date,
    ) -> int:
        written = 0
        coverage = stock_daily.groupby("ts_code")["trade_date"].agg(["min", "max"]).reset_index()
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
                all_instruments[symbol] = _merge_ranges(
                    all_instruments.get(symbol), start_day, end_day
                )
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
        frame: PandasDataFrame,
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
        merged: np.ndarray = np.full(
            merged_end - merged_start + 1,
            np.nan,
            dtype=np.float32,
        )

        old_offset = existing_start - merged_start
        merged[old_offset : old_offset + len(existing_values)] = existing_values

        new_offset = start_index - merged_start
        candidate: np.ndarray = values.astype(np.float32, copy=False)
        overwrite_mask = ~np.isnan(candidate)
        merged_slice = merged[new_offset : new_offset + len(candidate)]
        merged_slice[overwrite_mask] = candidate[overwrite_mask]
        merged[new_offset : new_offset + len(candidate)] = merged_slice

        payload = np.hstack(([float(merged_start)], merged))
        payload.astype("<f").tofile(path)

    @staticmethod
    def _call_with_retry(
        func: Callable[..., _T],
        /,
        *args: object,
        retries: int = 3,
        delay_seconds: float = 0.6,
        **kwargs: object,
    ) -> _T:
        if isinstance(retries, bool) or retries <= 0:
            raise ValueError("retries must be a positive integer")
        if not math.isfinite(delay_seconds) or delay_seconds < 0:
            raise ValueError("delay_seconds must be finite and non-negative")
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                return func(*args, **kwargs)
            except PermissionError:
                raise
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
