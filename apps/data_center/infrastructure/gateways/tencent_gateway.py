"""Tencent public gateway for historical A-share and index bars."""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import requests

from apps.data_center.domain.rules import normalize_asset_code
from apps.data_center.infrastructure.gateway_protocols import GatewayProviderProtocol
from apps.data_center.infrastructure.market_gateway_entities import (
    HistoricalPriceBar,
    QuoteSnapshot,
)
from apps.data_center.infrastructure.market_gateway_enums import DataCapability

logger = logging.getLogger(__name__)

_SUPPORTED = {DataCapability.HISTORICAL_PRICE, DataCapability.REALTIME_QUOTE}


def _request_error_is_permission_denied(exc: requests.RequestException) -> bool:
    """Return whether the local environment blocked outbound socket access."""

    markers = ("WinError 10013", "PermissionError", "访问权限不允许")
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, PermissionError):
            return True
        if any(marker in str(current) for marker in markers):
            return True
        current = current.__cause__ or current.__context__
    return False


class TencentGateway(GatewayProviderProtocol):
    """Fetch historical bars from Tencent's public qfq kline endpoint."""

    _URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    _QUOTE_URL = "https://qt.gtimg.cn/q={symbols}"

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout
        self._socket_blocked = False

    def provider_name(self) -> str:
        return "tencent"

    def supports(self, capability: DataCapability) -> bool:
        return capability in _SUPPORTED

    def get_quote_snapshots(self, asset_codes: list[str]) -> list[QuoteSnapshot]:
        symbols_by_code = {
            asset_code: symbol
            for asset_code in asset_codes
            if (symbol := self._to_symbol(asset_code))
        }
        if not symbols_by_code:
            return []

        try:
            response = requests.get(
                self._QUOTE_URL.format(symbols=",".join(symbols_by_code.values())),
                headers={
                    "Referer": "https://gu.qq.com/",
                    "User-Agent": "Mozilla/5.0",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            if _request_error_is_permission_denied(exc):
                logger.warning("Tencent 实时行情外网被本机权限拦截，快速降级")
                return []
            logger.exception("Tencent 实时行情获取失败: %s", ",".join(asset_codes))
            return []

        return self._parse_quote_response(response.text, symbols_by_code)

    def get_historical_prices(
        self,
        asset_code: str,
        start_date: str,
        end_date: str,
    ) -> list[HistoricalPriceBar]:
        if self._socket_blocked:
            return []

        symbol = self._to_symbol(asset_code)
        if not symbol:
            return []

        try:
            response = requests.get(
                self._URL,
                params={
                    "param": f"{symbol},day,{self._to_query_date(start_date)},{self._to_query_date(end_date)},1000,qfq"
                },
                headers={
                    "Referer": "https://gu.qq.com/",
                    "User-Agent": "Mozilla/5.0",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            if _request_error_is_permission_denied(exc):
                self._socket_blocked = True
                logger.warning("Tencent 历史 K 线外网被本机权限拦截，快速降级: %s", asset_code)
                return []
            logger.exception("Tencent 历史 K 线获取失败: %s", asset_code)
            return []
        except Exception:
            logger.exception("Tencent 历史 K 线获取失败: %s", asset_code)
            return []

        data = (payload.get("data") or {}).get(symbol) or {}
        rows = data.get("qfqday") or data.get("day") or []
        bars: list[HistoricalPriceBar] = []
        canonical_code = normalize_asset_code(asset_code, "tencent")

        for row in rows:
            if not isinstance(row, list) or len(row) < 6:
                continue
            try:
                bars.append(
                    HistoricalPriceBar(
                        asset_code=canonical_code,
                        trade_date=date.fromisoformat(str(row[0])),
                        open=float(row[1]),
                        close=float(row[2]),
                        high=float(row[3]),
                        low=float(row[4]),
                        volume=int(float(row[5])),
                        amount=float(row[6]) if len(row) > 6 and row[6] not in (None, "") else None,
                        source=self.provider_name(),
                    )
                )
            except (TypeError, ValueError):
                continue

        return bars

    @staticmethod
    def _to_symbol(asset_code: str) -> str | None:
        normalized = normalize_asset_code(asset_code, "tencent").upper()
        if "." in normalized:
            numeric, suffix = normalized.split(".", 1)
            if suffix == "SH":
                return f"sh{numeric}"
            if suffix == "SZ":
                return f"sz{numeric}"
            if suffix == "BJ":
                return f"bj{numeric}"
            return None
        if normalized.startswith("6"):
            return f"sh{normalized}"
        if normalized.startswith(("0", "3")):
            return f"sz{normalized}"
        if normalized.startswith(("4", "8")):
            return f"bj{normalized}"
        return None

    @staticmethod
    def _to_query_date(raw_value: str) -> str:
        if len(raw_value) == 8:
            return f"{raw_value[:4]}-{raw_value[4:6]}-{raw_value[6:]}"
        return raw_value

    def _parse_quote_response(
        self,
        text: str,
        symbols_by_code: dict[str, str],
    ) -> list[QuoteSnapshot]:
        requested_by_symbol = {symbol: code for code, symbol in symbols_by_code.items()}
        snapshots: list[QuoteSnapshot] = []
        for match in re.finditer(r'v_([a-z]{2}\d+)="([^"]*)"', text or ""):
            symbol = match.group(1)
            requested_code = requested_by_symbol.get(symbol)
            if requested_code is None:
                continue
            snapshot = self._parse_quote_fields(requested_code, match.group(2).split("~"))
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots

    @staticmethod
    def _parse_quote_fields(asset_code: str, fields: list[str]) -> QuoteSnapshot | None:
        if len(fields) < 35:
            return None
        price = _safe_decimal(fields[3])
        if price is None or price <= 0:
            return None

        amount = None
        trade_payload = fields[35] if len(fields) > 35 else ""
        trade_parts = str(trade_payload or "").split("/")
        if len(trade_parts) >= 3:
            amount = _safe_decimal(trade_parts[2])
        if amount is None and len(fields) > 37:
            amount_in_ten_thousand = _safe_decimal(fields[37])
            if amount_in_ten_thousand is not None:
                amount = amount_in_ten_thousand * Decimal("10000")

        return QuoteSnapshot(
            stock_code=normalize_asset_code(asset_code, "tencent"),
            price=price,
            change=_safe_decimal(fields[31] if len(fields) > 31 else None),
            change_pct=_safe_float(fields[32] if len(fields) > 32 else None),
            volume=_safe_int(fields[36] if len(fields) > 36 else fields[6]),
            amount=amount,
            high=_safe_decimal(fields[33] if len(fields) > 33 else None),
            low=_safe_decimal(fields[34] if len(fields) > 34 else None),
            open=_safe_decimal(fields[5]),
            pre_close=_safe_decimal(fields[4]),
            source="tencent",
            fetched_at=_parse_tencent_quote_time(fields[30] if len(fields) > 30 else ""),
        )


def _safe_decimal(value: object) -> Decimal | None:
    if value in (None, "", "-"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_float(value: object) -> float | None:
    decimal_value = _safe_decimal(value)
    return float(decimal_value) if decimal_value is not None else None


def _safe_int(value: object) -> int | None:
    if value in (None, "", "-"):
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _parse_tencent_quote_time(raw_value: str) -> datetime:
    try:
        return (
            datetime.strptime(str(raw_value), "%Y%m%d%H%M%S")
            .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            .astimezone(UTC)
        )
    except (ValueError, TypeError):
        return datetime.now(UTC)
