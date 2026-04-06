"""
QMT Gateway

通过 XtQuant/QMT 本地行情接口接入统一 GatewayProviderProtocol。
当前仅覆盖行情、技术快照和日线历史 K 线，不涉及交易能力。
"""

from __future__ import annotations

import importlib
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.data_center.infrastructure.market_gateway_entities import (
    HistoricalPriceBar,
    QuoteSnapshot,
    TechnicalSnapshot,
)
from apps.data_center.infrastructure.market_gateway_enums import DataCapability
from apps.data_center.infrastructure.gateway_protocols import GatewayProviderProtocol

logger = logging.getLogger(__name__)

_SUPPORTED = {
    DataCapability.REALTIME_QUOTE,
    DataCapability.TECHNICAL_FACTORS,
    DataCapability.HISTORICAL_PRICE,
}


def _safe_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        decimal_value = Decimal(str(value))
        return None if decimal_value != decimal_value else decimal_value
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_float(value: object) -> float | None:
    decimal_value = _safe_decimal(value)
    return float(decimal_value) if decimal_value is not None else None


def _safe_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _pick_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _normalize_provider_name(source_name: str | None) -> str:
    if not source_name:
        return "qmt"
    normalized = source_name.strip()
    if not normalized:
        return "qmt"
    return f"qmt:{normalized}"


