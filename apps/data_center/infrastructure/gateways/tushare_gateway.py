"""
Tushare Gateway

将现有 Tushare 适配器包装为统一的 MarketGatewayProtocol。
支持 REALTIME_QUOTE 和 TECHNICAL_FACTORS 能力。
作为统一 provider adapter 的底层行情客户端。
"""

import logging
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast

from apps.data_center.infrastructure.market_gateway_entities import (
    HistoricalPriceBar,
    QuoteSnapshot,
    TechnicalSnapshot,
)
from apps.data_center.infrastructure.market_gateway_enums import DataCapability
from apps.data_center.infrastructure.market_gateway_protocol import MarketGatewayProtocol
from core.integration.data_center_business_sources import build_tushare_stock_adapter
from shared.numeric import safe_float

logger = logging.getLogger(__name__)

_SUPPORTED = {
    DataCapability.REALTIME_QUOTE,
    DataCapability.TECHNICAL_FACTORS,
    DataCapability.HISTORICAL_PRICE,
}


class _RowLike(Protocol):
    """Typed boundary for one pandas-like provider row."""

    def get(self, key: str, default: object = None) -> object:
        """Return one provider field."""

    def __getitem__(self, key: str) -> object:
        """Return one required provider field."""


class _DataFrameLike(Protocol):
    """Minimal DataFrame contract returned by the Tushare SDK."""

    empty: bool

    def sort_values(self, by: str) -> "_DataFrameLike":
        """Return rows sorted by one field."""

    def iterrows(self) -> Iterable[tuple[object, _RowLike]]:
        """Iterate provider rows."""


class _TushareProClientProtocol(Protocol):
    """Tushare endpoints used by historical price retrieval."""

    def fund_daily(self, *, ts_code: str, start_date: str, end_date: str) -> _DataFrameLike:
        """Return fund daily bars."""

    def index_daily(self, *, ts_code: str, start_date: str, end_date: str) -> _DataFrameLike:
        """Return index daily bars."""

    def daily(self, *, ts_code: str, start_date: str, end_date: str) -> _DataFrameLike:
        """Return stock daily bars."""


def _safe_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_int(value: object) -> int | None:
    parsed = safe_float(value)
    if parsed is None or parsed < 0 or not parsed.is_integer():
        return None
    return int(parsed)


def _parse_compact_date(value: str) -> date | None:
    """Parse a strict YYYYMMDD provider boundary date."""

    if not isinstance(value, str) or len(value) != 8 or not value.isascii() or not value.isdigit():
        return None
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return None


def _normalize_asset_code(value: str) -> str | None:
    """Return one canonical six-digit CN security code with market suffix."""

    normalized = value.strip().upper()
    parts = normalized.split(".")
    if len(parts) > 2 or len(parts[0]) != 6 or not parts[0].isascii() or not parts[0].isdigit():
        return None
    if len(parts) == 2 and parts[1] not in {"SH", "SZ", "BJ"}:
        return None
    return normalized


