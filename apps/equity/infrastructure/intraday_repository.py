"""Intraday quote slice of the equity stock repository.

This module owns the `StockIntradayRepositoryMixin` slice of
`DjangoStockRepository`, including primary/fallback intraday sources and their
validation rules. Shared helpers and dependency wiring live in
`stock_repository.py`; do not import the compatibility facade here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.data_center.application.public import get_published_quote_series
from apps.data_center.composition import get_akshare_module
from apps.data_center.domain.protocols import QuoteSnapshotRepositoryProtocol
from apps.equity.domain.entities import IntradayPricePoint
from apps.realtime.domain.entities import PricePollingConfig
from core.exceptions import DataFetchError, DataValidationError

logger = logging.getLogger(__name__)
pd: ModuleType = import_module("pandas")


class StockIntradayRepositoryMixin:
    """Intraday (1-minute) price points with validated source failover."""

    _INTRADAY_SNAPSHOT_MAX_STALE_DAYS: int
    _INTRADAY_SNAPSHOT_MIN_POINTS: int
    _dc_quote_repo: QuoteSnapshotRepositoryProtocol
    _last_intraday_source: str | None

    if TYPE_CHECKING:

        def _safe_decimal(self, value: object) -> Decimal | None: ...

        def _safe_int(self, value: object) -> int | None: ...

        def _to_akshare_symbol(self, stock_code: str) -> str: ...

        def _to_market_aware_datetime(self, value: object) -> datetime: ...

    def get_intraday_points(self, stock_code: str) -> list[IntradayPricePoint]:
        """获取单资产最新交易日的 1 分钟分时数据。"""
        try:
            published_points = self._get_published_intraday_points(stock_code)
        except Exception as exc:
            logger.warning(
                "Failed to load published quote snapshots for %s: %s",
                stock_code,
                exc,
            )
            published_points = []

        if published_points:
            market_tz = ZoneInfo("Asia/Shanghai")
            if self._has_usable_intraday_snapshot_points(published_points, market_tz):
                self._last_intraday_source = "data_center_published_quote_snapshot"
                return published_points
            logger.info(
                "Skip stale or sparse published quote snapshots for %s: points=%s",
                stock_code,
                len(published_points),
            )

        # Remote AKShare sources remain an explicitly labelled diagnostic
        # failover when the current quote publication is missing or sparse.
        # They never replace the canonical published snapshot in a decision
        # path, and their source/observation time is preserved in the points.
        symbol = self._to_akshare_symbol(stock_code)
        self._last_intraday_source = None

        primary_error: DataFetchError | None = None
        try:
            primary_points = self._get_intraday_hist_min_points(stock_code, symbol)
        except DataFetchError as exc:
            primary_points = []
            primary_error = exc
            logger.warning("Primary intraday source failed for %s: %s", stock_code, exc)

        if primary_points:
            self._last_intraday_source = "akshare_hist_min_em"
            return self._validate_intraday_points(primary_points, "akshare_hist_min_em")

        try:
            fallback_points = self._get_intraday_tick_points(stock_code, symbol)
        except DataFetchError as exc:
            if primary_error is not None:
                raise DataFetchError(
                    message=f"{stock_code} 分时主备数据源均不可用",
                    details={
                        "stock_code": stock_code,
                        "primary_source": "akshare_hist_min_em",
                        "primary_error": primary_error.message,
                        "fallback_source": "akshare_intraday_em",
                        "fallback_error": exc.message,
                    },
                ) from exc
            raise

        if not fallback_points:
            if primary_error is not None:
                raise primary_error
            return []

        if primary_error is None:
            logger.warning(
                "Primary intraday source returned no data for %s; rejecting unvalidated fallback",
                stock_code,
            )
            raise DataFetchError(
                message=f"{stock_code} 主分时数据源暂无数据，拒绝切换到未校验备用源",
                details={
                    "stock_code": stock_code,
                    "primary_source": "akshare_hist_min_em",
                    "fallback_source": "akshare_intraday_em",
                },
            )

        validated_fallback = self._validate_intraday_fallback(stock_code, fallback_points)
        self._last_intraday_source = "akshare_intraday_em_fallback"
        logger.warning(
            "Using validated intraday fallback for %s due to primary failure: %s",
            stock_code,
            primary_error.message,
        )
        return validated_fallback

    def _get_published_intraday_points(self, stock_code: str) -> list[IntradayPricePoint]:
        """Convert member-bound published quote snapshots into intraday points."""

        payload = get_published_quote_series(
            stock_code,
            publication_key="current",
            limit=600,
        )
        if not isinstance(payload, Mapping) or bool(payload.get("must_not_use_for_decision")):
            return []
        rows = payload.get("rows")
        if not isinstance(rows, (list, tuple)):
            return []

        market_tz = ZoneInfo("Asia/Shanghai")
        parsed: list[IntradayPricePoint] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            payload_code = str(row.get("asset_code") or "").strip().upper()
            requested_base = stock_code.strip().upper().split(".", 1)[0]
            if payload_code and payload_code.split(".", 1)[0] != requested_base:
                continue
            raw_observed_at = row.get("snapshot_at")
            if not isinstance(raw_observed_at, str) or not raw_observed_at.strip():
                continue
            try:
                observed_at = datetime.fromisoformat(raw_observed_at.strip().replace("Z", "+00:00"))
            except ValueError:
                continue
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                continue
            price = self._safe_decimal(row.get("current_price"))
            if price is None or price <= 0:
                continue
            parsed.append(
                IntradayPricePoint(
                    stock_code=stock_code,
                    timestamp=observed_at.astimezone(market_tz),
                    price=price,
                    avg_price=price,
                    volume=self._safe_int(row.get("volume")),
                )
            )

        if not parsed:
            return []
        latest_session = max(point.timestamp.astimezone(market_tz).date() for point in parsed)
        session_points = [
            point
            for point in parsed
            if point.timestamp.astimezone(market_tz).date() == latest_session
        ]
        session_points.sort(key=lambda point: point.timestamp)
        return self._validate_intraday_points(
            session_points,
            "data_center_published_quote_snapshot",
        )

    def _has_usable_intraday_snapshot_points(
        self,
        points: list[IntradayPricePoint],
        market_tz: ZoneInfo,
    ) -> bool:
        """Return whether cached quote snapshots can stand in for an intraday line."""
        if len(points) < self._INTRADAY_SNAPSHOT_MIN_POINTS:
            return False
        session_date = points[-1].timestamp.astimezone(market_tz).date()
        market_today = timezone.now().astimezone(market_tz).date()
        stale_days = (market_today - session_date).days
        return 0 <= stale_days <= self._INTRADAY_SNAPSHOT_MAX_STALE_DAYS

    def get_last_intraday_source(self) -> str | None:
        """返回最近一次分时数据读取所使用的数据源。"""
        return self._last_intraday_source

    def _get_intraday_hist_min_points(
        self,
        stock_code: str,
        symbol: str,
    ) -> list[IntradayPricePoint]:
        try:
            ak = get_akshare_module()

            frame = ak.stock_zh_a_hist_min_em(symbol=symbol, period="1", adjust="")
        except Exception as exc:
            raise DataFetchError(
                message=f"AKShare 主分时接口获取失败: {stock_code}",
                details={"stock_code": stock_code, "source": "akshare_hist_min_em"},
            ) from exc

        try:
            if frame is None or frame.empty:
                return []

            frame = frame.copy()
            frame["时间"] = pd.to_datetime(frame["时间"], errors="coerce")
            frame = frame.dropna(subset=["时间"]).sort_values("时间")
            if frame.empty:
                return []

            latest_session = frame["时间"].dt.date.max()
            frame = frame[frame["时间"].dt.date == latest_session]

            points: list[IntradayPricePoint] = []
            for _, row in frame.iterrows():
                price = self._safe_decimal(row.get("收盘"))
                if price is None or price <= 0:
                    continue
                points.append(
                    IntradayPricePoint(
                        stock_code=stock_code,
                        timestamp=self._to_market_aware_datetime(row["时间"]),
                        price=price,
                        avg_price=self._safe_decimal(row.get("均价")),
                        volume=self._safe_int(row.get("成交量")),
                    )
                )
            return points
        except Exception as exc:
            raise DataFetchError(
                message=f"AKShare 主分时接口解析失败: {stock_code}",
                details={"stock_code": stock_code, "source": "akshare_hist_min_em"},
            ) from exc

    def _get_intraday_tick_points(
        self,
        stock_code: str,
        symbol: str,
    ) -> list[IntradayPricePoint]:
        try:
            ak = get_akshare_module()

            frame = ak.stock_intraday_em(symbol=symbol)
        except Exception as exc:
            raise DataFetchError(
                message=f"AKShare 备用分时接口获取失败: {stock_code}",
                details={"stock_code": stock_code, "source": "akshare_intraday_em"},
            ) from exc

        try:
            if frame is None or frame.empty:
                return []

            frame = frame.copy()
            frame["时间"] = pd.to_datetime(
                date.today().isoformat() + " " + frame["时间"].astype(str),
                errors="coerce",
            )
            frame["成交价"] = pd.to_numeric(frame["成交价"], errors="coerce")
            frame["手数"] = pd.to_numeric(frame["手数"], errors="coerce").fillna(0)
            frame = frame.dropna(subset=["时间", "成交价"]).sort_values("时间")
            if frame.empty:
                return []

            frame["minute"] = frame["时间"].dt.floor("min")

            points: list[IntradayPricePoint] = []
            for minute, bucket in frame.groupby("minute"):
                last_row = bucket.iloc[-1]
                shares = bucket["手数"] * 100
                total_shares = int(shares.sum()) if not shares.empty else 0
                weighted_amount = float((bucket["成交价"] * shares).sum()) if total_shares else 0.0
                avg_price = (
                    self._safe_decimal(weighted_amount / total_shares) if total_shares > 0 else None
                )
                price = self._safe_decimal(last_row.get("成交价"))
                if price is None or price <= 0:
                    continue
                points.append(
                    IntradayPricePoint(
                        stock_code=stock_code,
                        timestamp=self._to_market_aware_datetime(minute),
                        price=price,
                        avg_price=avg_price,
                        volume=total_shares or None,
                    )
                )
            return points
        except Exception as exc:
            raise DataFetchError(
                message=f"AKShare 备用分时接口解析失败: {stock_code}",
                details={"stock_code": stock_code, "source": "akshare_intraday_em"},
            ) from exc

    def _validate_intraday_points(
        self,
        points: list[IntradayPricePoint],
        source_name: str,
    ) -> list[IntradayPricePoint]:
        """校验分时点序列的基础数据质量。"""
        if not points:
            return []

        session_date = points[0].timestamp.date()
        previous_timestamp: datetime | None = None

        for point in points:
            if timezone.is_naive(point.timestamp):
                raise DataValidationError(f"{source_name} 返回了 naive datetime")
            if point.timestamp.date() != session_date:
                raise DataValidationError(f"{source_name} 返回了跨交易日分时数据")
            if previous_timestamp is not None and point.timestamp < previous_timestamp:
                raise DataValidationError(f"{source_name} 返回的分时数据未按时间升序排列")
            if point.price <= 0:
                raise DataValidationError(f"{source_name} 返回了非正价格")
            if point.avg_price is not None and point.avg_price <= 0:
                raise DataValidationError(f"{source_name} 返回了非正均价")
            if point.volume is not None and point.volume < 0:
                raise DataValidationError(f"{source_name} 返回了负成交量")
            previous_timestamp = point.timestamp

        return points

    def _validate_intraday_fallback(
        self,
        stock_code: str,
        fallback_points: list[IntradayPricePoint],
    ) -> list[IntradayPricePoint]:
        """在切换到备用分时源前执行一致性校验。"""
        validated_points = self._validate_intraday_points(
            fallback_points,
            "akshare_intraday_em",
        )
        validation_price = self._get_intraday_validation_price(stock_code)
        if validation_price is None or validation_price <= 0:
            raise DataFetchError(
                message=f"{stock_code} 备用分时数据缺少校验基准，拒绝切换",
                details={"stock_code": stock_code, "fallback_source": "akshare_intraday_em"},
            )

        latest_price = validated_points[-1].price
        deviation = abs((latest_price - validation_price) / validation_price)
        if deviation > Decimal("0.01"):
            logger.warning(
                "Rejected intraday fallback for %s due to %.2f%% deviation against validation price",
                stock_code,
                float(deviation * Decimal("100")),
            )
            raise DataValidationError(
                f"{stock_code} 备用分时数据校验失败，偏差 {float(deviation * Decimal('100')):.2f}%"
            )
        return validated_points

    def _get_intraday_validation_price(self, stock_code: str) -> Decimal | None:
        """获取切换备用分时源前的一致性校验价格。"""
        try:
            from apps.realtime.infrastructure.repositories import (
                AKSharePriceDataProvider,
                RedisRealtimePriceRepository,
            )

            config = PricePollingConfig()
            reference_time = timezone.now()
            max_age = timedelta(seconds=config.max_price_age_seconds)
            cached_price = RedisRealtimePriceRepository().get_latest_price(stock_code)
            if cached_price is not None and cached_price.is_fresh(
                reference_time=reference_time,
                max_age=max_age,
            ):
                cached_decimal = self._safe_decimal(cached_price.price)
                if cached_decimal is not None and cached_decimal > 0:
                    return cached_decimal
            elif cached_price is not None:
                logger.info(
                    "Skip unusable cached validation price for %s: observed_at=%s",
                    stock_code,
                    cached_price.timestamp,
                )

            realtime_price = AKSharePriceDataProvider().get_realtime_price(stock_code)
            if realtime_price is None or not realtime_price.is_fresh(
                reference_time=timezone.now(),
                max_age=max_age,
            ):
                return None

            realtime_decimal = self._safe_decimal(realtime_price.price)
            if realtime_decimal is not None and realtime_decimal > 0:
                return realtime_decimal
        except Exception as exc:
            logger.warning("Failed to get intraday validation price for %s: %s", stock_code, exc)

        return None


__all__ = ["StockIntradayRepositoryMixin"]
