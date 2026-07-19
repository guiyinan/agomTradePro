"""Daily price and technical-bar slice of the equity stock repository.

This module owns the `StockMarketDataRepositoryMixin` slice of
`DjangoStockRepository`, including remote gateway fallbacks and technical
indicator recalculation. Shared helpers and dependency wiring live in
`stock_repository.py`; do not import the compatibility facade here.
"""

import logging
from datetime import date, datetime
from decimal import Decimal

from apps.data_center.composition import (
    fetch_akshare_eastmoney_historical_prices,
    fetch_tushare_historical_prices,
    get_akshare_module,
)
from apps.equity.domain.entities import TechnicalBar
from core.exceptions import DataFetchError

from .adapters import TushareStockAdapter
from .models import StockDailyModel

logger = logging.getLogger(__name__)


class StockMarketDataRepositoryMixin:
    """Daily prices, technical bars, and remote market-data fallbacks."""

    def get_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        *,
        hydrate: bool = False,
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
        if not hydrate:
            local_models = StockDailyModel._default_manager.filter(
                stock_code=stock_code,
                trade_date__gte=start_date,
                trade_date__lte=end_date,
            ).order_by("trade_date")
            local_prices = [(m.trade_date, m.close) for m in local_models]
            if local_prices and self._has_sufficient_price_coverage(
                local_prices, start_date=start_date, end_date=end_date
            ):
                return local_prices

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

        models = StockDailyModel._default_manager.filter(
            stock_code=stock_code,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        ).order_by("trade_date")
        local_prices = [(m.trade_date, m.close) for m in models]
        if local_prices and self._has_sufficient_price_coverage(
            local_prices, start_date=start_date, end_date=end_date
        ):
            return local_prices

        return self._get_remote_daily_prices(stock_code, start_date, end_date)

    def get_technical_bars(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        *,
        hydrate: bool = False,
    ) -> list[TechnicalBar]:
        """获取K线与技术指标序列。"""
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

        models = StockDailyModel._default_manager.filter(
            stock_code=stock_code,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        ).order_by("trade_date")

        local_bars = [
            TechnicalBar(
                stock_code=model.stock_code,
                trade_date=model.trade_date,
                open=model.open,
                high=model.high,
                low=model.low,
                close=model.close,
                volume=model.volume,
                amount=model.amount,
                ma5=model.ma5,
                ma20=model.ma20,
                ma60=model.ma60,
                macd=model.macd,
                macd_signal=model.macd_signal,
                macd_hist=model.macd_hist,
                rsi=model.rsi,
            )
            for model in models
        ]
        if local_bars:
            best_available_bars = local_bars
            if self._has_sufficient_bar_coverage(
                local_bars, start_date=start_date, end_date=end_date
            ):
                return local_bars

        try:
            remote_bars = self._get_remote_historical_bars(stock_code, start_date, end_date)
        except DataFetchError:
            if best_available_bars:
                return best_available_bars
            raise
        self._cache_remote_historical_bars(stock_code, remote_bars)
        remote_technical_bars = self._recalculate_technical_bars(
            [
                TechnicalBar(
                    stock_code=stock_code,
                    trade_date=bar.trade_date,
                    open=Decimal(str(bar.open)),
                    high=Decimal(str(bar.high)),
                    low=Decimal(str(bar.low)),
                    close=Decimal(str(bar.close)),
                    volume=bar.volume or 0,
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
        prices = self.get_daily_prices(stock_code, start_date, end_date, hydrate=hydrate)

        returns = {}
        for i in range(1, len(prices)):
            prev_date, prev_price = prices[i - 1]
            curr_date, curr_price = prices[i]

            if prev_price > 0:
                daily_return = float((curr_price - prev_price) / prev_price)
                returns[curr_date] = daily_return

        return returns

    def _get_remote_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, Decimal]]:
        """在数据中台价格事实缺失时，通过数据中台 Gateway 拉取只读日线价格。"""
        tushare_gateway_prices = self._get_tushare_gateway_daily_prices(
            stock_code,
            start_date,
            end_date,
        )
        if tushare_gateway_prices:
            return tushare_gateway_prices

        akshare_gateway_bars = self._get_akshare_gateway_historical_bars(
            stock_code,
            start_date,
            end_date,
        )
        self._cache_remote_historical_bars(stock_code, akshare_gateway_bars)
        return self._bars_to_daily_prices(akshare_gateway_bars)

    def _get_remote_historical_bars(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list:
        """在数据中台价格事实缺失时，通过数据中台 Gateway 拉取历史 K 线。"""
        tushare_bars = self._get_tushare_gateway_historical_bars(
            stock_code,
            start_date,
            end_date,
        )
        if tushare_bars:
            return tushare_bars

        return self._get_akshare_gateway_historical_bars(stock_code, start_date, end_date)

    def _bars_to_daily_prices(self, bars: list) -> list[tuple[date, Decimal]]:
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
        bars: list,
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
                    volume=bar.volume or 0,
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

    def _get_tushare_gateway_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, Decimal]]:
        """通过 Tushare Gateway 获取真实远端日线价格。"""
        bars = self._get_tushare_gateway_historical_bars(stock_code, start_date, end_date)
        self._cache_remote_historical_bars(stock_code, bars)

        remote_prices: list[tuple[date, Decimal]] = []
        for bar in bars:
            close_price = self._safe_decimal(getattr(bar, "close", None))
            if close_price is None or close_price <= 0:
                continue
            remote_prices.append((bar.trade_date, close_price))
        return remote_prices

    def _get_tushare_gateway_historical_bars(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list:
        """通过 Data Center 的 Tushare Gateway 获取历史 K 线。"""
        try:
            return fetch_tushare_historical_prices(
                asset_code=stock_code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch Tushare gateway historical bars for %s: %s",
                stock_code,
                exc,
            )
            return []

    def _cache_remote_historical_bars(self, stock_code: str, bars: list) -> None:
        """将远端历史 K 线幂等写入本地日线表，作为 read-through cache。"""
        if not bars:
            return

        try:
            for bar in bars:
                trade_date = getattr(bar, "trade_date", None)
                open_price = self._safe_decimal(getattr(bar, "open", None))
                high_price = self._safe_decimal(getattr(bar, "high", None))
                low_price = self._safe_decimal(getattr(bar, "low", None))
                close_price = self._safe_decimal(getattr(bar, "close", None))
                amount = self._safe_decimal(getattr(bar, "amount", None)) or Decimal("0")

                if (
                    not isinstance(trade_date, date)
                    or open_price is None
                    or open_price <= 0
                    or high_price is None
                    or high_price <= 0
                    or low_price is None
                    or low_price <= 0
                    or close_price is None
                    or close_price <= 0
                ):
                    continue

                StockDailyModel._default_manager.update_or_create(
                    stock_code=stock_code,
                    trade_date=trade_date,
                    defaults={
                        "open": open_price,
                        "high": high_price,
                        "low": low_price,
                        "close": close_price,
                        "volume": getattr(bar, "volume", None) or 0,
                        "amount": amount,
                        "turnover_rate": getattr(bar, "turnover_rate", None),
                        "adj_factor": getattr(bar, "adj_factor", 1.0) or 1.0,
                    },
                )
        except Exception as exc:
            logger.warning(
                "Failed to cache remote historical bars for %s: %s",
                stock_code,
                exc,
            )

    def _get_akshare_gateway_historical_bars(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list:
        """通过 AKShare EastMoney Gateway 获取历史 K 线。"""
        try:
            return fetch_akshare_eastmoney_historical_prices(
                asset_code=stock_code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch AKShare gateway historical bars for %s: %s",
                stock_code,
                exc,
            )
            return []

    def _get_tushare_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, Decimal]]:
        """从 Tushare 获取远端日线价格。"""
        try:
            frame = TushareStockAdapter().fetch_daily_data(stock_code, start_date, end_date)
        except Exception as exc:
            logger.warning(
                "Failed to fetch Tushare daily prices for %s: %s",
                stock_code,
                exc,
            )
            return []

        if frame is None or frame.empty:
            return []

        remote_prices: list[tuple[date, Decimal]] = []
        for _, row in frame.iterrows():
            trade_date = row.get("trade_date")
            close_price = self._safe_decimal(row.get("close"))
            if hasattr(trade_date, "date"):
                trade_date = trade_date.date()
            if not isinstance(trade_date, date) or close_price is None or close_price <= 0:
                continue
            remote_prices.append((trade_date, close_price))

        return remote_prices

    def _get_akshare_daily_prices(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, Decimal]]:
        """从 AKShare 获取远端日线价格。"""
        try:
            ak = get_akshare_module()

            frame = ak.stock_zh_a_hist(
                symbol=self._to_akshare_symbol(stock_code),
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="qfq",
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch AKShare daily prices for %s: %s",
                stock_code,
                exc,
            )
            return []

        if frame is None or frame.empty:
            return []

        remote_prices: list[tuple[date, Decimal]] = []
        for _, row in frame.iterrows():
            trade_date = row.get("日期")
            close_price = self._safe_decimal(row.get("收盘"))
            if hasattr(trade_date, "date"):
                trade_date = trade_date.date()
            elif isinstance(trade_date, str):
                try:
                    trade_date = datetime.fromisoformat(trade_date).date()
                except ValueError:
                    continue
            if not isinstance(trade_date, date) or close_price is None or close_price <= 0:
                continue
            remote_prices.append((trade_date, close_price))

        return remote_prices


__all__ = ["StockMarketDataRepositoryMixin"]
