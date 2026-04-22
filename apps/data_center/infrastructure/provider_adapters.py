"""Unified provider adapters for Data Center Phase 3.

These adapters wrap existing module-specific gateways/adapters and expose
standardized data_center domain entities only.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from time import perf_counter
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
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
        return None if number != number else number
    except (TypeError, ValueError):
        return None


class BaseUnifiedProviderAdapter(UnifiedDataProviderProtocol):
    """Base class for standardized data-center providers."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self._caps = _SOURCE_CAPABILITIES.get(config.source_type, set())

    def provider_name(self) -> str:
        return self._config.name

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
        from apps.macro.infrastructure.adapters.tushare_adapter import TushareAdapter

        adapter = TushareAdapter(token=self._config.api_key, http_url=self._config.http_url)
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
                    source=self.provider_name(),
                    published_at=getattr(point, "published_at", None),
                    quality=DataQualityStatus.VALID,
                )
            )
        return results

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
                source=self.provider_name(),
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
                source=self.provider_name(),
                open=_safe_float(quote.open),
                high=_safe_float(quote.high),
                low=_safe_float(quote.low),
                prev_close=_safe_float(quote.pre_close),
                volume=float(quote.volume) if quote.volume is not None else None,
                amount=_safe_float(quote.amount),
            )
            for quote in quotes
        ]

    def fetch_fund_nav(
        self,
        fund_code: str,
        start_date: date,
        end_date: date,
    ) -> list[FundNavFact]:
        from apps.fund.infrastructure.adapters.tushare_fund_adapter import TushareFundAdapter

        adapter = TushareFundAdapter(token=self._config.api_key, http_url=self._config.http_url)
        df = adapter.fetch_fund_daily(
            fund_code=fund_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return []

        facts: list[FundNavFact] = []
        for row in df.itertuples(index=False):
            nav_date = getattr(row, "trade_date").date()
            facts.append(
                FundNavFact(
                    fund_code=fund_code,
                    nav_date=nav_date,
                    nav=float(getattr(row, "unit_nav")),
                    acc_nav=_safe_float(getattr(row, "accum_nav", None)),
                    source=self.provider_name(),
                )
            )
        return facts

    def fetch_financials(self, asset_code: str, periods: int = 8) -> list[FinancialFact]:
        from apps.equity.infrastructure.financial_source_gateway import TushareFinancialGateway

        gateway = TushareFinancialGateway(
            token=self._config.api_key,
            http_url=self._config.http_url,
        )
        batch = gateway.fetch(asset_code, periods=periods)
        facts: list[FinancialFact] = []
        for record in batch.records:
            common = dict(
                asset_code=record.stock_code,
                period_end=record.report_date,
                period_type=_to_period_type(record.report_type),
                source=self.provider_name(),
            )
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
        from apps.equity.infrastructure.valuation_source_gateways import TushareValuationGateway

        gateway = TushareValuationGateway(
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
                source=self.provider_name(),
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
        from apps.macro.infrastructure.adapters import AKShareAdapter

        adapter = AKShareAdapter()
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
                    source=self.provider_name(),
                    published_at=getattr(point, "published_at", None),
                    quality=DataQualityStatus.VALID,
                )
            )
        return results

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
                source=self.provider_name(),
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
                source=self.provider_name(),
                open=_safe_float(quote.open),
                high=_safe_float(quote.high),
                low=_safe_float(quote.low),
                prev_close=_safe_float(quote.pre_close),
                volume=float(quote.volume) if quote.volume is not None else None,
                amount=_safe_float(quote.amount),
            )
            for quote in quotes
        ]

    def fetch_fund_nav(
        self,
        fund_code: str,
        start_date: date,
        end_date: date,
    ) -> list[FundNavFact]:
        from apps.fund.infrastructure.adapters.akshare_fund_adapter import AkShareFundAdapter

        adapter = AkShareFundAdapter()
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
                    source=self.provider_name(),
                )
            )
        return facts

    def fetch_financials(self, asset_code: str, periods: int = 8) -> list[FinancialFact]:
        from apps.equity.infrastructure.financial_source_gateway import AKShareFinancialGateway

        gateway = AKShareFinancialGateway()
        batch = gateway.fetch(asset_code, periods=periods)
        facts: list[FinancialFact] = []
        for record in batch.records:
            common = dict(
                asset_code=record.stock_code,
                period_end=record.report_date,
                period_type=_to_period_type(record.report_type),
                source=self.provider_name(),
            )
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
        return facts

    def fetch_valuations(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationFact]:
        from apps.equity.infrastructure.valuation_source_gateways import AKShareValuationGateway

        gateway = AKShareValuationGateway()
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
                source=self.provider_name(),
            )
            for record in batch.records
        ]

    def fetch_sector_memberships(
        self,
        sector_code: str = "",
        sector_name: str = "",
        effective_date: date | None = None,
    ) -> list[SectorMembershipFact]:
        from apps.sector.infrastructure.adapters.akshare_sector_adapter import AKShareSectorAdapter

        adapter = AKShareSectorAdapter()
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
                source=self.provider_name(),
            )
            for row in df.to_dict("records")
            if row.get("stock_code")
        ]

    def fetch_news(self, asset_code: str, limit: int = 20) -> list[NewsFact]:
        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            AKShareEastMoneyGateway,
        )

        gateway = AKShareEastMoneyGateway()
        articles = gateway.get_stock_news(asset_code, limit=limit)
        return [
            NewsFact(
                asset_code=normalize_asset_code(article.stock_code, "akshare"),
                title=article.title,
                summary=article.content,
                published_at=_ensure_aware(article.published_at),
                url=article.url or "",
                source=self.provider_name(),
                external_id=article.news_id,
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
                source=self.provider_name(),
                extra={"main_net_ratio": flow.main_net_ratio},
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
                source=self.provider_name(),
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
                source=self.provider_name(),
                open=_safe_float(quote.open),
                high=_safe_float(quote.high),
                low=_safe_float(quote.low),
                prev_close=_safe_float(quote.pre_close),
                volume=float(quote.volume) if quote.volume is not None else None,
                amount=_safe_float(quote.amount),
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
                    source=self.provider_name(),
                    published_at=date.fromisoformat(row["date"]),
                    quality=DataQualityStatus.VALID,
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
