"""Unified provider adapters for Data Center Phase 3.

These adapters wrap existing module-specific gateways/adapters and expose
standardized data_center domain entities only.
"""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import UTC, date, datetime
from time import sleep
from typing import Any

import requests

from apps.data_center.domain.entities import (
    CapitalFlowFact,
    FinancialFact,
    FundNavFact,
    MacroFact,
    NewsFact,
    PriceBar,
    ProviderConfig,
    QuoteSnapshot,
    SectorMembershipFact,
    ValuationFact,
)
from apps.data_center.domain.enums import (
    DataCapability,
    DataQualityStatus,
    FinancialPeriodType,
)
from apps.data_center.domain.protocols import UnifiedDataProviderProtocol
from apps.data_center.infrastructure.macro_sources.base import (
    MacroAdapterProtocol,
    MacroDataPoint,
)
from shared.numeric import safe_float

logger = logging.getLogger(__name__)


def _fetch_macro_points(
    adapter: MacroAdapterProtocol,
    indicator_code: str,
    start_date: date,
    end_date: date,
) -> list[MacroDataPoint]:
    """Fetch macro points and expose source failures as recoverable connection errors."""

    try:
        return adapter.fetch(indicator_code, start_date, end_date)
    except Exception as exc:
        if exc.__class__.__name__ == "DataSourceUnavailableError":
            raise ConnectionError("macro_source_unavailable") from exc
        raise


_SOURCE_CAPABILITIES: dict[str, set[DataCapability]] = {
    "tushare": {
        DataCapability.MACRO,
        DataCapability.HISTORICAL_PRICE,
        DataCapability.REALTIME_QUOTE,
        DataCapability.FUND_NAV,
        DataCapability.FINANCIAL,
        DataCapability.VALUATION,
    },
    "akshare": {
        DataCapability.MACRO,
        DataCapability.HISTORICAL_PRICE,
        DataCapability.REALTIME_QUOTE,
        DataCapability.FUND_NAV,
        DataCapability.FINANCIAL,
        DataCapability.VALUATION,
        DataCapability.SECTOR_MEMBERSHIP,
        DataCapability.NEWS,
        DataCapability.CAPITAL_FLOW,
    },
    "eastmoney": {
        DataCapability.MACRO,
        DataCapability.HISTORICAL_PRICE,
        DataCapability.REALTIME_QUOTE,
        DataCapability.NEWS,
        DataCapability.CAPITAL_FLOW,
    },
    "qmt": {
        DataCapability.HISTORICAL_PRICE,
        DataCapability.REALTIME_QUOTE,
    },
    "fred": {
        DataCapability.MACRO,
    },
}

_FRED_SERIES_MAP: dict[str, tuple[str, str, str]] = {
    "US_FED_FUNDS_RATE": ("FEDFUNDS", "%", "M"),
    "US_CPI": ("CPIAUCSL", "指数", "M"),
    "US_CORE_CPI": ("CPILFESL", "指数", "M"),
    "US_UNEMPLOYMENT": ("UNRATE", "%", "M"),
    "US_GDP": ("GDP", "亿美元", "Q"),
}


def _ensure_aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_period_type(report_type: str) -> FinancialPeriodType:
    normalized = str(report_type).strip().lower()
    if normalized in {"annual", "4q", "year", "y"}:
        return FinancialPeriodType.ANNUAL
    if normalized in {"2q", "semi", "semi_annual", "half_year"}:
        return FinancialPeriodType.SEMI_ANNUAL
    if normalized in {"1q", "3q", "quarter", "quarterly"}:
        return FinancialPeriodType.QUARTERLY
    if normalized == "ttm":
        return FinancialPeriodType.TTM
    return FinancialPeriodType.QUARTERLY


def _period_type_from_period_end(period_end: date) -> FinancialPeriodType:
    if period_end.month == 12:
        return FinancialPeriodType.ANNUAL
    if period_end.month == 6:
        return FinancialPeriodType.SEMI_ANNUAL
    return FinancialPeriodType.QUARTERLY


