"""Fetch a dated Tushare daily/factor pair and attribute a failed request."""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Protocol

from core.exceptions import DataFetchError

if TYPE_CHECKING:
    import pandas as pd  # type: ignore[import-untyped]

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
