"""Repository protocols consumed by equity application use cases."""

from datetime import date
from decimal import Decimal
from typing import Protocol

from apps.equity.domain.entities import (
    FinancialData,
    IntradayPricePoint,
    ScoringWeightConfig,
    StockInfo,
    TechnicalBar,
    ValuationMetrics,
)
from apps.regime.domain.entities import RegimeSnapshot


class EquityStockReadRepositoryProtocol(Protocol):
    """Read contract used by equity analysis application use cases."""

    def get_stock_info(self, stock_code: str) -> StockInfo | None: ...

    def get_all_stocks_with_fundamentals(
        self,
        as_of_date: date | None = None,
    ) -> list[tuple[StockInfo, FinancialData, ValuationMetrics]]: ...

    def get_technical_bars(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        *,
        hydrate: bool = False,
        published_only: bool = False,
        publication_key: str = "current",
    ) -> list[TechnicalBar]: ...

    def get_intraday_points(self, stock_code: str) -> list[IntradayPricePoint]: ...

    def get_last_intraday_source(self) -> str | None: ...

    def get_valuation_history(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        *,
        hydrate: bool = False,
        published_only: bool = False,
        publication_key: str = "current",
    ) -> list[ValuationMetrics]: ...

    def get_latest_financial_data(
        self,
        stock_code: str,
        *,
        hydrate: bool = False,
        published_only: bool = True,
        publication_key: str = "current",
    ) -> FinancialData | None: ...

    def get_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        *,
        hydrate: bool = False,
        published_only: bool = False,
        publication_key: str = "current",
    ) -> list[tuple[date, Decimal]]: ...

    def calculate_daily_returns(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        *,
        hydrate: bool = False,
        published_only: bool = False,
        publication_key: str = "current",
    ) -> dict[date, float]: ...


class RegimeHistoryRepositoryProtocol(Protocol):
    """Historical regime snapshots required by correlation analysis."""

    def get_snapshots_in_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[RegimeSnapshot]: ...


class ScoringWeightConfigRepositoryProtocol(Protocol):
    """Read contract for the active database-backed scoring weights."""

    def get_active_config(self) -> ScoringWeightConfig: ...
