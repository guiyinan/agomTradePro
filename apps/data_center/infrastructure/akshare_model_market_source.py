"""AKShare daily inputs with explicit raw-price and adjustment semantics."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from apps.data_center.domain.model_market_data import ModelDailyBar
from core.exceptions import DataFetchError
from shared.numeric import safe_float


class AkshareModelMarketSource:
    """Normalize SDK responses before exposing any values to model consumers."""

    def __init__(self, client: Any, *, source: str, tolerance: float) -> None:
        self._client = client
        self._source = source
        self._tolerance = tolerance

    def stock_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        """Pair raw and backward-adjusted OHLC; reject nonmultiplicative adjustments."""
        params = {
            "symbol": asset_code.split(".")[0],
            "period": "daily",
            "start_date": start_date.strftime("%Y%m%d"),
            "end_date": end_date.strftime("%Y%m%d"),
        }
        raw = self._client.stock_zh_a_hist(**params, adjust="", timeout=20)
        adjusted = self._client.stock_zh_a_hist(**params, adjust="hfq", timeout=20)
        bars = self._normalize(raw, asset_code, start_date, end_date)
        factors = {
            bar.trade_date: bar
            for bar in self._normalize(adjusted, asset_code, start_date, end_date)
        }
        result: list[ModelDailyBar] = []
        for bar in bars:
            other = factors.get(bar.trade_date)
            if other is None:
                raise DataFetchError("Missing adjusted observation", code="MODEL_MARKET_INVALID")
            factor = other.close / bar.close
            for raw_price, adjusted_price in zip(
                (bar.open, bar.high, bar.low), (other.open, other.high, other.low), strict=True
            ):
                if abs(adjusted_price / raw_price / factor - 1) > self._tolerance:
                    raise DataFetchError(
                        "Adjustment is not multiplicative",
                        code="MODEL_MARKET_ADJUSTMENT_INCOMPATIBLE",
                    )
            result.append(
                ModelDailyBar(
                    asset_code=bar.asset_code,
                    trade_date=bar.trade_date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    change_percent=bar.change_percent,
                    adjustment_factor=factor,
                    amount=bar.amount,
                    source=bar.source,
                )
            )
        return tuple(result)

    def index_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        """Read unadjusted index OHLCV instead of fabricating bars from closes."""
        frame = self._client.index_zh_a_hist(
            symbol=asset_code.split(".")[0],
            period="daily",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        return self._normalize(frame, asset_code, start_date, end_date)

    def trade_days(self, start_date: date, end_date: date) -> tuple[date, ...]:
        """Read the provider's exchange calendar without weekday approximation."""
        frame = self._client.tool_trade_date_hist_sina()
        if frame is None or "trade_date" not in frame.columns:
            return ()
        days = pd.to_datetime(frame["trade_date"], errors="coerce").dropna()
        return tuple(
            sorted({item.date() for item in days if start_date <= item.date() <= end_date})
        )

    def index_members(self, index_code: str, target_date: date) -> tuple[str, ...]:
        """Decline historical membership: today's list is not a point-in-time snapshot."""
        return ()

    def _normalize(
        self, frame: Any, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        if frame is None or frame.empty:
            return ()
        rows: list[ModelDailyBar] = []
        for record in frame.to_dict("records"):
            observed = pd.to_datetime(record.get("日期"), errors="coerce")
            if pd.isna(observed) or not start_date <= observed.date() <= end_date:
                continue
            values = [
                safe_float(record.get(key))
                for key in ("开盘", "最高", "最低", "收盘", "成交量", "涨跌幅")
            ]
            if any(value is None for value in values):
                raise DataFetchError("Incomplete daily observation", code="MODEL_MARKET_INVALID")
            opening, high, low, close, volume, change = values
            assert opening is not None and high is not None and low is not None
            assert close is not None and volume is not None and change is not None
            if min(opening, high, low, close) <= 0:
                raise DataFetchError("Nonpositive daily prices", code="MODEL_MARKET_INVALID")
            rows.append(
                ModelDailyBar(
                    asset_code=asset_code,
                    trade_date=observed.date(),
                    open=opening,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume * 100.0,
                    change_percent=change,
                    adjustment_factor=None,
                    source=self._source,
                    amount=safe_float(record.get("成交额")),
                )
            )
        return tuple(sorted(rows, key=lambda bar: bar.trade_date))
