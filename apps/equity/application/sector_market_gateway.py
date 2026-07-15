"""Equity-owned adapter for Sector benchmark returns."""

from __future__ import annotations

from datetime import date

from apps.sector.application.market_returns_gateway import register_market_returns_gateway

from .query_services import fetch_index_daily_returns


class EquityMarketReturnsGateway:
    def fetch_index_daily_returns(
        self, *, index_code: str, start_date: date, end_date: date, hydrate: bool = True
    ) -> dict:
        return fetch_index_daily_returns(
            index_code=index_code, start_date=start_date, end_date=end_date, hydrate=hydrate
        )


def register_sector_market_gateway() -> None:
    register_market_returns_gateway(EquityMarketReturnsGateway())


__all__ = ["EquityMarketReturnsGateway", "register_sector_market_gateway"]