def _safe_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        try:
            parsed = value.date()
            return parsed if isinstance(parsed, date) else None
        except (TypeError, ValueError):
            return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.strptime(str(value)[:8], "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


def _safe_month_end_date(value: Any) -> date | None:
    parsed = _safe_date(value)
    if parsed is not None:
        return parsed
    raw_value = str(value or "").strip()
    try:
        parsed_month = datetime.strptime(raw_value[:7], "%Y-%m").date()
    except (TypeError, ValueError):
        return None
    return date(
        parsed_month.year,
        parsed_month.month,
        monthrange(parsed_month.year, parsed_month.month)[1],
    )


def _request_error_is_permission_denied(exc: requests.RequestException) -> bool:
    """Return whether the request failed because outbound sockets are locally blocked."""

    markers = ("WinError 10013", "PermissionError", "访问权限不允许")
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, PermissionError):
            return True
        message = str(current)
        if any(marker in message for marker in markers):
            return True
        current = current.__cause__ or current.__context__
    return False


_MARKET_NEWS_POSITIVE_KEYWORDS = (
    "上涨",
    "回升",
    "走强",
    "净流入",
    "反弹",
    "修复",
    "改善",
    "增长",
    "突破",
    "新高",
)
_MARKET_NEWS_NEGATIVE_KEYWORDS = (
    "下跌",
    "走弱",
    "净流出",
    "回落",
    "杀跌",
    "风险",
    "波动",
    "承压",
    "收缩",
    "新低",
)


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _valuation_period(start_date: date, end_date: date) -> str:
    span_days = max((end_date - start_date).days, 0)
    if span_days <= 366:
        return "近一年"
    if span_days <= 366 * 3:
        return "近三年"
    if span_days <= 366 * 5:
        return "近五年"
    if span_days <= 366 * 10:
        return "近十年"
    return "全部"


def _score_market_news_sentiment(text: str) -> float:
    """Heuristically score one market-news text into [-1, 1]."""

    normalized = str(text or "").strip()
    if not normalized:
        return 0.0

    positive_hits = sum(1 for item in _MARKET_NEWS_POSITIVE_KEYWORDS if item in normalized)
    negative_hits = sum(1 for item in _MARKET_NEWS_NEGATIVE_KEYWORDS if item in normalized)
    raw_score = (positive_hits - negative_hits) / 3.0
    return max(-1.0, min(1.0, raw_score))


