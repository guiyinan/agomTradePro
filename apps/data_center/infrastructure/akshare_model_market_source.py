"""AKShare daily inputs with explicit raw-price and adjustment semantics."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Protocol

import pandas as pd  # type: ignore[import-untyped]

from apps.data_center.domain.model_market_data import ModelDailyBar, TradingCalendarEvidence
from core.exceptions import DataFetchError
from shared.numeric import safe_float


class _EgressHistoryTransport(Protocol):
    """Minimal transport capability required for routed EastMoney history."""

    def fetch_eastmoney_history(
        self,
        *,
        provider_id: int,
        deployment_region: str,
        symbol: str,
        start_date: date,
        end_date: date,
        adjust: str,
    ) -> pd.DataFrame:
        """Fetch one normalized EastMoney history frame."""
        ...

    def should_route_history(self, *, provider_id: int, deployment_region: str) -> bool:
        """Return whether the persisted route owns this provider history."""
        ...


class AkshareModelMarketSource:
    """Normalize SDK responses before exposing any values to model consumers."""

    def __init__(
        self,
        client: Any,
        *,
        source: str,
        tolerance: float,
        transport: _EgressHistoryTransport | None = None,
        provider_id: int | None = None,
        deployment_region: str = "unknown",
    ) -> None:
        self._client = client
        self._source = source
        self._tolerance = tolerance
        self._transport = transport
        self._provider_id = provider_id
        self._deployment_region = deployment_region or "unknown"

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
        raw = self._history_frame(params, start_date=start_date, end_date=end_date, adjust="")
        adjusted = self._history_frame(
            params, start_date=start_date, end_date=end_date, adjust="hfq"
        )
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

    def _history_frame(
        self,
        params: dict[str, str],
        *,
        start_date: date,
        end_date: date,
        adjust: str,
    ) -> pd.DataFrame:
        """Use the routed transport when configured, retaining SDK compatibility otherwise."""

        if self._transport is not None and self._provider_id is not None:
            if not self._transport.should_route_history(
                provider_id=self._provider_id,
                deployment_region=self._deployment_region,
            ):
                return self._client.stock_zh_a_hist(**params, adjust=adjust, timeout=20)
            return self._transport.fetch_eastmoney_history(
                provider_id=self._provider_id,
                deployment_region=self._deployment_region,
                symbol=params["symbol"],
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
        return self._client.stock_zh_a_hist(**params, adjust=adjust, timeout=20)

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
        try:
            return self.trading_calendar_evidence(start_date, end_date).open_sessions
        except DataFetchError:
            return ()

    def trading_calendar_evidence(
        self, start_date: date, end_date: date
    ) -> TradingCalendarEvidence:
        """Bind AKShare's exchange-session history to the requested calendar window."""

        if start_date > end_date:
            raise ValueError("Trading calendar start_date must not exceed end_date")
        frame = self._client.tool_trade_date_hist_sina()
        if frame is None or frame.empty or "trade_date" not in frame.columns:
            raise DataFetchError(
                "AKShare trading calendar schema is unavailable",
                code="MODEL_MARKET_CALENDAR_SCHEMA_INVALID",
            )
        parsed = pd.to_datetime(frame["trade_date"], errors="coerce")
        if parsed.isna().any():
            raise DataFetchError(
                "AKShare trading calendar contains an invalid date",
                code="MODEL_MARKET_CALENDAR_SCHEMA_INVALID",
            )
        raw_provider_days = tuple(item.date() for item in parsed)
        if len(set(raw_provider_days)) != len(raw_provider_days):
            raise DataFetchError(
                "AKShare trading calendar contains duplicate sessions",
                code="MODEL_MARKET_CALENDAR_CONFLICT",
            )
        provider_days = tuple(sorted(raw_provider_days))
        if not provider_days or provider_days[0] > start_date or provider_days[-1] < end_date:
            raise DataFetchError(
                "AKShare trading calendar coverage is incomplete",
                code="MODEL_MARKET_CALENDAR_COVERAGE_INCOMPLETE",
            )
        return TradingCalendarEvidence(
            coverage_start=start_date,
            coverage_end=end_date,
            open_sessions=tuple(item for item in provider_days if start_date <= item <= end_date),
            source=self._source,
            observed_at=datetime.now(UTC),
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