class TushareGateway(MarketGatewayProtocol):
    """Tushare 数据源 Provider

    注意：Tushare 免费版只能获取日线收盘数据，非真实时行情。
    适合作为东方财富的备用/校验源。
    """

    def provider_name(self) -> str:
        return "tushare"

    def supports(self, capability: DataCapability) -> bool:
        return capability in _SUPPORTED

    def get_quote_snapshots(self, stock_codes: list[str]) -> list[QuoteSnapshot]:
        """从 Tushare 获取最新日线数据作为"准实时"行情"""
        try:
            adapter = build_tushare_stock_adapter()
            results: list[QuoteSnapshot] = []

            from django.utils import timezone

            end_date = timezone.now().strftime("%Y%m%d")
            start_date = (timezone.now() - timedelta(days=5)).strftime("%Y%m%d")

            for code in stock_codes:
                try:
                    df = adapter.fetch_daily_data(
                        stock_code=code,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    if df is None or df.empty:
                        continue

                    latest = df.iloc[-1]
                    price = _safe_decimal(latest.get("close"))
                    if price is None or price <= 0:
                        continue

                    # 计算涨跌额/涨跌幅
                    pre_close = _safe_decimal(latest.get("pre_close"))
                    change = None
                    change_pct = None
                    if price and pre_close and pre_close > 0:
                        change = price - pre_close
                        change_pct = float(change / pre_close * 100)

                    results.append(
                        QuoteSnapshot(
                            stock_code=code,
                            price=price,
                            change=change,
                            change_pct=change_pct,
                            volume=_safe_int(latest.get("vol")),
                            amount=_safe_decimal(latest.get("amount")),
                            turnover_rate=safe_float(latest.get("turnover_rate")),
                            high=_safe_decimal(latest.get("high")),
                            low=_safe_decimal(latest.get("low")),
                            open=_safe_decimal(latest.get("open")),
                            pre_close=pre_close,
                            source="tushare",
                        )
                    )
                except Exception:
                    logger.warning("Tushare 获取 %s 失败", code, exc_info=True)
                    continue

            logger.info("Tushare 行情: 请求 %d 只, 成功 %d 只", len(stock_codes), len(results))
            return results

        except Exception:
            logger.exception("Tushare gateway 批量行情失败")
            return []

    def get_technical_snapshot(self, stock_code: str) -> TechnicalSnapshot | None:
        """从 Tushare 获取技术指标"""
        snapshots = self.get_quote_snapshots([stock_code])
        if not snapshots:
            return None
        q = snapshots[0]
        return TechnicalSnapshot(
            stock_code=stock_code,
            trade_date=date.today(),
            close=q.price,
            turnover_rate=q.turnover_rate,
            source="tushare",
        )

    def get_historical_prices(
        self,
        asset_code: str,
        start_date: str,
        end_date: str,
    ) -> list[HistoricalPriceBar]:
        """从 Tushare 获取历史 K 线"""
        normalized_asset_code = _normalize_asset_code(asset_code)
        parsed_start_date = _parse_compact_date(start_date)
        parsed_end_date = _parse_compact_date(end_date)
        if (
            normalized_asset_code is None
            or parsed_start_date is None
            or parsed_end_date is None
            or parsed_start_date > parsed_end_date
        ):
            logger.warning("Tushare historical price request rejected: invalid scope")
            return []
        try:
            from shared.infrastructure.tushare_client import create_tushare_pro_client

            pro = cast(_TushareProClientProtocol, create_tushare_pro_client())

            code = normalized_asset_code.split(".", 1)[0]
            ts_code = self._to_tushare_code(code)
            if "." in normalized_asset_code:
                ts_code = normalized_asset_code
            df = None

            # ETF
            if code.startswith(("51", "15", "56", "58")):
                df = pro.fund_daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                )

            # 指数
            if df is None or (hasattr(df, "empty") and df.empty):
                if self._is_index_asset(normalized_asset_code):
                    df = pro.index_daily(
                        ts_code=ts_code,
                        start_date=start_date,
                        end_date=end_date,
                    )

            # 股票
            if df is None or (hasattr(df, "empty") and df.empty):
                df = pro.daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                )

            if df is None or df.empty:
                return self._fallback_historical_prices(asset_code, start_date, end_date)

            df = df.sort_values("trade_date")
            bars: list[HistoricalPriceBar] = []
            for _, row in df.iterrows():
                try:
                    td = str(row["trade_date"])
                    trade_date = _parse_compact_date(td)
                    open_price = safe_float(row.get("open"))
                    high_price = safe_float(row.get("high"))
                    low_price = safe_float(row.get("low"))
                    close_price = safe_float(row.get("close"))
                    if (
                        trade_date is None
                        or open_price is None
                        or high_price is None
                        or low_price is None
                        or close_price is None
                        or min(open_price, high_price, low_price, close_price) <= 0
                        or high_price < max(open_price, low_price, close_price)
                        or low_price > min(open_price, high_price, close_price)
                    ):
                        continue
                    amount = safe_float(row.get("amount"))
                    if amount is not None and amount < 0:
                        amount = None
                    bars.append(
                        HistoricalPriceBar(
                            asset_code=ts_code,
                            trade_date=trade_date,
                            open=open_price,
                            high=high_price,
                            low=low_price,
                            close=close_price,
                            volume=_safe_int(row.get("vol")),
                            amount=amount,
                            source="tushare",
                        )
                    )
                except (ValueError, TypeError):
                    continue

            logger.info("Tushare 历史 K 线: %s 获取 %d 条", asset_code, len(bars))
            return bars

        except Exception:
            logger.exception("Tushare 历史 K 线获取失败: %s", asset_code)
            return self._fallback_historical_prices(asset_code, start_date, end_date)

    @staticmethod
    def _to_tushare_code(code: str) -> str:
        """纯数字代码转 Tushare 格式"""
        if "." in code:
            return code
        if code.startswith("6"):
            return f"{code}.SH"
        if code.startswith(("0", "3")):
            return f"{code}.SZ"
        if code.startswith(("4", "8", "92")):
            return f"{code}.BJ"
        if code.startswith("5") or code.startswith("15"):
            # ETF: 51xxxx → SH, 15xxxx → SZ
            if code.startswith(("51", "56", "58")):
                return f"{code}.SH"
            return f"{code}.SZ"
        return f"{code}.SH"

    @staticmethod
    def _is_index_asset(asset_code: str) -> bool:
        normalized = str(asset_code or "").strip().upper()
        base_code = normalized.split(".", 1)[0]
        if normalized.endswith(".SH"):
            return base_code.startswith("000")
        if normalized.endswith(".SZ"):
            return base_code.startswith("399")
        return base_code.startswith(("000", "399"))

    @staticmethod
    def _fallback_historical_prices(
        asset_code: str,
        start_date: str,
        end_date: str,
    ) -> list[HistoricalPriceBar]:
        try:
            from apps.data_center.infrastructure.gateways.tencent_gateway import TencentGateway

            raw_bars: object = TencentGateway().get_historical_prices(
                asset_code, start_date, end_date
            )
            if not isinstance(raw_bars, list):
                return []
            bars = [bar for bar in raw_bars if isinstance(bar, HistoricalPriceBar)]
            if len(bars) != len(raw_bars):
                return []
            if bars:
                logger.info("Tushare 历史 K 线降级到腾讯成功: %s 获取 %d 条", asset_code, len(bars))
            return bars
        except Exception:
            logger.exception("Tushare 历史 K 线降级腾讯失败: %s", asset_code)
            return []
