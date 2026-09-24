"""Provider-backed mainland-China trading-session resolution."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from functools import lru_cache

from apps.data_center.domain.market_time import (
    CN_MARKET_TIMEZONE,
)
from apps.data_center.domain.market_time import (
    latest_closed_cn_market_session as _latest_closed_session,
)
from apps.data_center.domain.market_time import (
    latest_completed_cn_market_session as _latest_completed_session,
)
from apps.data_center.domain.model_market_data import (
    TradingCalendarEvidence,
    TradingCalendarEvidencePort,
)
from core.exceptions import AgomTradeProException, DataFetchError

logger = logging.getLogger(__name__)
CALENDAR_LOOKBACK_DAYS = 45
MAX_SESSION_GAP_DAYS = 14


@lru_cache(maxsize=32)
def load_cn_market_calendar_evidence(start_date: date, end_date: date) -> TradingCalendarEvidence:
    """Load source-bound exchange-calendar evidence through provider routing."""

    from apps.data_center.composition import build_model_market_data_service

    port = build_model_market_data_service()
    if not isinstance(port, TradingCalendarEvidencePort):
        raise DataFetchError(
            "Trading calendar evidence contract is unavailable",
            code="MODEL_MARKET_CALENDAR_EVIDENCE_UNAVAILABLE",
        )
    return port.trading_calendar_evidence(start_date, end_date)


def load_open_cn_market_sessions(start_date: date, end_date: date) -> tuple[date, ...]:
    """Load authoritative exchange sessions with complete bounded coverage."""

    evidence = load_cn_market_calendar_evidence(start_date, end_date)
    if evidence.coverage_start != start_date or evidence.coverage_end != end_date:
        raise DataFetchError(
            "Trading calendar coverage differs from the requested window",
            code="MODEL_MARKET_CALENDAR_COVERAGE_MISMATCH",
        )
    if not evidence.source.strip():
        raise DataFetchError(
            "Trading calendar source is missing",
            code="MODEL_MARKET_CALENDAR_SOURCE_MISSING",
        )
    return tuple(
        sorted(
            {
                item
                for item in evidence.open_sessions
                if evidence.coverage_start <= item <= evidence.coverage_end
            }
        )
    )


def _open_sessions_for(now: datetime) -> tuple[date, ...]:
    """Return a bounded exchange-calendar window or an empty fail-closed result."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("market clock must be timezone-aware")
    local_date = now.astimezone(CN_MARKET_TIMEZONE).date()
    start_date = local_date - timedelta(days=CALENDAR_LOOKBACK_DAYS)
    try:
        sessions = load_open_cn_market_sessions(start_date, local_date)
    except (
        AgomTradeProException,
        OSError,
        PermissionError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        logger.warning("Trading calendar unavailable: %s", type(exc).__name__)
        return ()
    if not sessions or (local_date - sessions[-1]).days > MAX_SESSION_GAP_DAYS:
        logger.warning("Trading calendar coverage is missing or stale")
        return ()
    return sessions


def latest_completed_cn_market_session(now: datetime) -> date | None:
    """Resolve the latest completed session from provider calendar evidence."""

    return _latest_completed_session(now, open_sessions=_open_sessions_for(now))


def latest_closed_cn_market_session(now: datetime) -> date | None:
    """Resolve the latest closed session from provider calendar evidence."""

    return _latest_closed_session(now, open_sessions=_open_sessions_for(now))


def latest_cn_market_session_ready_after(now: datetime, *, ready_after: time) -> date | None:
    """Resolve the latest exchange session whose post-close readiness time passed."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("market clock must be timezone-aware")
    local_now = now.astimezone(CN_MARKET_TIMEZONE)
    cutoff = (
        local_now.date()
        if local_now.time() >= ready_after
        else local_now.date() - timedelta(days=1)
    )
    eligible = tuple(session for session in _open_sessions_for(now) if session <= cutoff)
    return max(eligible) if eligible else None


__all__ = [
    "latest_closed_cn_market_session",
    "latest_cn_market_session_ready_after",
    "latest_completed_cn_market_session",
    "load_cn_market_calendar_evidence",
    "load_open_cn_market_sessions",
]