class QMTGateway(GatewayProviderProtocol):
    """QMT/XtQuant 行情 Provider。"""

    def __init__(
        self,
        source_name: str | None = None,
        extra_config: dict[str, Any] | None = None,
    ) -> None:
        self._provider_name = _normalize_provider_name(source_name)
        self._extra_config = extra_config or {}

    def provider_name(self) -> str:
        return self._provider_name

    def supports(self, capability: DataCapability) -> bool:
        return capability in _SUPPORTED

    def get_quote_snapshots(
        self, stock_codes: list[str]
    ) -> list[QuoteSnapshot]:
        """从 QMT 获取实时行情快照。"""
        try:
            xtdata = self._load_xtdata()
            qmt_codes = [self._to_qmt_code(code) for code in stock_codes]
            raw_map = xtdata.get_full_tick(qmt_codes) or {}

            results: list[QuoteSnapshot] = []
            for stock_code, qmt_code in zip(stock_codes, qmt_codes, strict=False):
                raw = raw_map.get(qmt_code) or {}
                if not isinstance(raw, dict):
                    continue

                price = _safe_decimal(
                    _pick_value(raw, "lastPrice", "last_price", "price")
                )
                if price is None or price <= 0:
                    continue

                pre_close = _safe_decimal(
                    _pick_value(raw, "lastClose", "last_close", "preClose", "pre_close")
                )
                change = _safe_decimal(_pick_value(raw, "change", "priceChange"))
                change_pct = _safe_float(
                    _pick_value(raw, "changePercent", "change_pct", "pctChg")
                )
                if change is None and pre_close is not None:
                    change = price - pre_close
                if change_pct is None and change is not None and pre_close and pre_close > 0:
                    change_pct = float(change / pre_close * 100)

                results.append(
                    QuoteSnapshot(
                        stock_code=self._to_tushare_code(stock_code),
                        price=price,
                        change=change,
                        change_pct=change_pct,
                        volume=_safe_int(_pick_value(raw, "volume", "vol")),
                        amount=_safe_decimal(_pick_value(raw, "amount", "amt")),
                        turnover_rate=_safe_float(
                            _pick_value(raw, "turnoverRate", "turnover_rate")
                        ),
                        volume_ratio=_safe_float(
                            _pick_value(raw, "volumeRatio", "volume_ratio")
                        ),
                        high=_safe_decimal(_pick_value(raw, "high", "highPrice")),
                        low=_safe_decimal(_pick_value(raw, "low", "lowPrice")),
                        open=_safe_decimal(_pick_value(raw, "open", "openPrice")),
                        pre_close=pre_close,
                        source="qmt",
                    )
                )

            logger.info("QMT 行情: 请求 %d 只, 成功 %d 只", len(stock_codes), len(results))
            return results
        except Exception:
            logger.exception("QMT 行情获取失败")
            return []

    def get_technical_snapshot(
        self, stock_code: str
    ) -> TechnicalSnapshot | None:
        snapshots = self.get_quote_snapshots([stock_code])
        if not snapshots:
            return None
        quote = snapshots[0]
        return TechnicalSnapshot(
            stock_code=stock_code,
            trade_date=date.today(),
            close=quote.price,
            turnover_rate=quote.turnover_rate,
            volume_ratio=quote.volume_ratio,
            source="qmt",
        )

    def get_historical_prices(
        self,
        asset_code: str,
        start_date: str,
        end_date: str,
    ) -> list[HistoricalPriceBar]:
        """从 QMT 获取日线历史 K 线。"""
        try:
            import pandas as pd

            xtdata = self._load_xtdata()
            qmt_code = self._to_qmt_code(asset_code)
            raw = xtdata.get_market_data_ex(
                field_list=["time", "open", "high", "low", "close", "volume", "amount"],
                stock_list=[qmt_code],
                period="1d",
                start_time=start_date,
                end_time=end_date,
                count=-1,
                dividend_type=self._extra_config.get("dividend_type", "none"),
                fill_data=True,
            )
            frame = self._extract_history_frame(raw, qmt_code)
            if frame is None or frame.empty:
                return []

            if "time" in frame.columns:
                frame["trade_date"] = frame["time"].apply(self._parse_trade_date)
            elif "trade_date" not in frame.columns:
                return []

            frame = frame.dropna(subset=["trade_date"]).sort_values("trade_date")

            bars: list[HistoricalPriceBar] = []
            for _, row in frame.iterrows():
                try:
                    bars.append(
                        HistoricalPriceBar(
                            asset_code=asset_code,
                            trade_date=row["trade_date"],
                            open=float(row.get("open", 0)),
                            high=float(row.get("high", 0)),
                            low=float(row.get("low", 0)),
                            close=float(row.get("close", 0)),
                            volume=_safe_int(row.get("volume")),
                            amount=_safe_float(row.get("amount")),
                            source="qmt",
                        )
                    )
                except (ValueError, TypeError):
                    continue

            logger.info("QMT 历史 K 线: %s 获取 %d 条", asset_code, len(bars))
            return bars
        except Exception:
            logger.exception("QMT 历史 K 线获取失败: %s", asset_code)
            return []

    def _load_xtdata(self):
        """延迟加载 xtdata，避免环境未安装时在 import 阶段失败。"""
        try:
            xtdata = importlib.import_module("xtquant.xtdata")
        except ImportError as exc:
            raise RuntimeError(
                "未安装 xtquant，QMT 行情通道不可用"
            ) from exc

        data_dir = self._extra_config.get("data_dir")
        set_data_dir = getattr(xtdata, "set_data_dir", None)
        if data_dir and callable(set_data_dir):
            set_data_dir(data_dir)

        connect = getattr(xtdata, "connect", None)
        if callable(connect):
            client_path = self._extra_config.get("client_path")
            try:
                if client_path:
                    connect(client_path)
                else:
                    connect()
            except TypeError:
                connect()

        return xtdata

    @staticmethod
    def _extract_history_frame(raw: Any, qmt_code: str):
        import pandas as pd

        if raw is None:
            return None
        if isinstance(raw, pd.DataFrame):
            return raw.copy()
        if isinstance(raw, dict):
            if qmt_code in raw:
                return QMTGateway._extract_history_frame(raw[qmt_code], qmt_code)
            if {"open", "high", "low", "close"}.issubset(raw.keys()):
                return pd.DataFrame(raw)
            for value in raw.values():
                frame = QMTGateway._extract_history_frame(value, qmt_code)
                if frame is not None and not frame.empty:
                    return frame
        if isinstance(raw, list):
            return pd.DataFrame(raw)
        return None

    @staticmethod
    def _parse_trade_date(raw_value: Any) -> date | None:
        if raw_value in (None, ""):
            return None
        if isinstance(raw_value, date) and not isinstance(raw_value, datetime):
            return raw_value
        if isinstance(raw_value, datetime):
            return raw_value.date()

        raw_text = str(raw_value).strip()
        if not raw_text:
            return None

        if raw_text.isdigit():
            if len(raw_text) == 8:
                return date(
                    int(raw_text[0:4]),
                    int(raw_text[4:6]),
                    int(raw_text[6:8]),
                )
            timestamp = int(raw_text)
            if len(raw_text) >= 13:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp).date()

        try:
            return datetime.fromisoformat(raw_text.replace("/", "-")).date()
        except ValueError:
            return None

    @staticmethod
    def _to_qmt_code(code: str) -> str:
        code = code.strip()
        if not code:
            return code
        if "." in code:
            return code.upper()
        if code.startswith("6"):
            return f"{code}.SH"
        if code.startswith(("0", "3")):
            return f"{code}.SZ"
        if code.startswith(("8", "4")):
            return f"{code}.BJ"
        return code.upper()

    @staticmethod
    def _to_tushare_code(code: str) -> str:
        return QMTGateway._to_qmt_code(code)
