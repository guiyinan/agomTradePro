"""
QMT Gateway

通过 XtQuant/QMT 本地行情接口接入统一 MarketGatewayProtocol。
当前仅覆盖行情、技术快照和日线历史 K 线，不涉及交易能力。
"""

from __future__ import annotations

import importlib
import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from numbers import Integral
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.infrastructure.market_gateway_entities import (
    HistoricalPriceBar,
    QuoteSnapshot,
    TechnicalSnapshot,
    quote_metric_source_text,
)
from apps.data_center.infrastructure.market_gateway_enums import DataCapability
from apps.data_center.infrastructure.market_gateway_protocol import MarketGatewayProtocol
from shared.numeric import safe_float

logger = logging.getLogger(__name__)
_CHINA_TZ = ZoneInfo("Asia/Shanghai")

_SUPPORTED = {
    DataCapability.REALTIME_QUOTE,
    DataCapability.TECHNICAL_FACTORS,
    DataCapability.HISTORICAL_PRICE,
}


def _parse_qmt_observed_at(value: object) -> datetime | None:
    """Parse QMT quote observation time without substituting request time."""

    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            numeric = float(raw)
        except ValueError:
            numeric = 0.0
        if numeric >= 1_000_000_000:
            seconds = numeric / 1000 if numeric >= 1_000_000_000_000 else numeric
            try:
                return datetime.fromtimestamp(seconds, tz=UTC)
            except (OSError, OverflowError, ValueError):
                return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            try:
                parsed = datetime.strptime(raw, "%Y%m%d%H%M%S")
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed.astimezone(UTC)


class _XtDataProtocol(Protocol):
    """QMT 行情 SDK 当前使用到的最小动态接口。"""

    def get_full_tick(self, stock_list: list[str]) -> object: ...

    def get_market_data_ex(
        self,
        *,
        field_list: list[str],
        stock_list: list[str],
        period: str,
        start_time: str,
        end_time: str,
        count: int,
        dividend_type: object,
        fill_data: bool,
    ) -> object: ...


def _safe_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        decimal_value = Decimal(str(value))
        return decimal_value if decimal_value.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_int(value: object) -> int | None:
    parsed_value = safe_float(value)
    if parsed_value is None:
        return None
    return int(parsed_value)


def _resolve_dividend_adjustment(value: object) -> tuple[str, PriceAdjustment] | None:
    """Map only QMT's official adjustment modes to the existing bar enum.

    QMT distinguishes ratio modes from its plain directional modes. The
    current HistoricalPriceBar contract does not, so ratio modes retain their
    direction but cannot claim a distinct ratio algorithm.
    """

    if type(value) is not str:
        return None
    normalized = value.strip().casefold()
    adjustment_by_mode = {
        "none": PriceAdjustment.NONE,
        "front": PriceAdjustment.FORWARD,
        "back": PriceAdjustment.BACKWARD,
        "front_ratio": PriceAdjustment.FORWARD,
        "back_ratio": PriceAdjustment.BACKWARD,
    }
    adjustment = adjustment_by_mode.get(normalized)
    if adjustment is None:
        return None
    return normalized, adjustment


def _is_missing_scalar(value: object) -> bool:
    """Return whether one external scalar is absent without coercing arrays."""

    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _parse_history_volume(value: object) -> tuple[bool, int | None]:
    """Keep absent volume optional and preserve only exact nonnegative integers."""

    if _is_missing_scalar(value):
        return True, None
    if isinstance(value, (bool, np.bool_)):
        return False, None
    finite_boundary = safe_float(value)
    if finite_boundary is None or finite_boundary < 0:
        return False, None
    if isinstance(value, Integral):
        return True, int(value)

    try:
        exact_value = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return False, None
    if (
        not exact_value.is_finite()
        or exact_value < 0
        or exact_value != exact_value.to_integral_value()
    ):
        return False, None
    if isinstance(value, (float, np.floating)) and abs(exact_value) > Decimal(2**53):
        return False, None
    return True, int(exact_value)


