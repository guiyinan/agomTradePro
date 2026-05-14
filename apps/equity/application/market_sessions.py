"""Market-session bootstrap helpers for equity detail pages."""

from __future__ import annotations

from dataclasses import dataclass

from apps.data_center.domain.enums import MarketExchange
from apps.equity.application.repository_provider import get_equity_stock_repository


@dataclass(frozen=True)
class MarketSessionWindow:
    """Single local trading session within a market day."""

    start: str
    end: str

    def to_dict(self) -> dict[str, str]:
        return {
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True)
class MarketSessionProfile:
    """Frontend bootstrap metadata for session-aware chart defaults."""

    exchange: str
    timezone: str
    sessions: tuple[MarketSessionWindow, ...]
    default_timeframe_in_session: str = "intraday"
    default_timeframe_out_of_session: str = "intraday"

    def to_dict(self) -> dict[str, object]:
        return {
            "exchange": self.exchange,
            "timezone": self.timezone,
            "sessions": [item.to_dict() for item in self.sessions],
            "default_timeframe_in_session": self.default_timeframe_in_session,
            "default_timeframe_out_of_session": self.default_timeframe_out_of_session,
        }


_MARKET_SESSION_PROFILES: dict[str, MarketSessionProfile] = {
    MarketExchange.SSE.value: MarketSessionProfile(
        exchange=MarketExchange.SSE.value,
        timezone="Asia/Shanghai",
        sessions=(
            MarketSessionWindow(start="09:30", end="11:30"),
            MarketSessionWindow(start="13:00", end="15:00"),
        ),
    ),
    MarketExchange.SZSE.value: MarketSessionProfile(
        exchange=MarketExchange.SZSE.value,
        timezone="Asia/Shanghai",
        sessions=(
            MarketSessionWindow(start="09:30", end="11:30"),
            MarketSessionWindow(start="13:00", end="15:00"),
        ),
    ),
    MarketExchange.BSE.value: MarketSessionProfile(
        exchange=MarketExchange.BSE.value,
        timezone="Asia/Shanghai",
        sessions=(
            MarketSessionWindow(start="09:30", end="11:30"),
            MarketSessionWindow(start="13:00", end="15:00"),
        ),
    ),
    MarketExchange.HKEX.value: MarketSessionProfile(
        exchange=MarketExchange.HKEX.value,
        timezone="Asia/Hong_Kong",
        sessions=(
            MarketSessionWindow(start="09:30", end="12:00"),
            MarketSessionWindow(start="13:00", end="16:00"),
        ),
    ),
    MarketExchange.NYSE.value: MarketSessionProfile(
        exchange=MarketExchange.NYSE.value,
        timezone="America/New_York",
        sessions=(MarketSessionWindow(start="09:30", end="16:00"),),
    ),
    MarketExchange.NASDAQ.value: MarketSessionProfile(
        exchange=MarketExchange.NASDAQ.value,
        timezone="America/New_York",
        sessions=(MarketSessionWindow(start="09:30", end="16:00"),),
    ),
    "XETRA": MarketSessionProfile(
        exchange="XETRA",
        timezone="Europe/Berlin",
        sessions=(MarketSessionWindow(start="09:00", end="17:30"),),
    ),
    "XFRA": MarketSessionProfile(
        exchange="XFRA",
        timezone="Europe/Berlin",
        sessions=(MarketSessionWindow(start="09:00", end="17:30"),),
    ),
    "FWB": MarketSessionProfile(
        exchange="FWB",
        timezone="Europe/Berlin",
        sessions=(MarketSessionWindow(start="09:00", end="17:30"),),
    ),
    MarketExchange.OTHER.value: MarketSessionProfile(
        exchange=MarketExchange.OTHER.value,
        timezone="UTC",
        sessions=(),
        default_timeframe_out_of_session="day",
    ),
}


def get_equity_detail_market_session_profile(
    stock_code: str,
    *,
    stock_repository=None,
) -> dict[str, object]:
    """Resolve the market-session profile used by the equity detail page."""

    repository = stock_repository or get_equity_stock_repository()
    exchange = ""
    if hasattr(repository, "get_listing_exchange"):
        exchange = str(repository.get_listing_exchange(stock_code) or "").upper()

    profile = _MARKET_SESSION_PROFILES.get(exchange)
    if profile is None:
        profile = _MARKET_SESSION_PROFILES[MarketExchange.OTHER.value]
    return profile.to_dict()
