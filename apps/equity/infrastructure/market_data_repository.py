"""Daily price and technical-bar slice of the equity stock repository.

This module owns the `StockMarketDataRepositoryMixin` slice of
`DjangoStockRepository`, including remote gateway fallbacks and technical
indicator recalculation. Shared helpers and dependency wiring live in
`stock_repository.py`; do not import the compatibility facade here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.data_center.application.public import (
    get_model_market_data_port,
    get_published_price_bar_series,
)
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.model_market_data import ModelDailyBar
from apps.data_center.domain.protocols import PriceBarRepositoryProtocol
from apps.equity.domain.entities import TechnicalBar
from core.exceptions import DataFetchError
from shared.numeric import safe_float

logger = logging.getLogger(__name__)


_HistoricalPriceBar = ModelDailyBar


if TYPE_CHECKING:
    from apps.data_center.application.on_demand import OnDemandDataCenterService


class StockMarketDataRepositoryMixin:
    """Daily prices, technical bars, and remote market-data fallbacks."""

    _dc_on_demand: OnDemandDataCenterService
    _dc_price_bar_repo: PriceBarRepositoryProtocol

    if TYPE_CHECKING:

        def _safe_decimal(self, value: object) -> Decimal | None: ...

        def _to_akshare_symbol(self, stock_code: str) -> str: ...

    def get_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        *,
        hydrate: bool = False,
        published_only: bool = False,
        publication_key: str = "current",
    ) -> list[tuple[date, Decimal]]:
        """
        获取股票的日线收盘价数据

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            [(日期, 收盘价), ...]，按日期升序排列
        """
        if published_only:
            return self._get_published_daily_prices(
                stock_code,
                start_date=start_date,
                end_date=end_date,
                publication_key=publication_key,
            )

        dc_bars = (
            self._dc_on_demand.ensure_price_bars(stock_code, start_date, end_date).records
            if hydrate
            else self._dc_price_bar_repo.get_bars(
                stock_code,
                start=start_date,
                end=end_date,
                limit=max((end_date - start_date).days + 10, 120),
            )
        )
        if dc_bars:
            dc_prices = [
                (bar.bar_date, Decimal(str(bar.close)))
                for bar in sorted(dc_bars, key=lambda item: item.bar_date)
            ]
            if self._has_sufficient_price_coverage(
                dc_prices, start_date=start_date, end_date=end_date
            ):
                return dc_prices

        return self._get_remote_daily_prices(stock_code, start_date, end_date)

    @staticmethod
    def _get_published_daily_prices(
        stock_code: str,
        *,
        start_date: date,
        end_date: date,
        publication_key: str,
    ) -> list[tuple[date, Decimal]]:
        """Read daily prices only from a publication-bound price-bar series."""

        payload = get_published_price_bar_series(
            stock_code,
            publication_key=publication_key,
            start=start_date,
            end=end_date,
            limit=max((end_date - start_date).days + 10, 120),
        )
        if bool(payload.get("must_not_use_for_decision")):
            return []
        rows = payload.get("rows", [])
        if not isinstance(rows, (list, tuple)):
            return []
        prices_by_date: dict[date, Decimal] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            raw_date = row.get("timestamp", row.get("bar_date"))
            if not isinstance(raw_date, str) or not raw_date.strip():
                continue
            try:
                bar_date = date.fromisoformat(raw_date.strip()[:10])
            except ValueError:
                continue
            raw_fetched_at = row.get("fetched_at")
            if not isinstance(raw_fetched_at, str) or not raw_fetched_at.strip():
                continue
            try:
                fetched_at = datetime.fromisoformat(raw_fetched_at.strip().replace("Z", "+00:00"))
            except ValueError:
                continue
            if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
                continue
            close = safe_float(row.get("close"), default=None)
            if close is None or close <= 0:
                continue
            prices_by_date[bar_date] = Decimal(str(close))
        return sorted(prices_by_date.items(), key=lambda item: item[0])

    def get_technical_bars(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        *,
        hydrate: bool = False,
        published_only: bool = False,
        publication_key: str = "current",
    ) -> list[TechnicalBar]:
        """获取K线与技术指标序列。"""
        if published_only:
            return self._get_published_technical_bars(
                stock_code,
                start_date=start_date,
                end_date=end_date,
                publication_key=publication_key,
            )

        dc_bars = (
            self._dc_on_demand.ensure_price_bars(stock_code, start_date, end_date).records
            if hydrate
            else self._dc_price_bar_repo.get_bars(
                stock_code,
                start=start_date,
                end=end_date,
                limit=max((end_date - start_date).days + 10, 120),
            )
        )
        best_available_bars: list[TechnicalBar] = []
        if dc_bars:
            best_available_bars = self._price_bars_to_technical_bars(stock_code, dc_bars)
            if self._has_sufficient_bar_coverage(
                best_available_bars, start_date=start_date, end_date=end_date
            ):
                return best_available_bars

        try:
            remote_bars = self._get_remote_historical_bars(stock_code, start_date, end_date)
        except DataFetchError:
            if best_available_bars:
                return best_available_bars
            raise
        remote_technical_bars = self._recalculate_technical_bars(
            [
                TechnicalBar(
                    stock_code=stock_code,
                    trade_date=bar.trade_date,
                    open=Decimal(str(bar.open)),
                    high=Decimal(str(bar.high)),
                    low=Decimal(str(bar.low)),
                    close=Decimal(str(bar.close)),
                    volume=int(bar.volume) if bar.volume is not None else 0,
                    amount=self._safe_decimal(getattr(bar, "amount", None)) or Decimal("0"),
                    ma5=None,
                    ma20=None,
                    ma60=None,
                    macd=None,
                    macd_signal=None,
                    macd_hist=None,
                    rsi=None,
                )
                for bar in remote_bars
            ]
        )
        return remote_technical_bars or best_available_bars

    def _get_published_technical_bars(
        self,
        stock_code: str,
        *,
        start_date: date,
        end_date: date,
        publication_key: str,
    ) -> list[TechnicalBar]:
        """Build technical bars exclusively from the selected price publication."""

        payload = get_published_price_bar_series(
            stock_code,
            publication_key=publication_key,
            start=start_date,
            end=end_date,
            limit=max((end_date - start_date).days + 10, 120),
        )
        if bool(payload.get("must_not_use_for_decision")):
            return []
        rows = payload.get("rows", [])
        if not isinstance(rows, (list, tuple)):
            return []

        bars: list[TechnicalBar] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            raw_date = row.get("timestamp", row.get("bar_date"))
            if not isinstance(raw_date, str) or not raw_date.strip():
                continue
            try:
                trade_date = date.fromisoformat(raw_date.strip()[:10])
            except ValueError:
                continue
            raw_fetched_at = row.get("fetched_at")
            if not isinstance(raw_fetched_at, str) or not raw_fetched_at.strip():
                continue
            try:
                fetched_at = datetime.fromisoformat(raw_fetched_at.strip().replace("Z", "+00:00"))
            except ValueError:
                continue
            if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
                continue
            open_value = safe_float(row.get("open"), default=None)
            high_value = safe_float(row.get("high"), default=None)
            low_value = safe_float(row.get("low"), default=None)
            close_value = safe_float(row.get("close"), default=None)
            if (
                open_value is None
                or high_value is None
                or low_value is None
                or close_value is None
                or min(open_value, high_value, low_value, close_value) <= 0
            ):
                continue
            volume_value = safe_float(row.get("volume"), default=0.0) or 0.0
            amount_value = safe_float(row.get("amount"), default=0.0) or 0.0
            bars.append(
                TechnicalBar(
                    stock_code=stock_code,
                    trade_date=trade_date,
                    open=Decimal(str(open_value)),
                    high=Decimal(str(high_value)),
                    low=Decimal(str(low_value)),
                    close=Decimal(str(close_value)),
                    volume=max(int(volume_value), 0),
                    amount=Decimal(str(max(amount_value, 0.0))),
                    ma5=None,
                    ma20=None,
                    ma60=None,
                    macd=None,
                    macd_signal=None,
                    macd_hist=None,
                    rsi=None,
                )
            )
        if not bars:
            return []
        bars.sort(key=lambda item: item.trade_date)
        return self._recalculate_technical_bars(bars)

    def _has_sufficient_price_coverage(
        self,
        prices: list[tuple[date, Decimal]],
        *,
        start_date: date,
        end_date: date,
    ) -> bool:
        if not prices:
            return False
        calendar_days = max((end_date - start_date).days + 1, 1)
        if calendar_days <= 45:
            return len(prices) >= 1
        expected_trading_days = max(int(calendar_days * 0.55), 1)
        minimum_points = min(60, max(8, expected_trading_days // 4))
        return len(prices) >= minimum_points

    def _has_sufficient_bar_coverage(
        self,
        bars: list[TechnicalBar],
        *,
        start_date: date,
        end_date: date,
    ) -> bool:
        if not bars:
            return False
        calendar_days = max((end_date - start_date).days + 1, 1)
        if calendar_days <= 45:
            return len(bars) >= 2
        expected_trading_days = max(int(calendar_days * 0.55), 1)
        minimum_points = min(60, max(8, expected_trading_days // 4))
        return len(bars) >= minimum_points

    def calculate_daily_returns(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        *,
        hydrate: bool = False,
        published_only: bool = False,
        publication_key: str = "current",
    ) -> dict[date, float]:
        """
        计算股票的日收益率

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            {日期: 收益率}，收益率以小数表示（如 0.01 表示 1%）
        """
        prices = self.get_daily_prices(
            stock_code,
            start_date,
            end_date,
            hydrate=hydrate,
            published_only=published_only,
            publication_key=publication_key,
        )

        returns: dict[date, float] = {}
        for i in range(1, len(prices)):
            prev_date, prev_price = prices[i - 1]
            curr_date, curr_price = prices[i]

            if prev_price > 0:
                daily_return = float((curr_price - prev_price) / prev_price)
                returns[curr_date] = daily_return

        return returns

    def _get_remote_daily_prices(
        self, stock_code: str, start_date: date, end_date: date
    ) -> list[tuple[date, Decimal]]:
        return self._bars_to_daily_prices(
            self._get_remote_historical_bars(stock_code, start_date, end_date)
        )

    def _get_remote_historical_bars(
        self, stock_code: str, start_date: date, end_date: date
    ) -> list[_HistoricalPriceBar]:
        return list(get_model_market_data_port().stock_history(stock_code, start_date, end_date))

    def _bars_to_daily_prices(self, bars: list[_HistoricalPriceBar]) -> list[tuple[date, Decimal]]:
        prices: list[tuple[date, Decimal]] = []
        for bar in bars:
            trade_date = getattr(bar, "trade_date", None)
            close_price = self._safe_decimal(getattr(bar, "close", None))
            if not isinstance(trade_date, date) or close_price is None or close_price <= 0:
                continue
            prices.append((trade_date, close_price))
        return prices

    def _price_bars_to_technical_bars(
        self,
        stock_code: str,
        bars: list[PriceBar],
    ) -> list[TechnicalBar]:
        return self._recalculate_technical_bars(
            [
                TechnicalBar(
                    stock_code=stock_code,
                    trade_date=bar.bar_date,
                    open=Decimal(str(bar.open)),
                    high=Decimal(str(bar.high)),
                    low=Decimal(str(bar.low)),
                    close=Decimal(str(bar.close)),
                    volume=int(bar.volume) if bar.volume is not None else 0,
                    amount=self._safe_decimal(bar.amount) or Decimal("0"),
                    ma5=None,
                    ma20=None,
                    ma60=None,
                    macd=None,
                    macd_signal=None,
                    macd_hist=None,
                    rsi=None,
                )
                for bar in sorted(bars, key=lambda item: item.bar_date)
            ]
        )

    def _recalculate_technical_bars(
        self,
        bars: list[TechnicalBar],
    ) -> list[TechnicalBar]:
        recalculated: list[TechnicalBar] = []
        closes: list[Decimal] = []
        ema12: float | None = None
        ema26: float | None = None
        signal_ema: float | None = None
        alpha12 = 2 / 13
        alpha26 = 2 / 27
        alpha9 = 2 / 10

        for bar in sorted(bars, key=lambda item: item.trade_date):
            closes.append(bar.close)
            close_float = float(bar.close)
            ema12 = close_float if ema12 is None else ema12 + (close_float - ema12) * alpha12
            ema26 = close_float if ema26 is None else ema26 + (close_float - ema26) * alpha26
            macd = ema12 - ema26
            signal_ema = macd if signal_ema is None else signal_ema + (macd - signal_ema) * alpha9

            recalculated.append(
                TechnicalBar(
                    stock_code=bar.stock_code,
                    trade_date=bar.trade_date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    amount=bar.amount,
                    ma5=self._calculate_sma(closes, 5),
                    ma20=self._calculate_sma(closes, 20),
                    ma60=self._calculate_sma(closes, 60),
                    macd=macd,
                    macd_signal=signal_ema,
                    macd_hist=macd - signal_ema,
                    rsi=None,
                )
            )
        return recalculated

    def _calculate_sma(self, closes: list[Decimal], window: int) -> Decimal | None:
        if len(closes) < window:
            return None
        return sum(closes[-window:]) / Decimal(window)


__all__ = ["StockMarketDataRepositoryMixin"]