def _pick_value(payload: dict[str, object], *keys: str) -> object | None:
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


class QMTGateway(MarketGatewayProtocol):
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

    def get_quote_snapshots(self, stock_codes: list[str]) -> list[QuoteSnapshot]:
        """从 QMT 获取实时行情快照。"""
        try:
            xtdata = self._load_xtdata()
            qmt_codes = [self._to_qmt_code(code) for code in stock_codes]
            raw_map = xtdata.get_full_tick(qmt_codes)
            if not isinstance(raw_map, dict):
                logger.warning("QMT 行情返回格式无效: %s", type(raw_map).__name__)
                return []

            results: list[QuoteSnapshot] = []
            for stock_code, qmt_code in zip(stock_codes, qmt_codes, strict=False):
                raw = raw_map.get(qmt_code) or {}
                if not isinstance(raw, dict):
                    continue

                price = _safe_decimal(_pick_value(raw, "lastPrice", "last_price", "price"))
                if price is None or price <= 0:
                    continue

                pre_close = _safe_decimal(
                    _pick_value(raw, "lastClose", "last_close", "preClose", "pre_close")
                )
                change = _safe_decimal(_pick_value(raw, "change", "priceChange"))
                change_pct_field = next(
                    (
                        name
                        for name in ("changePercent", "change_pct", "pctChg")
                        if raw.get(name) not in (None, "")
                    ),
                    None,
                )
                raw_change_pct = raw.get(change_pct_field) if change_pct_field else None
                change_pct = safe_float(raw_change_pct)
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
                        turnover_rate=safe_float(_pick_value(raw, "turnoverRate", "turnover_rate")),
                        volume_ratio=safe_float(_pick_value(raw, "volumeRatio", "volume_ratio")),
                        high=_safe_decimal(_pick_value(raw, "high", "highPrice")),
                        low=_safe_decimal(_pick_value(raw, "low", "lowPrice")),
                        open=_safe_decimal(_pick_value(raw, "open", "openPrice")),
                        pre_close=pre_close,
                        source="qmt",
                        observed_at=_parse_qmt_observed_at(
                            _pick_value(raw, "time", "timestamp", "dataTime", "lastTime")
                        ),
                        change_pct_source_value=quote_metric_source_text(raw_change_pct),
                        change_pct_source_field=change_pct_field,
                        change_pct_source_origin=(
                            "vendor_reported" if change_pct_field is not None else "unknown"
                        ),
                    )
                )

            logger.info("QMT 行情: 请求 %d 只, 成功 %d 只", len(stock_codes), len(results))
            return results
        except Exception:
            logger.exception("QMT 行情获取失败")
            return []

    def get_technical_snapshot(self, stock_code: str) -> TechnicalSnapshot | None:
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
        """Return identity-checked, unfilled QMT daily bars in the requested range."""

        requested_start = self._parse_request_date(start_date)
        requested_end = self._parse_request_date(end_date)
        if requested_start is None or requested_end is None or requested_start > requested_end:
            logger.warning("QMT 历史 K 线日期范围无效: %s %s..%s", asset_code, start_date, end_date)
            return []

        adjustment_mode = self._extra_config.get("dividend_type", "none")
        resolved_adjustment = _resolve_dividend_adjustment(adjustment_mode)
        if resolved_adjustment is None:
            logger.warning("QMT 复权方式不受支持: %r", adjustment_mode)
            return []
        dividend_type, price_adjustment = resolved_adjustment

        try:
            xtdata = self._load_xtdata()
            qmt_code = self._to_qmt_code(asset_code)
            raw = xtdata.get_market_data_ex(
                field_list=["time", "open", "high", "low", "close", "volume", "amount"],
                stock_list=[qmt_code],
                period="1d",
                start_time=requested_start.strftime("%Y%m%d"),
                end_time=requested_end.strftime("%Y%m%d"),
                count=-1,
                dividend_type=dividend_type,
                fill_data=False,
            )
            frame = self._extract_history_frame(raw, qmt_code)
            if frame is None or frame.empty:
                return []

            if "time" in frame.columns:
                frame["trade_date"] = frame["time"].apply(self._parse_trade_date)
            elif "trade_date" in frame.columns:
                frame["trade_date"] = frame["trade_date"].apply(self._parse_trade_date)
            else:
                return []

            frame = frame.dropna(subset=["trade_date"])
            frame = frame[
                frame["trade_date"].apply(
                    lambda value: isinstance(value, date)
                    and requested_start <= value <= requested_end
                )
            ].sort_values("trade_date")
            if frame["trade_date"].duplicated(keep=False).any():
                logger.warning("QMT 历史 K 线包含重复交易日: %s", asset_code)
                return []

            bars: list[HistoricalPriceBar] = []
            columns = {
                name: frame[name].tolist() if name in frame.columns else [None] * len(frame)
                for name in ("trade_date", "open", "high", "low", "close", "volume", "amount")
            }
            for trade_date, raw_open, raw_high, raw_low, raw_close, raw_volume, raw_amount in zip(
                columns["trade_date"],
                columns["open"],
                columns["high"],
                columns["low"],
                columns["close"],
                columns["volume"],
                columns["amount"],
                strict=True,
            ):
                if not isinstance(trade_date, date):
                    continue
                if any(
                    isinstance(value, (bool, np.bool_))
                    for value in (raw_open, raw_high, raw_low, raw_close)
                ):
                    continue
                open_price = safe_float(raw_open)
                high_price = safe_float(raw_high)
                low_price = safe_float(raw_low)
                close_price = safe_float(raw_close)
                if (
                    open_price is None
                    or open_price <= 0
                    or high_price is None
                    or high_price <= 0
                    or low_price is None
                    or low_price <= 0
                    or close_price is None
                    or close_price <= 0
                    or low_price > open_price
                    or open_price > high_price
                    or low_price > close_price
                    or close_price > high_price
                ):
                    continue
                volume_is_valid, volume = _parse_history_volume(raw_volume)
                if not volume_is_valid:
                    continue
                bars.append(
                    HistoricalPriceBar(
                        asset_code=asset_code,
                        trade_date=trade_date,
                        open=open_price,
                        high=high_price,
                        low=low_price,
                        close=close_price,
                        volume=volume,
                        amount=safe_float(raw_amount),
                        source="qmt",
                        adjustment=price_adjustment,
                    )
                )

            logger.info("QMT 历史 K 线: %s 获取 %d 条", asset_code, len(bars))
            return bars
        except Exception:
            logger.exception("QMT 历史 K 线获取失败: %s", asset_code)
            return []

    def _load_xtdata(self) -> _XtDataProtocol:
        """延迟加载 xtdata，避免环境未安装时在 import 阶段失败。"""
        try:
            xtdata = importlib.import_module("xtquant.xtdata")
        except ImportError as exc:
            raise RuntimeError("未安装 xtquant，QMT 行情通道不可用") from exc

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

        return cast(_XtDataProtocol, xtdata)

    @staticmethod
    def _extract_history_frame(
        raw: object,
        qmt_code: str,
        *,
        source_identity_verified: bool = False,
    ) -> pd.DataFrame | None:
        """Extract only the requested security's frame with source identity evidence."""

        if raw is None:
            return None
        if isinstance(raw, pd.DataFrame):
            return QMTGateway._verify_history_frame_identity(
                raw,
                qmt_code,
                source_identity_verified=source_identity_verified,
            )
        if isinstance(raw, dict):
            if qmt_code in raw:
                return QMTGateway._extract_history_frame(
                    raw[qmt_code],
                    qmt_code,
                    source_identity_verified=True,
                )
            if {"open", "high", "low", "close"}.issubset(raw.keys()):
                return QMTGateway._extract_history_frame(
                    pd.DataFrame(raw),
                    qmt_code,
                    source_identity_verified=source_identity_verified,
                )
            return None
        if isinstance(raw, list):
            return QMTGateway._extract_history_frame(
                pd.DataFrame(raw),
                qmt_code,
                source_identity_verified=source_identity_verified,
            )
        return None

    @staticmethod
    def _verify_history_frame_identity(
        frame: pd.DataFrame,
        qmt_code: str,
        *,
        source_identity_verified: bool,
    ) -> pd.DataFrame | None:
        """Reject frames without matching row identity or an exact enclosing map key."""

        identity_columns = {"asset_code", "code", "qmt_code", "stock_code", "symbol", "ts_code"}
        columns = [
            column
            for column in frame.columns
            if isinstance(column, str) and column.casefold() in identity_columns
        ]
        if not columns:
            return frame.copy() if source_identity_verified else None
        for column in columns:
            for value in frame[column]:
                if _is_missing_scalar(value):
                    if source_identity_verified:
                        continue
                    return None
                if QMTGateway._to_qmt_code(str(value)) != qmt_code:
                    return None
        return frame.copy()

    @staticmethod
    def _parse_trade_date(raw_value: object) -> date | None:
        """Parse source dates and epochs using the Asia/Shanghai market calendar."""

        if _is_missing_scalar(raw_value) or isinstance(raw_value, bool):
            return None
        if isinstance(raw_value, date) and not isinstance(raw_value, datetime):
            return raw_value
        if isinstance(raw_value, datetime):
            parsed = raw_value
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                parsed = parsed.replace(tzinfo=_CHINA_TZ)
            return parsed.astimezone(_CHINA_TZ).date()

        if isinstance(raw_value, Integral):
            raw_text = str(int(raw_value))
            if len(raw_text) == 8:
                try:
                    return date(
                        int(raw_text[0:4]),
                        int(raw_text[4:6]),
                        int(raw_text[6:8]),
                    )
                except ValueError:
                    return None

        raw_text = raw_value.strip() if isinstance(raw_value, str) else ""
        if raw_text.isdigit() and len(raw_text) == 8:
            try:
                return date(
                    int(raw_text[0:4]),
                    int(raw_text[4:6]),
                    int(raw_text[6:8]),
                )
            except ValueError:
                return None
        if raw_text.isdigit() and len(raw_text) == 14:
            try:
                parsed = datetime.strptime(raw_text, "%Y%m%d%H%M%S")
            except ValueError:
                return None
            return parsed.replace(tzinfo=_CHINA_TZ).date()

        numeric = safe_float(raw_value)
        if numeric is not None:
            seconds = numeric / 1000 if abs(numeric) >= 1_000_000_000_000 else numeric
            try:
                return datetime.fromtimestamp(seconds, tz=_CHINA_TZ).date()
            except (OSError, OverflowError, ValueError):
                return None

        if raw_text:
            try:
                parsed = datetime.fromisoformat(raw_text.replace("/", "-"))
            except ValueError:
                return None
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                parsed = parsed.replace(tzinfo=_CHINA_TZ)
            return parsed.astimezone(_CHINA_TZ).date()
        return None

    @staticmethod
    def _parse_request_date(raw_value: str) -> date | None:
        """Parse an explicit date bound without interpreting it as an epoch."""

        if type(raw_value) is not str:
            return None
        raw_text = raw_value.strip()
        if len(raw_text) == 8 and raw_text.isdigit():
            try:
                return date(
                    int(raw_text[0:4]),
                    int(raw_text[4:6]),
                    int(raw_text[6:8]),
                )
            except ValueError:
                return None
        try:
            return date.fromisoformat(raw_text.replace("/", "-"))
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
