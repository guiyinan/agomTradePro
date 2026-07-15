"""Sector-owned gateway for benchmark market returns."""

from __future__ import annotations

from datetime import date
from typing import Protocol


class MarketReturnsGateway(Protocol):
    def fetch_index_daily_returns(
        self, *, index_code: str, start_date: date, end_date: date, hydrate: bool = True
    ) -> dict: ...


class EmptyMarketReturnsGateway:
    def fetch_index_daily_returns(
        self, *, index_code: str, start_date: date, end_date: date, hydrate: bool = True
    ) -> dict:
        del index_code, start_date, end_date, hydrate
        return {}


_gateway: MarketReturnsGateway = EmptyMarketReturnsGateway()


def register_market_returns_gateway(gateway: MarketReturnsGateway) -> None:
    global _gateway
    _gateway = gateway


def fetch_index_daily_returns(
    *, index_code: str, start_date: date, end_date: date, hydrate: bool = True
) -> dict:
    return _gateway.fetch_index_daily_returns(
        index_code=index_code, start_date=start_date, end_date=end_date, hydrate=hydrate
    )


__all__ = ["MarketReturnsGateway", "fetch_index_daily_returns", "register_market_returns_gateway"]
