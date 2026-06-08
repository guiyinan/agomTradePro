"""Unified provider adapters for Data Center Phase 3.

These adapters wrap existing module-specific gateways/adapters and expose
standardized data_center domain entities only.
"""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from time import perf_counter, sleep
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
    PriceAdjustment,
)
from apps.data_center.domain.protocols import UnifiedDataProviderProtocol
from apps.data_center.domain.rules import normalize_asset_code
from core.integration.data_center_business_sources import (
    build_akshare_fund_adapter,
    build_akshare_macro_adapter,
    build_akshare_sector_adapter,
    build_tushare_financial_gateway,
    build_tushare_fund_adapter,
    build_tushare_macro_adapter,
    build_tushare_valuation_gateway,
)

logger = logging.getLogger(__name__)

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


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
        return None if number != number else number
    except (TypeError, ValueError):
        return None


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


class TushareUnifiedProviderAdapter(BaseUnifiedProviderAdapter):
    """Standardized Tushare provider wrapper."""

    def fetch_macro_series(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        if indicator_code == "CN_A_TOTAL_TURNOVER":
            return self._fetch_market_turnover(start_date, end_date)
        if indicator_code == "CN_A_MARGIN_BALANCE":
            return self._fetch_margin_balance(start_date, end_date)
        if indicator_code == "CN_A_ETF_NET_FLOW":
            return []
        if indicator_code == "CN_A_ETF_NET_FLOW_MAIN":
            return []
        if indicator_code == "CN_A_ETF_SIZE_FLOW":
            return self._fetch_etf_size_flow(start_date, end_date)

        adapter = build_tushare_macro_adapter(
            token=self._config.api_key,
            http_url=self._config.http_url,
        )
        fetch_code = "SHIBOR" if indicator_code == "CN_SHIBOR" else indicator_code
        points = adapter.fetch(fetch_code, start_date, end_date)
        results: list[MacroFact] = []
        for point in points:
            observed_at = getattr(point, "observed_at", None)
            if observed_at is None:
                continue
            results.append(
                MacroFact(
                    indicator_code=indicator_code,
                    reporting_period=observed_at,
                    value=float(point.value),
                    unit=getattr(point, "unit", "") or "",
                    source=self.provider_source(),
                    published_at=getattr(point, "published_at", None),
                    quality=DataQualityStatus.VALID,
                    extra=self._provider_extra(
                        {
                            "original_unit": getattr(point, "original_unit", "")
                            or getattr(point, "unit", "")
                            or "",
                        }
                    ),
                )
            )
        return results

    def _fetch_market_turnover(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        """Fetch broad A-share turnover from Tushare index daily amount fields."""

        from shared.infrastructure.tushare_client import create_tushare_pro_client

        pro = create_tushare_pro_client(token=self._config.api_key, http_url=self._config.http_url)
        rows_by_date: dict[date, float] = {}
        for ts_code in ("000001.SH", "399001.SZ"):
            df = pro.index_daily(
                ts_code=ts_code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
            if df is None or df.empty:
                continue
            for row in df.to_dict("records"):
                observed_at = _safe_date(_first_present(row, "trade_date", "date"))
                if observed_at is None:
                    continue
                amount = _safe_float(_first_present(row, "amount"))
                if amount is None:
                    continue
                rows_by_date[observed_at] = rows_by_date.get(observed_at, 0.0) + amount * 1000.0

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
                        "proxy": "tushare_index_daily_sh000001_plus_sz399001",
                        "original_unit": "千元",
                    }
                ),
            )
            for observed_at, value in sorted(rows_by_date.items())
        ]

    def _fetch_margin_balance(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        """Fetch A-share financing balance from Tushare margin rows."""

        from shared.infrastructure.tushare_client import create_tushare_pro_client

        pro = create_tushare_pro_client(token=self._config.api_key, http_url=self._config.http_url)
        df = pro.margin(
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return []

        rows_by_date: dict[date, float] = {}
        for row in df.to_dict("records"):
            observed_at = _safe_date(_first_present(row, "trade_date", "date"))
            if observed_at is None:
                continue
            value = _safe_float(_first_present(row, "rzye"))
            if value is None:
                continue
            rows_by_date[observed_at] = rows_by_date.get(observed_at, 0.0) + value

        return [
            MacroFact(
                indicator_code="CN_A_MARGIN_BALANCE",
                reporting_period=observed_at,
                value=value,
                unit="元",
                source=self.provider_source(),
                published_at=observed_at,
                quality=DataQualityStatus.VALID,
                extra=self._provider_extra(
                    {
                        "proxy": "tushare_margin_sum_rzye",
                        "original_unit": "元",
                    }
                ),
            )
            for observed_at, value in sorted(rows_by_date.items())
        ]

    def _fetch_etf_size_flow(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        """Fetch ETF net flow proxy from Tushare ETF daily size deltas."""

        from shared.infrastructure.tushare_client import create_tushare_pro_client

        pro = create_tushare_pro_client(token=self._config.api_key, http_url=self._config.http_url)
        trade_dates = self._fetch_tushare_open_dates(pro, start_date, end_date)
        if len(trade_dates) < 2:
            return []

        facts: list[MacroFact] = []
        for previous_date, current_date in zip(trade_dates, trade_dates[1:], strict=False):
            previous_size = self._fetch_tushare_etf_total_size(pro, previous_date)
            current_size = self._fetch_tushare_etf_total_size(pro, current_date)
            if previous_size is None or current_size is None:
                continue
            facts.append(
                MacroFact(
                    indicator_code="CN_A_ETF_SIZE_FLOW",
                    reporting_period=current_date,
                    value=(current_size - previous_size) * 10_000.0,
                    unit="元",
                    source=self.provider_source(),
                    published_at=current_date,
                    quality=DataQualityStatus.VALID,
                    extra=self._provider_extra(
                        {
                            "proxy": "tushare_etf_share_size_delta",
                            "flow_method": "etf_size_delta",
                            "original_unit": "万元",
                            "previous_trade_date": previous_date.isoformat(),
                            "current_total_size_wan": current_size,
                            "previous_total_size_wan": previous_size,
                        }
                    ),
                )
            )
        return facts

    def _fetch_tushare_open_dates(self, pro: Any, start_date: date, end_date: date) -> list[date]:
        lookback_start = start_date - timedelta(days=10)
        df = pro.trade_cal(
            exchange="SSE",
            start_date=lookback_start.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return []
        dates: list[date] = []
        for row in df.to_dict("records"):
            is_open = str(_first_present(row, "is_open") or "").strip()
            if is_open not in {"1", "1.0", "True", "true"}:
                continue
            trade_date = _safe_date(_first_present(row, "cal_date", "trade_date"))
            if trade_date is not None and trade_date <= end_date:
                dates.append(trade_date)
        return sorted(set(dates))

    def _fetch_tushare_etf_total_size(self, pro: Any, trade_date: date) -> float | None:
        total_size = 0.0
        seen_rows = 0
        for exchange in ("SSE", "SZSE"):
            df = pro.etf_share_size(
                trade_date=trade_date.strftime("%Y%m%d"),
                exchange=exchange,
            )
            if df is None or df.empty:
                continue
            for row in df.to_dict("records"):
                value = _safe_float(_first_present(row, "total_size"))
                if value is None:
                    continue
                total_size += value
                seen_rows += 1
        return total_size if seen_rows else None

    def fetch_price_history(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[PriceBar]:
        from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway

        gateway = TushareGateway()
        canonical_asset_code = normalize_asset_code(asset_code, "tushare")
        bars = gateway.get_historical_prices(
            asset_code=canonical_asset_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        return [
            PriceBar(
                asset_code=canonical_asset_code,
                bar_date=bar.trade_date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=float(bar.volume) if bar.volume is not None else None,
                amount=bar.amount,
                source=self.provider_source(),
                adjustment=PriceAdjustment.NONE,
            )
            for bar in bars
        ]

    def fetch_quote_snapshots(self, asset_codes: list[str]) -> list[QuoteSnapshot]:
        from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway

        gateway = TushareGateway()
        quotes = gateway.get_quote_snapshots(asset_codes)
        return [
            QuoteSnapshot(
                asset_code=normalize_asset_code(quote.stock_code, "tushare"),
                snapshot_at=_ensure_aware(getattr(quote, "fetched_at", None)),
                current_price=float(quote.price),
                source=self.provider_source(),
                open=_safe_float(quote.open),
                high=_safe_float(quote.high),
                low=_safe_float(quote.low),
                prev_close=_safe_float(quote.pre_close),
                volume=float(quote.volume) if quote.volume is not None else None,
                amount=_safe_float(quote.amount),
                extra=self._provider_extra(),
            )
            for quote in quotes
        ]

    def fetch_fund_nav(
        self,
        fund_code: str,
        start_date: date,
        end_date: date,
    ) -> list[FundNavFact]:
        adapter = build_tushare_fund_adapter(
            token=self._config.api_key,
            http_url=self._config.http_url,
        )
        df = adapter.fetch_fund_daily(
            fund_code=fund_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return []

        facts: list[FundNavFact] = []
        for row in df.itertuples(index=False):
            nav_date = row.trade_date.date()
            facts.append(
                FundNavFact(
                    fund_code=fund_code,
                    nav_date=nav_date,
                    nav=float(row.unit_nav),
                    acc_nav=_safe_float(getattr(row, "accum_nav", None)),
                    source=self.provider_source(),
                    extra=self._provider_extra(),
                )
            )
        return facts

    def fetch_financials(self, asset_code: str, periods: int = 8) -> list[FinancialFact]:
        gateway = build_tushare_financial_gateway(
            token=self._config.api_key,
            http_url=self._config.http_url,
        )
        batch = gateway.fetch(asset_code, periods=periods)
        facts: list[FinancialFact] = []
        for record in batch.records:
            common = {
                "asset_code": record.stock_code,
                "period_end": record.report_date,
                "period_type": _to_period_type(record.report_type),
                "source": self.provider_source(),
                "extra": self._provider_extra(),
            }
            facts.extend(
                [
                    FinancialFact(
                        metric_code="revenue", value=float(record.revenue), unit="元", **common
                    ),
                    FinancialFact(
                        metric_code="net_profit",
                        value=float(record.net_profit),
                        unit="元",
                        **common,
                    ),
                    FinancialFact(
                        metric_code="total_assets",
                        value=float(record.total_assets),
                        unit="元",
                        **common,
                    ),
                    FinancialFact(
                        metric_code="total_liabilities",
                        value=float(record.total_liabilities),
                        unit="元",
                        **common,
                    ),
                    FinancialFact(
                        metric_code="equity", value=float(record.equity), unit="元", **common
                    ),
                    FinancialFact(metric_code="roe", value=float(record.roe), unit="%", **common),
                    FinancialFact(
                        metric_code="debt_ratio", value=float(record.debt_ratio), unit="%", **common
                    ),
                ]
            )
            if record.roa is not None:
                facts.append(
                    FinancialFact(metric_code="roa", value=float(record.roa), unit="%", **common)
                )
            if record.revenue_growth is not None:
                facts.append(
                    FinancialFact(
                        metric_code="revenue_growth",
                        value=float(record.revenue_growth),
                        unit="%",
                        **common,
                    )
                )
            if record.net_profit_growth is not None:
                facts.append(
                    FinancialFact(
                        metric_code="net_profit_growth",
                        value=float(record.net_profit_growth),
                        unit="%",
                        **common,
                    )
                )
        return facts

    def fetch_valuations(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationFact]:
        gateway = build_tushare_valuation_gateway(
            token=self._config.api_key,
            http_url=self._config.http_url,
        )
        batch = gateway.fetch(asset_code, start_date=start_date, end_date=end_date)
        return [
            ValuationFact(
                asset_code=record.stock_code,
                val_date=record.trade_date,
                pe_ttm=float(record.pe) if record.pe is not None else None,
                pb=float(record.pb) if record.pb is not None else None,
                ps_ttm=float(record.ps) if record.ps is not None else None,
                market_cap=float(record.total_mv) if record.total_mv is not None else None,
                float_market_cap=float(record.circ_mv) if record.circ_mv is not None else None,
                dv_ratio=(
                    float(record.dividend_yield) if record.dividend_yield is not None else None
                ),
                source=self.provider_source(),
                extra=self._provider_extra(),
            )
            for record in batch.records
        ]


class AkshareUnifiedProviderAdapter(BaseUnifiedProviderAdapter):
    """Standardized AKShare provider wrapper."""

    def fetch_macro_series(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        if indicator_code == "CN_A_TOTAL_TURNOVER":
            return self._fetch_market_turnover(start_date, end_date)
        if indicator_code == "CN_A_MARGIN_BALANCE":
            return self._fetch_margin_balance(start_date, end_date)
        if indicator_code in {"CN_A_ETF_NET_FLOW", "CN_A_ETF_NET_FLOW_MAIN"}:
            return self._fetch_etf_net_flow(start_date, end_date, indicator_code=indicator_code)
        if indicator_code == "CN_A_ETF_SIZE_FLOW":
            return []
        if indicator_code == "CN_A_NEW_INVESTOR_ACCOUNTS":
            return self._fetch_new_investor_accounts(start_date, end_date)

        adapter = build_akshare_macro_adapter()
        points = adapter.fetch(indicator_code, start_date, end_date)
        results: list[MacroFact] = []
        for point in points:
            observed_at = getattr(point, "observed_at", None)
            if observed_at is None:
                continue
            results.append(
                MacroFact(
                    indicator_code=indicator_code,
                    reporting_period=observed_at,
                    value=float(point.value),
                    unit=getattr(point, "unit", "") or "",
                    source=self.provider_source(),
                    published_at=getattr(point, "published_at", None),
                    quality=DataQualityStatus.VALID,
                    extra=self._provider_extra(
                        {
                            "original_unit": getattr(point, "original_unit", "")
                            or getattr(point, "unit", "")
                            or "",
                        }
                    ),
                )
            )
        return results

    def _fetch_market_turnover(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        """Approximate total A-share turnover by summing SH/SZ broad-index amounts."""

        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            _eastmoney_direct_network,
        )
        from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module

        ak = get_akshare_module()
        index_symbols = ("sh000001", "sz399001")
        rows_by_date: dict[date, float] = {}

        for symbol in index_symbols:
            with _eastmoney_direct_network():
                df = ak.stock_zh_index_daily_em(symbol=symbol)
            if df is None or df.empty:
                continue
            for row in df.to_dict("records"):
                observed_at = _safe_date(_first_present(row, "date", "日期"))
                if observed_at is None or observed_at < start_date or observed_at > end_date:
                    continue
                amount = _safe_float(_first_present(row, "amount", "成交额"))
                if amount is None:
                    continue
                rows_by_date[observed_at] = rows_by_date.get(observed_at, 0.0) + amount

        return [
            MacroFact(
                indicator_code="CN_A_TOTAL_TURNOVER",
                reporting_period=observed_at,
                value=value,
                unit="元",
                source=self.provider_source(),
                quality=DataQualityStatus.VALID,
                extra=self._provider_extra({"proxy": "sh_index_plus_sz_index"}),
            )
            for observed_at, value in sorted(rows_by_date.items())
        ]

    def _fetch_margin_balance(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        """Fetch total A-share margin balance by summing SH and SZ market rows."""

        from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module

        ak = get_akshare_module()
        sh_df = ak.macro_china_market_margin_sh()
        sz_df = ak.macro_china_market_margin_sz()
        rows_by_date: dict[date, float] = {}

        for df in (sh_df, sz_df):
            if df is None or df.empty:
                continue
            for row in df.to_dict("records"):
                observed_at = _safe_date(_first_present(row, "日期", "date"))
                if observed_at is None or observed_at < start_date or observed_at > end_date:
                    continue
                value = _safe_float(_first_present(row, "融资余额"))
                if value is None:
                    continue
                rows_by_date[observed_at] = rows_by_date.get(observed_at, 0.0) + value

        return [
            MacroFact(
                indicator_code="CN_A_MARGIN_BALANCE",
                reporting_period=observed_at,
                value=value,
                unit="元",
                source=self.provider_source(),
                quality=DataQualityStatus.VALID,
                extra=self._provider_extra({"proxy": "sh_margin_plus_sz_margin"}),
            )
            for observed_at, value in sorted(rows_by_date.items())
        ]

    def _fetch_etf_net_flow(
        self,
        start_date: date,
        end_date: date,
        *,
        indicator_code: str = "CN_A_ETF_NET_FLOW",
    ) -> list[MacroFact]:
        """Fetch market-wide ETF net flow from the latest ETF spot snapshot."""

        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            _eastmoney_direct_network,
        )
        from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module

        records: list[dict[str, Any]] = []
        proxy_name = "fund_etf_spot_em"
        try:
            ak = get_akshare_module()
            with _eastmoney_direct_network():
                df = ak.fund_etf_spot_em()
            if df is not None and not df.empty:
                records = df.to_dict("records")
        except (ConnectionError, OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            logger.warning("AKShare ETF spot fetch failed, trying EastMoney direct: %s", exc)

        if not records:
            records = self._fetch_etf_spot_records_direct()
            proxy_name = "eastmoney_clist_get"

        if not records:
            return []

        observed_at: date | None = None
        total_flow = 0.0
        for row in records:
            current_date = _safe_date(_first_present(row, "数据日期", "f297"))
            if current_date is None:
                continue
            observed_at = current_date if observed_at is None else max(observed_at, current_date)
            flow = _safe_float(_first_present(row, "主力净流入-净额", "f62"))
            if flow is not None:
                total_flow += flow

        if observed_at is None or observed_at < start_date or observed_at > end_date:
            return []

        return [
            MacroFact(
                indicator_code=indicator_code,
                reporting_period=observed_at,
                value=total_flow,
                unit="元",
                source=self.provider_source(),
                quality=DataQualityStatus.VALID,
                extra=self._provider_extra({"proxy": proxy_name}),
            )
        ]

    def _fetch_etf_spot_records_direct(self) -> list[dict[str, Any]]:
        """Fetch ETF spot rows directly from EastMoney when AKShare is unavailable."""

        urls = (
            "https://88.push2.eastmoney.com/api/qt/clist/get",
            "https://82.push2.eastmoney.com/api/qt/clist/get",
            "https://push2.eastmoney.com/api/qt/clist/get",
        )
        base_params = {
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "wbp2u": "|0|0|0|web",
            "fid": "f12",
            "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024,b:MK0827",
            "fields": "f12,f14,f62,f297,f124",
            "pz": "500",
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            "Referer": "https://quote.eastmoney.com/center/gridlist.html",
            "Accept": "application/json,text/plain,*/*",
        }

        def _fetch_pages(url: str) -> list[dict[str, Any]]:
            page = 1
            records: list[dict[str, Any]] = []
            total: int | None = None
            while total is None or len(records) < total:
                params = {**base_params, "pn": str(page)}
                response = requests.get(url, params=params, headers=headers, timeout=10)
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data") or {}
                diff = data.get("diff") or []
                if not isinstance(diff, list) or not diff:
                    break
                if total is None:
                    try:
                        total = int(data.get("total") or len(diff))
                    except (TypeError, ValueError):
                        total = len(diff)
                records.extend([row for row in diff if isinstance(row, dict)])
                page += 1
            return records

        def _fetch_with_retries() -> list[dict[str, Any]]:
            last_error: requests.RequestException | None = None
            for attempt in range(1, 4):
                for url in urls:
                    try:
                        records = _fetch_pages(url)
                        if records:
                            return records
                    except requests.RequestException as exc:
                        last_error = exc
                        logger.warning(
                            "EastMoney ETF direct fetch failed: url=%s attempt=%d error=%s",
                            url,
                            attempt,
                            exc,
                        )
                if attempt < 3:
                    sleep(1.5 * attempt)
            if last_error is not None:
                raise last_error
            return []

        try:
            return _fetch_with_retries()
        except requests.RequestException as exc:
            logger.warning(
                "EastMoney ETF direct fetch exhausted default network, retrying without proxy: %s",
                exc,
            )

        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            _eastmoney_direct_network,
        )

        try:
            with _eastmoney_direct_network():
                return _fetch_with_retries()
        except requests.RequestException as exc:
            raise ConnectionError(str(exc)) from exc

    def _fetch_new_investor_accounts(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        """Fetch monthly new investor-account statistics from EastMoney via AKShare."""

        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            _eastmoney_direct_network,
        )
        from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module

        ak = get_akshare_module()
        with _eastmoney_direct_network():
            df = ak.stock_account_statistics_em()
        if df is None or df.empty:
            return []

        facts: list[MacroFact] = []
        for row in df.to_dict("records"):
            observed_at = _safe_month_end_date(_first_present(row, "数据日期", "date", "month"))
            if observed_at is None or observed_at < start_date or observed_at > end_date:
                continue
            value_wan = _safe_float(
                _first_present(
                    row,
                    "新增投资者-数量",
                    "新增投资者数量",
                    "new_investors",
                    "new_accounts",
                )
            )
            if value_wan is None:
                continue
            facts.append(
                MacroFact(
                    indicator_code="CN_A_NEW_INVESTOR_ACCOUNTS",
                    reporting_period=observed_at,
                    value=value_wan * 10_000.0,
                    unit="户",
                    source=self.provider_source(),
                    quality=DataQualityStatus.VALID,
                    extra=self._provider_extra(
                        {
                            "proxy": "stock_account_statistics_em",
                            "original_unit": "万户",
                            "raw_new_investor_count": value_wan,
                        }
                    ),
                )
            )
        return sorted(facts, key=lambda item: item.reporting_period)

    def fetch_price_history(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[PriceBar]:
        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            AKShareEastMoneyGateway,
        )

        gateway = AKShareEastMoneyGateway()
        canonical_asset_code = normalize_asset_code(asset_code, "akshare")
        bars = gateway.get_historical_prices(
            asset_code=canonical_asset_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        return [
            PriceBar(
                asset_code=canonical_asset_code,
                bar_date=bar.trade_date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=float(bar.volume) if bar.volume is not None else None,
                amount=bar.amount,
                source=self.provider_source(),
            )
            for bar in bars
        ]

    def fetch_quote_snapshots(self, asset_codes: list[str]) -> list[QuoteSnapshot]:
        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            AKShareEastMoneyGateway,
        )

        gateway = AKShareEastMoneyGateway()
        quotes = gateway.get_quote_snapshots(asset_codes)
        return [
            QuoteSnapshot(
                asset_code=normalize_asset_code(quote.stock_code, "akshare"),
                snapshot_at=_ensure_aware(getattr(quote, "fetched_at", None)),
                current_price=float(quote.price),
                source=self.provider_source(),
                open=_safe_float(quote.open),
                high=_safe_float(quote.high),
                low=_safe_float(quote.low),
                prev_close=_safe_float(quote.pre_close),
                volume=float(quote.volume) if quote.volume is not None else None,
                amount=_safe_float(quote.amount),
                extra=self._provider_extra(),
            )
            for quote in quotes
        ]

    def fetch_fund_nav(
        self,
        fund_code: str,
        start_date: date,
        end_date: date,
    ) -> list[FundNavFact]:
        adapter = build_akshare_fund_adapter()
        df = adapter.fetch_fund_nav_em(fund_code.split(".")[0])
        if df is None or df.empty:
            return []

        facts: list[FundNavFact] = []
        for row in df.to_dict("records"):
            nav_date = row.get("nav_date")
            if nav_date is None:
                continue
            nav_date = nav_date.date() if hasattr(nav_date, "date") else nav_date
            if nav_date < start_date or nav_date > end_date:
                continue
            facts.append(
                FundNavFact(
                    fund_code=fund_code,
                    nav_date=nav_date,
                    nav=float(row.get("unit_nav")),
                    acc_nav=_safe_float(row.get("累计净值")),
                    source=self.provider_source(),
                    extra=self._provider_extra(),
                )
            )
        return facts

    def fetch_financials(self, asset_code: str, periods: int = 8) -> list[FinancialFact]:
        from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module

        ak = get_akshare_module()
        canonical_asset_code = normalize_asset_code(asset_code, "akshare")
        df = ak.stock_financial_analysis_indicator_em(
            symbol=canonical_asset_code,
            indicator="按报告期",
        )
        if df is None or df.empty:
            return []

        facts: list[FinancialFact] = []
        for row in df.to_dict("records")[:periods]:
            period_end = _safe_date(_first_present(row, "REPORT_DATE", "报告期"))
            if period_end is None:
                continue

            revenue = _safe_float(_first_present(row, "TOTALOPERATEREVE", "营业总收入"))
            net_profit = _safe_float(_first_present(row, "PARENTNETPROFIT", "归母净利润"))
            roe = _safe_float(_first_present(row, "ROEJQ", "ROE_DILUTED", "净资产收益率"))
            debt_ratio = _safe_float(_first_present(row, "ZCFZL", "资产负债率"))
            total_liabilities = _safe_float(_first_present(row, "LIABILITY", "负债合计"))
            total_assets = _safe_float(_first_present(row, "TOTAL_ASSETS", "总资产"))
            if total_assets is None and total_liabilities is not None and debt_ratio:
                total_assets = total_liabilities / (debt_ratio / 100)
            equity = _safe_float(_first_present(row, "TOTAL_EQUITY", "股东权益合计"))
            if equity is None and total_assets is not None and total_liabilities is not None:
                equity = total_assets - total_liabilities

            if revenue is None or net_profit is None or roe is None or debt_ratio is None:
                continue

            common = {
                "asset_code": canonical_asset_code,
                "period_end": period_end,
                "period_type": _period_type_from_period_end(period_end),
                "source": self.provider_source(),
                "report_date": period_end,
                "extra": self._provider_extra(),
            }
            metric_values = {
                "revenue": (revenue, "元"),
                "net_profit": (net_profit, "元"),
                "revenue_growth": (
                    _safe_float(_first_present(row, "TOTALOPERATEREVETZ", "营收同比")),
                    "%",
                ),
                "net_profit_growth": (
                    _safe_float(_first_present(row, "PARENTNETPROFITTZ", "归母净利润同比")),
                    "%",
                ),
                "total_assets": (total_assets or 0.0, "元"),
                "total_liabilities": (total_liabilities or 0.0, "元"),
                "equity": (equity or 0.0, "元"),
                "roe": (roe, "%"),
                "roa": (_safe_float(_first_present(row, "JROA", "ZZCJLL", "总资产收益率")), "%"),
                "debt_ratio": (debt_ratio, "%"),
            }
            for metric_code, (value, unit) in metric_values.items():
                if value is None:
                    continue
                facts.append(
                    FinancialFact(metric_code=metric_code, value=value, unit=unit, **common)
                )
        return facts

    def fetch_valuations(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationFact]:
        from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module

        ak = get_akshare_module()
        symbol = asset_code.strip().upper().split(".", 1)[0]
        canonical_asset_code = normalize_asset_code(asset_code, "akshare")
        period = _valuation_period(start_date, end_date)
        indicator_fields = {
            "市盈率(TTM)": "pe_ttm",
            "市盈率(静)": "pe_static",
            "市净率": "pb",
            "总市值": "market_cap",
        }

        rows_by_date: dict[date, dict[str, float]] = {}
        for indicator, field in indicator_fields.items():
            df = ak.stock_zh_valuation_baidu(
                symbol=symbol,
                indicator=indicator,
                period=period,
            )
            if df is None or df.empty:
                continue

            for row in df.to_dict("records"):
                val_date = _safe_date(_first_present(row, "date", "日期"))
                if val_date is None or val_date < start_date or val_date > end_date:
                    continue
                value = _safe_float(_first_present(row, "value", "数值"))
                if value is None:
                    continue
                if field == "market_cap":
                    value *= 100_000_000
                rows_by_date.setdefault(val_date, {})[field] = value

        facts: list[ValuationFact] = []
        for val_date, values in sorted(rows_by_date.items()):
            facts.append(
                ValuationFact(
                    asset_code=canonical_asset_code,
                    val_date=val_date,
                    pe_ttm=values.get("pe_ttm"),
                    pe_static=values.get("pe_static"),
                    pb=values.get("pb"),
                    ps_ttm=None,
                    market_cap=values.get("market_cap"),
                    float_market_cap=None,
                    dv_ratio=None,
                    source=self.provider_source(),
                    extra=self._provider_extra(),
                )
            )
        return facts

    def fetch_sector_memberships(
        self,
        sector_code: str = "",
        sector_name: str = "",
        effective_date: date | None = None,
    ) -> list[SectorMembershipFact]:
        adapter = build_akshare_sector_adapter()
        resolved_name = sector_name
        resolved_code = sector_code
        if not resolved_name and resolved_code:
            sector_list = adapter.fetch_sector_list()
            matched = sector_list[sector_list["sector_code"] == resolved_code]
            if not matched.empty:
                resolved_name = str(matched.iloc[0]["sector_name"])
        if not resolved_name:
            return []

        as_of = effective_date or date.today()
        df = adapter.fetch_sector_constituents(resolved_name)
        if df is None or df.empty:
            return []
        return [
            SectorMembershipFact(
                asset_code=normalize_asset_code(str(row["stock_code"]), "akshare"),
                sector_code=resolved_code or resolved_name,
                sector_name=resolved_name,
                effective_date=as_of,
                source=self.provider_source(),
            )
            for row in df.to_dict("records")
            if row.get("stock_code")
        ]

    def fetch_news(self, asset_code: str, limit: int = 20) -> list[NewsFact]:
        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            AKShareEastMoneyGateway,
        )

        gateway = AKShareEastMoneyGateway()
        if not str(asset_code or "").strip():
            articles = gateway.get_market_news(limit=limit)
            return [
                NewsFact(
                    asset_code="",
                    title=article.title,
                    summary=article.content,
                    published_at=_ensure_aware(article.published_at),
                    url=article.url or "",
                    source=self.provider_source(),
                    external_id=article.news_id,
                    sentiment_score=_score_market_news_sentiment(
                        f"{article.title} {article.content}"
                    ),
                    extra=self._provider_extra({"market_scope": "broad_market"}),
                )
                for article in articles
            ]

        articles = gateway.get_stock_news(asset_code, limit=limit)
        return [
            NewsFact(
                asset_code=normalize_asset_code(article.stock_code, "akshare"),
                title=article.title,
                summary=article.content,
                published_at=_ensure_aware(article.published_at),
                url=article.url or "",
                source=self.provider_source(),
                external_id=article.news_id,
                sentiment_score=_score_market_news_sentiment(f"{article.title} {article.content}"),
                extra=self._provider_extra(),
            )
            for article in articles
        ]

    def fetch_capital_flows(
        self,
        asset_code: str,
        period: str = "5d",
    ) -> list[CapitalFlowFact]:
        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            AKShareEastMoneyGateway,
        )

        gateway = AKShareEastMoneyGateway()
        flows = gateway.get_capital_flows(asset_code, period=period)
        return [
            CapitalFlowFact(
                asset_code=normalize_asset_code(flow.stock_code, "akshare"),
                flow_date=flow.trade_date,
                main_net=flow.main_net_inflow,
                retail_net=None,
                super_large_net=flow.super_large_net_inflow,
                large_net=flow.large_net_inflow,
                medium_net=flow.medium_net_inflow,
                small_net=flow.small_net_inflow,
                source=self.provider_source(),
                extra=self._provider_extra({"main_net_ratio": flow.main_net_ratio}),
            )
            for flow in flows
        ]


class EastMoneyUnifiedProviderAdapter(AkshareUnifiedProviderAdapter):
    """EastMoney provider is implemented via the dedicated EastMoney gateway."""


class QmtUnifiedProviderAdapter(BaseUnifiedProviderAdapter):
    """Standardized QMT provider wrapper."""

    def _gateway(self):
        from apps.data_center.infrastructure.gateways.qmt_gateway import QMTGateway

        return QMTGateway(
            source_name=self.provider_name(),
            extra_config=self._config.extra_config,
        )

    def fetch_price_history(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[PriceBar]:
        canonical_asset_code = normalize_asset_code(asset_code, "qmt")
        bars = self._gateway().get_historical_prices(
            asset_code=canonical_asset_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        return [
            PriceBar(
                asset_code=canonical_asset_code,
                bar_date=bar.trade_date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=float(bar.volume) if bar.volume is not None else None,
                amount=bar.amount,
                source=self.provider_source(),
            )
            for bar in bars
        ]

    def fetch_quote_snapshots(self, asset_codes: list[str]) -> list[QuoteSnapshot]:
        quotes = self._gateway().get_quote_snapshots(asset_codes)
        return [
            QuoteSnapshot(
                asset_code=normalize_asset_code(quote.stock_code, "qmt"),
                snapshot_at=_ensure_aware(getattr(quote, "fetched_at", None)),
                current_price=float(quote.price),
                source=self.provider_source(),
                open=_safe_float(quote.open),
                high=_safe_float(quote.high),
                low=_safe_float(quote.low),
                prev_close=_safe_float(quote.pre_close),
                volume=float(quote.volume) if quote.volume is not None else None,
                amount=_safe_float(quote.amount),
                extra=self._provider_extra(),
            )
            for quote in quotes
        ]


class FredUnifiedProviderAdapter(BaseUnifiedProviderAdapter):
    """Minimal FRED macro adapter using the official HTTP API."""

    def fetch_macro_series(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        if indicator_code not in _FRED_SERIES_MAP:
            return []

        series_id, unit, _period_type = _FRED_SERIES_MAP[indicator_code]
        response = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "api_key": self._config.api_key,
                "file_type": "json",
                "observation_start": start_date.isoformat(),
                "observation_end": end_date.isoformat(),
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()

        facts: list[MacroFact] = []
        for row in payload.get("observations", []):
            value = row.get("value")
            if value in (None, ".", ""):
                continue
            facts.append(
                MacroFact(
                    indicator_code=indicator_code,
                    reporting_period=date.fromisoformat(row["date"]),
                    value=float(value),
                    unit=unit,
                    source=self.provider_source(),
                    published_at=date.fromisoformat(row["date"]),
                    quality=DataQualityStatus.VALID,
                    extra=self._provider_extra({"original_unit": unit}),
                )
            )
        return facts


def build_unified_provider_adapter(config: ProviderConfig) -> UnifiedDataProviderProtocol:
    """Create a standardized provider adapter from config."""

    mapping = {
        "tushare": TushareUnifiedProviderAdapter,
        "akshare": AkshareUnifiedProviderAdapter,
        "eastmoney": EastMoneyUnifiedProviderAdapter,
        "qmt": QmtUnifiedProviderAdapter,
        "fred": FredUnifiedProviderAdapter,
    }
    adapter_cls = mapping.get(config.source_type)
    if adapter_cls is None:
        raise ValueError(f"Unsupported provider source_type: {config.source_type}")
    return adapter_cls(config)


def time_adapter_call(fn, *args, **kwargs):
    """Run a provider call and return (result, latency_ms)."""

    started = perf_counter()
    result = fn(*args, **kwargs)
    return result, (perf_counter() - started) * 1000
