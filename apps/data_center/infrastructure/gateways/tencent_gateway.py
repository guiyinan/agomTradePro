"""Tencent public gateway for historical A-share and index bars."""

from __future__ import annotations

import logging
from datetime import date

import requests

from apps.data_center.domain.rules import normalize_asset_code
from apps.data_center.infrastructure.gateway_protocols import GatewayProviderProtocol
from apps.data_center.infrastructure.market_gateway_entities import HistoricalPriceBar
from apps.data_center.infrastructure.market_gateway_enums import DataCapability

logger = logging.getLogger(__name__)

_SUPPORTED = {DataCapability.HISTORICAL_PRICE}


class TencentGateway(GatewayProviderProtocol):
    """Fetch historical bars from Tencent's public qfq kline endpoint."""

    _URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    def provider_name(self) -> str:
        return "tencent"

    def supports(self, capability: DataCapability) -> bool:
        return capability in _SUPPORTED

    def get_historical_prices(
        self,
        asset_code: str,
        start_date: str,
        end_date: str,
    ) -> list[HistoricalPriceBar]:
        symbol = self._to_symbol(asset_code)
        if not symbol:
            return []

        try:
            response = requests.get(
                self._URL,
                params={"param": f"{symbol},day,{self._to_query_date(start_date)},{self._to_query_date(end_date)},1000,qfq"},
                headers={
                    "Referer": "https://gu.qq.com/",
                    "User-Agent": "Mozilla/5.0",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
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
