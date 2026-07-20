"""Unified provider adapters for Data Center Phase 3.

These adapters wrap existing module-specific gateways/adapters and expose
standardized data_center domain entities only.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from apps.data_center.domain.entities import (
    FinancialFact,
    FundNavFact,
    MacroFact,
    PriceBar,
    QuoteSnapshot,
    ValuationFact,
)
from apps.data_center.domain.enums import (
    DataQualityStatus,
    PriceAdjustment,
)
from apps.data_center.domain.rules import normalize_asset_code
from apps.data_center.infrastructure._provider_adapter_base import (
    BaseUnifiedProviderAdapter,
    _ensure_aware,
    _fetch_macro_points,
    _first_present,
    _safe_date,
    _to_period_type,
)
from apps.data_center.infrastructure.macro_sources import TushareAdapter
from core.integration.data_center_business_sources import (
    build_tushare_financial_gateway,
    build_tushare_fund_adapter,
    build_tushare_valuation_gateway,
)
from shared.numeric import safe_float

logger = logging.getLogger(__name__)


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

        adapter = TushareAdapter(
            token=self._config.api_key,
            http_url=self._config.http_url,
        )
        fetch_code = "SHIBOR" if indicator_code == "CN_SHIBOR" else indicator_code
        points = _fetch_macro_points(adapter, fetch_code, start_date, end_date)
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
        """Fetch full-market A-share turnover by summing stock daily amounts."""

        from shared.infrastructure.tushare_client import create_tushare_pro_client

        rows_by_date: dict[date, float] = {}
        try:
            pro = create_tushare_pro_client(
                token=self._config.api_key, http_url=self._config.http_url
            )
            calendar = pro.trade_cal(
                exchange="",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                is_open="1",
            )
            trading_dates = sorted(
                observed_at
                for observed_at in (
                    _safe_date(_first_present(row, "cal_date", "trade_date", "date"))
                    for row in (calendar.to_dict("records") if calendar is not None else [])
                )
                if observed_at is not None
            )
            for current_date in trading_dates:
                df = pro.daily(trade_date=current_date.strftime("%Y%m%d"))
                if df is None or df.empty:
                    continue
                for row in df.to_dict("records"):
                    observed_at = _safe_date(_first_present(row, "trade_date", "date"))
                    if observed_at is None:
                        continue
                    amount = safe_float(_first_present(row, "amount"))
                    if amount is None:
                        continue
                    rows_by_date[observed_at] = rows_by_date.get(observed_at, 0.0) + amount
        except Exception as exc:
            logger.warning("Tushare full-market turnover fetch failed closed: %s", exc)
            return []

        if not rows_by_date:
            return []

        return [
            MacroFact(
                indicator_code="CN_A_TOTAL_TURNOVER",
                reporting_period=observed_at,
                value=value,
                unit="千元",
                source=self.provider_source(),
                published_at=observed_at,
                quality=DataQualityStatus.VALID,
                extra=self._provider_extra(
                    {
                        "aggregation": "tushare_a_share_daily_amount_sum",
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
            value = safe_float(_first_present(row, "rzye"))
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
        requested_dates = [item for item in trade_dates if item >= start_date]
        if not requested_dates:
            return []
        earlier_dates = [item for item in trade_dates if item < requested_dates[0]]
        if not earlier_dates:
            return []
        flow_dates = [earlier_dates[-1], *requested_dates]
        totals_by_date = self._fetch_tushare_etf_total_sizes(pro, flow_dates)

        facts: list[MacroFact] = []
        for previous_date, current_date in zip(flow_dates, flow_dates[1:], strict=False):
            previous_size = totals_by_date.get(previous_date)
            current_size = totals_by_date.get(current_date)
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

    def _fetch_tushare_etf_total_sizes(
        self,
        pro: Any,
        trade_dates: list[date],
    ) -> dict[date, float]:
        """Fetch complete SSE+SZSE ETF sizes for a short date range in two calls."""

        if not trade_dates:
            return {}
        totals_by_exchange: dict[str, dict[date, float]] = {}
        for exchange in ("SSE", "SZSE"):
            df = pro.etf_share_size(
                start_date=min(trade_dates).strftime("%Y%m%d"),
                end_date=max(trade_dates).strftime("%Y%m%d"),
                exchange=exchange,
            )
            if df is None or df.empty:
                return {}
            exchange_totals: dict[date, float] = {}
            for row in df.to_dict("records"):
                observed_at = _safe_date(_first_present(row, "trade_date", "date"))
                value = safe_float(_first_present(row, "total_size"))
                if observed_at is None or observed_at not in trade_dates or value is None:
                    continue
                exchange_totals[observed_at] = exchange_totals.get(observed_at, 0.0) + value
            totals_by_exchange[exchange] = exchange_totals

        complete_totals: dict[date, float] = {}
        for trade_date in trade_dates:
            if not all(trade_date in totals_by_exchange[item] for item in ("SSE", "SZSE")):
                continue
            complete_totals[trade_date] = sum(
                totals_by_exchange[item][trade_date] for item in ("SSE", "SZSE")
            )
        return complete_totals

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
                open=safe_float(quote.open),
                high=safe_float(quote.high),
                low=safe_float(quote.low),
                prev_close=safe_float(quote.pre_close),
                volume=float(quote.volume) if quote.volume is not None else None,
                amount=safe_float(quote.amount),
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
                    acc_nav=safe_float(getattr(row, "accum_nav", None)),
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
