"""Composed equity stock repository.

`DjangoStockRepository` wires the focused stock-info, fundamentals, market-data,
and intraday mixins together and owns the shared code/normalization helpers.
The compatibility facade in `repositories.py` remains the stable import and
monkeypatch surface; do not import it here.
"""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.data_center.application.on_demand import OnDemandDataCenterService
from apps.data_center.application.public import make_on_demand_data_center_service
from apps.data_center.composition import (
    get_asset_repository,
    get_financial_fact_repository,
    get_price_bar_repository,
    get_quote_snapshot_repository,
    get_valuation_fact_repository,
)
from core.exceptions import DataValidationError

from .fundamentals_repository import StockFundamentalsRepositoryMixin
from .intraday_repository import StockIntradayRepositoryMixin
from .market_data_repository import StockMarketDataRepositoryMixin
from .stock_info_repository import StockInfoRepositoryMixin

logger = logging.getLogger(__name__)


class DjangoStockRepository(
    StockInfoRepositoryMixin,
    StockFundamentalsRepositoryMixin,
    StockMarketDataRepositoryMixin,
    StockIntradayRepositoryMixin,
):
    """Django ORM 个股数据仓储"""

    _INTRADAY_SNAPSHOT_MAX_STALE_DAYS = 5
    _INTRADAY_SNAPSHOT_MIN_POINTS = 3

    def __init__(
        self,
        *,
        on_demand_service: OnDemandDataCenterService | None = None,
    ) -> None:
        self._last_intraday_source: str | None = None
        self._dc_asset_repo = get_asset_repository()
        self._dc_financial_repo = get_financial_fact_repository()
        self._dc_price_bar_repo = get_price_bar_repository()
        self._dc_quote_repo = get_quote_snapshot_repository()
        self._dc_valuation_repo = get_valuation_fact_repository()
        self._dc_on_demand = (
            on_demand_service
            if on_demand_service is not None
            else make_on_demand_data_center_service()
        )

    def _safe_decimal(self, value: object) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            decimal_value = Decimal(str(value))
            return None if decimal_value != decimal_value else decimal_value
        except (InvalidOperation, ValueError, TypeError):
            return None

    def _safe_int(self, value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(float(str(value)))
        except (ValueError, TypeError):
            return None

    def _build_stock_code_candidates(self, stock_code: str) -> list[str]:
        normalized = stock_code.strip().upper()
        if not normalized:
            return []

        candidates = [normalized]
        exchange_prefix = normalized[:2]
        prefix_code = normalized[2:]
        if (
            exchange_prefix in {"SH", "SZ", "BJ"}
            and len(prefix_code) == 6
            and prefix_code.isdigit()
        ):
            candidates.append(f"{prefix_code}.{exchange_prefix}")
            candidates.append(prefix_code)
        base_code = normalized.split(".", 1)[0]
        if base_code != normalized:
            candidates.append(base_code)
            market = normalized.split(".", 1)[1]
            if market in {"SH", "SZ", "BJ"}:
                candidates.append(f"{market}{base_code}")
        else:
            market = self._infer_market_from_stock_code(normalized)
            if market:
                candidates.append(f"{base_code}.{market}")

        result: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in result:
                result.append(candidate)
        return result

    def _infer_market_from_stock_code(self, stock_code: str) -> str:
        code = stock_code.strip().upper()
        if code.endswith(".SH"):
            return "SH"
        if code.endswith(".SZ"):
            return "SZ"
        if code.endswith(".BJ"):
            return "BJ"
        if code.startswith("6"):
            return "SH"
        if code.startswith(("0", "3")):
            return "SZ"
        if code.startswith(("4", "8")):
            return "BJ"
        return ""

    def _infer_exchange_from_market(self, market: str) -> str:
        market_code = str(market or "").upper()
        market_map = {
            "SH": "SSE",
            "SZ": "SZSE",
            "BJ": "BSE",
            "HK": "HKEX",
        }
        return market_map.get(market_code, "OTHER")

    def _infer_exchange_from_stock_code(self, stock_code: str) -> str:
        return self._infer_exchange_from_market(self._infer_market_from_stock_code(stock_code))

    def _to_akshare_symbol(self, stock_code: str) -> str:
        return stock_code.split(".")[0] if "." in stock_code else stock_code

    def _to_market_aware_datetime(self, value: object) -> datetime:
        """将分时数据时间转换为 Asia/Shanghai 的 timezone-aware datetime。"""
        if isinstance(value, datetime):
            dt_value = value
        else:
            to_pydatetime = getattr(value, "to_pydatetime", None)
            if not callable(to_pydatetime):
                raise DataValidationError(f"无法解析分时时间: {value!r}")
            converted = to_pydatetime()
            if not isinstance(converted, datetime):
                raise DataValidationError(f"无法解析分时时间: {value!r}")
            dt_value = converted

        market_tz = ZoneInfo("Asia/Shanghai")
        if timezone.is_naive(dt_value):
            return timezone.make_aware(dt_value, market_tz)
        return dt_value.astimezone(market_tz)


__all__ = ["DjangoStockRepository"]
