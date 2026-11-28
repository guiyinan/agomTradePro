"""Fetch target-session Tushare prices and classify dated suspension records."""

from __future__ import annotations

import logging
from datetime import date
from typing import Protocol

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from core.exceptions import DataFetchError

logger = logging.getLogger(__name__)
_PUBLIC_ERRORS = frozenset(
    {
        "TUSHARE_PROVIDER_REJECTED",
        "TUSHARE_INVALID_PAYLOAD",
        "TUSHARE_DATA_NOT_YET_AVAILABLE",
        "TUSHARE_REDIRECT_BLOCKED",
        "TUSHARE_PROVIDER_RESPONSE_CAPTURE_UNAVAILABLE",
        "MODEL_MARKET_INCOMPLETE_RESULT",
    }
)


class _SessionQuery(Protocol):
    def __call__(self, *, trade_date: str) -> pd.DataFrame | None: ...


def join_daily_factor_rows(
    daily_rows: pd.DataFrame, factor_rows: pd.DataFrame, *, duplicate_code: str, missing_code: str
) -> pd.DataFrame:
    """Join only daily keys and require one finite, positive factor for each."""
    keys = ["ts_code", "trade_date"]
    daily_keys = daily_rows.loc[:, keys].drop_duplicates()
    matching_factors = factor_rows.merge(daily_keys, on=keys, how="inner")
    if matching_factors.duplicated(keys).any():
        raise DataFetchError(
            "Provider returned duplicate adjustment factors for a price row", code=duplicate_code
        )
    joined = daily_rows.merge(
        matching_factors.loc[:, [*keys, "adj_factor"]], on=keys, how="left", validate="many_to_one"
    )
    factor_values = pd.to_numeric(joined["adj_factor"], errors="coerce")
    if not np.isfinite(factor_values).all() or (factor_values <= 0).any():
        raise DataFetchError(
            "Provider price row lacks one finite, positive adjustment factor", code=missing_code
        )
    return joined


def full_day_suspensions(
    frame: pd.DataFrame | None,
    asset_codes: tuple[str, ...],
    start_date: date,
    end_date: date,
    *,
    target_batch: bool = False,
) -> dict[str, tuple[date, ...]]:
    """Keep only unique explicit S records with empty timing for each requested code and day."""
    fields = ("ts_code", "trade_date", "suspend_type", "suspend_timing")
    if (
        frame is None
        or frame.empty
        or not frame.columns.is_unique
        or not set(fields).issubset(frame.columns)
    ):
        return {}
    requested = set(asset_codes)
    seen: set[tuple[str, date]] = set()
    ambiguous: set[tuple[str, date]] = set()
    for code, stamp, kind, timing in frame.loc[:, list(fields)].itertuples(index=False, name=None):
        if not isinstance(code, str) or code not in requested:
            if target_batch:
                raise DataFetchError(
                    "Suspension response exceeds the requested scope",
                    code="MODEL_MARKET_SESSION_SCOPE_INVALID",
                )
            continue
        if target_batch and (not isinstance(stamp, str) or stamp != start_date.strftime("%Y%m%d")):
            ambiguous.add((code, start_date))
            continue
        if not pd.api.types.is_scalar(stamp):
            continue
        observed = pd.to_datetime(stamp, format="%Y%m%d", errors="coerce")
        if pd.isna(observed) or not start_date <= observed.date() <= end_date:
            continue
        key = (code, observed.date())
        if (
            key in seen
            or not isinstance(kind, str)
            or kind != "S"
            or not (
                pd.api.types.is_scalar(timing)
                and pd.isna(timing)
                or isinstance(timing, str)
                and not timing.strip()
            )
        ):
            ambiguous.add(key)
        seen.add(key)
    proven: dict[str, list[date]] = {}
    for code, day in sorted(seen - ambiguous):
        proven.setdefault(code, []).append(day)
    return {code: tuple(days) for code, days in proven.items()}


def fetch_tushare_price_session(
    day: date, *, daily: _SessionQuery, adj_factor: _SessionQuery
) -> tuple[date, pd.DataFrame | None, pd.DataFrame | None, tuple[str, Exception] | None]:
    """Return the two SDK tables, or the endpoint and exception of the first failed read."""
    session = day.strftime("%Y%m%d")
    endpoint = "daily"
    try:
        prices = daily(trade_date=session)
        endpoint = "adj_factor"
        factors = adj_factor(trade_date=session)
        return day, prices, factors, None
    except Exception as error:
        code = error.code if isinstance(error, DataFetchError) else None
        logger.warning(
            "Model history session fetch failed: endpoint=%s trade_date=%s code=%s",
            endpoint,
            day,
            code if code in _PUBLIC_ERRORS else "MODEL_MARKET_PROVIDER_FETCH_FAILED",
        )
        return day, None, None, (endpoint, error)