class BaseUnifiedProviderAdapter(UnifiedDataProviderProtocol):
    """Base class for standardized data-center providers."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self._caps = _SOURCE_CAPABILITIES.get(config.source_type, set())

    def provider_name(self) -> str:
        return self._config.name

    def provider_source(self) -> str:
        source_type = str(self._config.source_type or "").strip()
        return source_type or self.provider_name()

    def _provider_extra(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(extra or {})
        payload.setdefault("provider_name", self.provider_name())
        payload["source_type"] = self.provider_source()
        return payload

    def supports(self, capability: DataCapability) -> bool:
        return capability in self._caps

    def fetch_macro_series(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        return []

    def fetch_price_history(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[PriceBar]:
        return []

    def fetch_quote_snapshots(
        self,
        asset_codes: list[str],
    ) -> list[QuoteSnapshot]:
        return []

    def fetch_fund_nav(
        self,
        fund_code: str,
        start_date: date,
        end_date: date,
    ) -> list[FundNavFact]:
        return []

    def fetch_financials(
        self,
        asset_code: str,
        periods: int = 8,
    ) -> list[FinancialFact]:
        return []

    def fetch_valuations(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationFact]:
        return []

    def fetch_sector_memberships(
        self,
        sector_code: str = "",
        sector_name: str = "",
        effective_date: date | None = None,
    ) -> list[SectorMembershipFact]:
        return []

    def fetch_news(
        self,
        asset_code: str,
        limit: int = 20,
    ) -> list[NewsFact]:
        return []

    def fetch_capital_flows(
        self,
        asset_code: str,
        period: str = "5d",
    ) -> list[CapitalFlowFact]:
        return []

    def _fetch_market_turnover_from_tencent(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        """Fallback broad A-share turnover to Tencent historical index amounts."""

        from apps.data_center.infrastructure.gateways.tencent_gateway import TencentGateway

        gateway = TencentGateway(timeout=10.0)
        rows_by_date: dict[date, float] = {}
        for asset_code in ("000001.SH", "399001.SZ"):
            bars = gateway.get_historical_prices(
                asset_code,
                start_date.strftime("%Y%m%d"),
                end_date.strftime("%Y%m%d"),
            )
            for bar in bars:
                if bar.amount is None:
                    continue
                if bar.trade_date < start_date or bar.trade_date > end_date:
                    continue
                rows_by_date[bar.trade_date] = rows_by_date.get(bar.trade_date, 0.0) + float(
                    bar.amount
                )

        return [
            MacroFact(
                indicator_code="CN_A_TOTAL_TURNOVER",
                reporting_period=observed_at,
                value=value,
                unit="元",
                source=self.provider_source(),
                published_at=observed_at,
                quality=DataQualityStatus.VALID,
                extra=self._provider_extra(
                    {
                        "proxy": "tencent_index_history_sh000001_plus_sz399001",
                        "fallback_provider": "tencent",
                    }
                ),
            )
            for observed_at, value in sorted(rows_by_date.items())
        ]

    def _fetch_market_turnover_from_eastmoney_quote(
        self,
        target_date: date,
    ) -> list[MacroFact]:
        """Fallback broad A-share turnover to EastMoney direct index quote amounts."""

        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            _EASTMONEY_QUOTE_URL,
            _QUOTE_FIELDS,
            _eastmoney_direct_network,
            _to_secid,
        )

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "application/json,text/plain,*/*",
        }
        total_amount = 0.0
        success_count = 0
        expected_index_count = 2
        with _eastmoney_direct_network():
            with requests.Session() as session:
                session.headers.update(headers)
                for asset_code in ("000001.SH", "399001.SZ"):
                    params = {
                        "secid": _to_secid(asset_code),
                        "fields": _QUOTE_FIELDS,
                        "invt": "2",
                        "fltt": "1",
                    }
                    amount = None
                    for attempt in range(1, 4):
                        try:
                            response = session.get(_EASTMONEY_QUOTE_URL, params=params, timeout=10)
                            response.raise_for_status()
                            data = (response.json() or {}).get("data") or {}
                            amount = safe_float(data.get("f48"))
                            break
                        except requests.RequestException as exc:
                            if _request_error_is_permission_denied(exc):
                                logger.warning(
                                    "EastMoney direct turnover quote blocked by local socket policy: asset=%s",
                                    asset_code,
                                )
                                raise ConnectionError("market_source_unavailable") from exc
                            if attempt == 3:
                                logger.warning(
                                    "EastMoney direct turnover quote failed: asset=%s error_type=%s",
                                    asset_code,
                                    exc.__class__.__name__,
                                )
                            else:
                                sleep(0.6 * attempt)
                    if amount is None:
                        continue
                    total_amount += amount
                    success_count += 1

        if success_count < expected_index_count:
            return []

        return [
            MacroFact(
                indicator_code="CN_A_TOTAL_TURNOVER",
                reporting_period=target_date,
                value=total_amount,
                unit="元",
                source=self.provider_source(),
                published_at=target_date,
                quality=DataQualityStatus.VALID,
                extra=self._provider_extra(
                    {
                        "proxy": "eastmoney_quote_sh000001_plus_sz399001",
                        "fallback_provider": "eastmoney_direct_quote",
                        "successful_index_count": success_count,
                    }
                ),
            )
        ]
