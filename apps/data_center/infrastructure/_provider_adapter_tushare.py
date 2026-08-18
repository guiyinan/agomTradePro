"""Unified provider adapters for Data Center Phase 3.

These adapters wrap existing module-specific gateways/adapters and expose
standardized data_center domain entities only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, cast

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
from apps.data_center.infrastructure.tushare_client import create_tushare_pro_client
from shared.numeric import safe_float

logger = logging.getLogger(__name__)

_A_SHARE_BEHAVIOR_CODES = frozenset(
    {
        "CN_A_ADVANCE_COUNT",
        "CN_A_DECLINE_COUNT",
        "CN_A_LIMIT_UP_COUNT",
        "CN_A_LIMIT_DOWN_COUNT",
    }
)


# Test and migration seams.  Production uses the native Data Center gateways
# below; callers may inject a legacy-shaped fake while transitioning fixtures.
def build_tushare_fund_adapter(*, token: str, http_url: str | None = None) -> Any | None:
    """Return no compatibility adapter by default; retained as an injection seam."""

    del token, http_url
    return None


def build_tushare_financial_gateway(*, token: str, http_url: str | None = None) -> Any | None:
    """Return no compatibility gateway by default; retained for migration fakes."""

    del token, http_url
    return None


def build_tushare_valuation_gateway(*, token: str, http_url: str | None = None) -> Any | None:
    """Return no compatibility gateway by default; retained for migration fakes."""

    del token, http_url
    return None


class _ProviderFrame(Protocol):
    """Minimal pandas-like frame returned by the Tushare SDK."""

    empty: bool

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        """Return provider rows as dictionaries."""


class _TushareProClient(Protocol):
    """Tushare endpoints required by canonical macro fact collection."""

    def trade_cal(
        self,
        *,
        exchange: str,
        start_date: str,
        end_date: str,
        is_open: str | None = None,
    ) -> _ProviderFrame | None:
        """Return the exchange trading calendar."""

    def daily(self, *, trade_date: str) -> _ProviderFrame | None:
        """Return all-stock daily bars for one trade date."""

    def limit_list_d(
        self,
        *,
        trade_date: str,
        limit_type: str,
    ) -> _ProviderFrame | None:
        """Return daily price-limit pool rows."""

    def margin(self, *, start_date: str, end_date: str) -> _ProviderFrame | None:
        """Return margin balance rows."""

    def etf_share_size(
        self,
        *,
        start_date: str,
        end_date: str,
        exchange: str,
    ) -> _ProviderFrame | None:
        """Return ETF share-size rows."""

    def fund_nav(
        self,
        *,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> _ProviderFrame | None:
        """Return fund NAV rows."""

    def fina_indicator(
        self,
        *,
        ts_code: str,
        limit: int,
    ) -> _ProviderFrame | None:
        """Return financial indicator rows."""

    def daily_basic(
        self,
        *,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> _ProviderFrame | None:
        """Return daily valuation rows."""


def _optional_nonnegative_float(value: object) -> float | None:
    """Return one finite nonnegative provider value when valid."""

    parsed = safe_float(value)
    if parsed is None or parsed < 0:
        return None
    return parsed


def _available_at_from_report_date(report_date: date | None) -> datetime | None:
    """Convert the provider's announcement date into an explicit availability instant."""

    if report_date is None:
        return None
    return datetime.combine(report_date, datetime.min.time(), tzinfo=UTC)


def _financial_fact_builder(
    *,
    asset_code: str,
    period_end: date,
    report_date: date | None = None,
    report_type: str,
    source: str,
    extra: dict[str, Any],
) -> Callable[[str, float, str], FinancialFact]:
    """Bind one financial period's shared fields to a typed fact constructor."""

    period_type = _to_period_type(report_type)

    def build(metric_code: str, value: float, unit: str) -> FinancialFact:
        return FinancialFact(
            asset_code=asset_code,
            period_end=period_end,
            period_type=period_type,
            metric_code=metric_code,
            value=value,
            unit=unit,
            source=source,
            report_date=report_date,
            available_at=_available_at_from_report_date(report_date),
            extra=extra,
        )

    return build


class TushareUnifiedProviderAdapter(BaseUnifiedProviderAdapter):
    """Standardized Tushare provider wrapper."""

    def _configured_request_mode(self) -> str | None:
        """Return this provider row's explicit Tushare transport mode."""

        raw_mode = (self._config.extra_config or {}).get("tushare_request_mode")
        return raw_mode.strip() if isinstance(raw_mode, str) and raw_mode.strip() else None

    def _create_pro_client(self) -> _TushareProClient:
        """Build a client without leaking another provider row's transport config."""

        return cast(
            _TushareProClient,
            create_tushare_pro_client(
                token=self._config.api_key,
                http_url=self._config.http_url,
                request_mode=self._configured_request_mode(),
            ),
        )

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
        if indicator_code in _A_SHARE_BEHAVIOR_CODES:
            return self._fetch_a_share_behavior(indicator_code, start_date, end_date)

        adapter = TushareAdapter(
            token=self._config.api_key,
            http_url=self._config.http_url,
            request_mode=self._configured_request_mode(),
        )
        fetch_code = "SHIBOR" if indicator_code == "CN_SHIBOR" else indicator_code
        points = _fetch_macro_points(adapter, fetch_code, start_date, end_date)
        results: list[MacroFact] = []
        for point in points:
            observed_at = getattr(point, "observed_at", None)
            value = safe_float(getattr(point, "value", None))
            if observed_at is None or value is None:
                continue
            results.append(
                MacroFact(
                    indicator_code=indicator_code,
                    reporting_period=observed_at,
                    value=value,
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

    def _fetch_a_share_behavior(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        """Fetch one daily A-share breadth or price-limit count from Tushare."""

        observed_at = end_date
        if observed_at < start_date:
            return []
        try:
            pro = self._create_pro_client()
            trade_date = observed_at.strftime("%Y%m%d")
            if indicator_code in {"CN_A_ADVANCE_COUNT", "CN_A_DECLINE_COUNT"}:
                frame = pro.daily(trade_date=trade_date)
                if frame is None or frame.empty:
                    return []
                changes = [
                    change
                    for row in frame.to_dict("records")
                    if (change := safe_float(_first_present(row, "pct_chg", "change_pct")))
                    is not None
                ]
                if not changes:
                    return []
                if indicator_code == "CN_A_ADVANCE_COUNT":
                    value = sum(1 for change in changes if change > 0)
                    aggregation = "tushare_daily_positive_change_count"
                else:
                    value = sum(1 for change in changes if change < 0)
                    aggregation = "tushare_daily_negative_change_count"
            else:
                limit_type = "U" if indicator_code == "CN_A_LIMIT_UP_COUNT" else "D"
                frame = pro.limit_list_d(trade_date=trade_date, limit_type=limit_type)
                if frame is None or frame.empty:
                    return []
                rows = [
                    row
                    for row in frame.to_dict("records")
                    if (name := str(_first_present(row, "name", "名称", "ts_name") or "").strip())
                    and "ST" not in name.upper()
                ]
                if not rows:
                    return []
                value = len(rows)
                aggregation = f"tushare_limit_list_d_{limit_type.lower()}_row_count"
        except Exception as exc:
            logger.warning(
                "Tushare A-share behavior fetch failed closed",
                extra={"exception_type": type(exc).__name__, "indicator_code": indicator_code},
            )
            return []

        return [
            MacroFact(
                indicator_code=indicator_code,
                reporting_period=observed_at,
                value=float(value),
                unit="家",
                source=self.provider_source(),
                published_at=observed_at,
                quality=DataQualityStatus.VALID,
                extra=self._provider_extra(
                    {
                        "aggregation": aggregation,
                        "market_scope": "a_share_provider_universe",
                        "original_unit": "家",
                    }
                ),
            )
        ]

    def _fetch_market_turnover(
        self,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        """Fetch full-market A-share turnover by summing stock daily amounts."""

        rows_by_date: dict[date, float] = {}
        try:
            pro = self._create_pro_client()
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
            logger.warning(
                "Tushare full-market turnover fetch failed closed",
                extra={"exception_type": type(exc).__name__},
            )
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

        pro = self._create_pro_client()
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

        pro = self._create_pro_client()
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
                    value=current_size - previous_size,
                    unit="万元",
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

    def _fetch_tushare_open_dates(
        self,
        pro: _TushareProClient,
        start_date: date,
        end_date: date,
    ) -> list[date]:
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
        pro: _TushareProClient,
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

        gateway = TushareGateway(
            token=self._config.api_key,
            http_url=self._config.http_url,
            request_mode=self._configured_request_mode(),
            source_name=self.provider_name(),
        )
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
                source=str(getattr(bar, "source", "") or self.provider_source()).strip(),
                adjustment=PriceAdjustment.NONE,
            )
            for bar in bars
        ]

    def fetch_quote_snapshots(self, asset_codes: list[str]) -> list[QuoteSnapshot]:
        from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway

        gateway = TushareGateway(
            token=self._config.api_key,
            http_url=self._config.http_url,
            request_mode=self._configured_request_mode(),
            source_name=self.provider_name(),
        )
        quotes = gateway.get_quote_snapshots(asset_codes)
        results: list[QuoteSnapshot] = []
        for quote in quotes:
            current_price = safe_float(quote.price)
            observed_at = getattr(quote, "observed_at", None)
            fetched_at = getattr(quote, "fetched_at", None)
            if (
                current_price is None
                or current_price <= 0
                or observed_at is None
                or fetched_at is None
            ):
                continue
            results.append(
                QuoteSnapshot(
                    asset_code=normalize_asset_code(quote.stock_code, "tushare"),
                    snapshot_at=_ensure_aware(observed_at),
                    fetched_at=_ensure_aware(fetched_at),
                    current_price=current_price,
                    source=self.provider_source(),
                    open=safe_float(quote.open),
                    high=safe_float(quote.high),
                    low=safe_float(quote.low),
                    prev_close=safe_float(quote.pre_close),
                    volume=_optional_nonnegative_float(quote.volume),
                    amount=_optional_nonnegative_float(quote.amount),
                    extra=self._provider_extra(),
                )
            )
        return results

    def fetch_fund_nav(
        self,
        fund_code: str,
        start_date: date,
        end_date: date,
    ) -> list[FundNavFact]:
        compatibility_adapter = build_tushare_fund_adapter(
            token=self._config.api_key,
            http_url=self._config.http_url,
        )
        if compatibility_adapter is not None:
            df = compatibility_adapter.fetch_fund_daily(
                fund_code=fund_code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
            if df is None or df.empty:
                return []
            facts: list[FundNavFact] = []
            for row in df.to_dict("records"):
                nav_date = _safe_date(_first_present(row, "trade_date", "nav_date"))
                nav = safe_float(_first_present(row, "unit_nav", "nav"))
                if nav_date is None or nav is None or nav <= 0:
                    continue
                facts.append(
                    FundNavFact(
                        fund_code=fund_code,
                        nav_date=nav_date,
                        nav=nav,
                        acc_nav=safe_float(_first_present(row, "accum_nav", "acc_nav")),
                        source=self.provider_source(),
                        extra=self._provider_extra(),
                    )
                )
            return facts
        pro = self._create_pro_client()
        df = pro.fund_nav(
            ts_code=fund_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return []

        native_facts: list[FundNavFact] = []
        for row in df.to_dict("records"):
            nav_date = _safe_date(_first_present(row, "nav_date", "end_date", "trade_date"))
            nav = safe_float(_first_present(row, "unit_nav", "nav"))
            acc_nav = safe_float(_first_present(row, "accum_nav", "acc_nav"))
            if nav_date is None:
                continue
            if nav is None or nav <= 0:
                continue
            if acc_nav is not None and acc_nav <= 0:
                acc_nav = None
            native_facts.append(
                FundNavFact(
                    fund_code=fund_code,
                    nav_date=nav_date,
                    nav=nav,
                    acc_nav=acc_nav,
                    source=self.provider_source(),
                    extra=self._provider_extra(),
                )
            )
        return native_facts

    def fetch_financials(self, asset_code: str, periods: int = 8) -> list[FinancialFact]:
        compatibility_gateway = build_tushare_financial_gateway(
            token=self._config.api_key,
            http_url=self._config.http_url,
        )
        if compatibility_gateway is not None:
            batch = compatibility_gateway.fetch(asset_code, periods=periods)
            compatibility_facts: list[FinancialFact] = []
            for record in batch.records:
                build_fact = _financial_fact_builder(
                    asset_code=record.stock_code,
                    period_end=record.report_date,
                    report_type=record.report_type,
                    source=self.provider_source(),
                    extra=self._provider_extra(),
                )
                for metric_code, raw_value, unit in (
                    ("revenue", record.revenue, "元"),
                    ("net_profit", record.net_profit, "元"),
                    ("total_assets", record.total_assets, "元"),
                    ("total_liabilities", record.total_liabilities, "元"),
                    ("equity", record.equity, "元"),
                    ("roe", record.roe, "%"),
                    ("debt_ratio", record.debt_ratio, "%"),
                    ("roa", record.roa, "%"),
                    ("revenue_growth", record.revenue_growth, "%"),
                    ("net_profit_growth", record.net_profit_growth, "%"),
                ):
                    value = safe_float(raw_value)
                    if value is not None:
                        compatibility_facts.append(build_fact(metric_code, value, unit))
            return compatibility_facts
        pro = self._create_pro_client()
        frame = pro.fina_indicator(
            ts_code=normalize_asset_code(asset_code, "tushare"),
            limit=max(periods, 1),
        )
        if frame is None or frame.empty:
            return []
        native_facts: list[FinancialFact] = []
        for row in frame.to_dict("records"):
            period_end = _safe_date(_first_present(row, "period_end", "end_date"))
            if period_end is None:
                continue
            report_date = _safe_date(_first_present(row, "ann_date", "announced_date"))
            report_type = (
                "1Q"
                if period_end.month == 3
                else "2Q" if period_end.month == 6 else "3Q" if period_end.month == 9 else "4Q"
            )
            build_fact = _financial_fact_builder(
                asset_code=normalize_asset_code(asset_code, "tushare"),
                period_end=period_end,
                report_date=report_date,
                report_type=report_type,
                source=self.provider_source(),
                extra=self._provider_extra(),
            )

            for metric_code, raw_value, unit in (
                ("revenue", _first_present(row, "revenue", "oper_cost"), "元"),
                ("net_profit", _first_present(row, "n_income", "net_profit"), "元"),
                ("total_assets", _first_present(row, "total_assets"), "元"),
                ("total_liabilities", _first_present(row, "total_liab"), "元"),
                ("equity", _first_present(row, "total_hldr_eqy_exc_min_int"), "元"),
                ("roe", _first_present(row, "roe", "roe_dt"), "%"),
                ("debt_ratio", _first_present(row, "debt_to_assets"), "%"),
                ("roa", _first_present(row, "roa"), "%"),
                ("revenue_growth", _first_present(row, "tr_yoy"), "%"),
                ("net_profit_growth", _first_present(row, "netprofit_yoy"), "%"),
            ):
                value = safe_float(raw_value)
                if value is not None:
                    native_facts.append(build_fact(metric_code, value, unit))
        return native_facts

    def fetch_valuations(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationFact]:
        compatibility_gateway = build_tushare_valuation_gateway(
            token=self._config.api_key,
            http_url=self._config.http_url,
        )
        if compatibility_gateway is not None:
            batch = compatibility_gateway.fetch(asset_code, start_date, end_date)
            return [
                ValuationFact(
                    asset_code=record.stock_code,
                    val_date=record.trade_date,
                    pe_ttm=safe_float(record.pe),
                    pb=safe_float(record.pb),
                    ps_ttm=safe_float(record.ps),
                    market_cap=_optional_nonnegative_float(record.total_mv),
                    float_market_cap=_optional_nonnegative_float(record.circ_mv),
                    dv_ratio=safe_float(record.dividend_yield),
                    source=self.provider_source(),
                    extra=self._provider_extra(),
                )
                for record in batch.records
            ]
        pro = self._create_pro_client()
        frame = pro.daily_basic(
            ts_code=normalize_asset_code(asset_code, "tushare"),
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if frame is None or frame.empty:
            return []
        facts: list[ValuationFact] = []
        for row in frame.to_dict("records"):
            val_date = _safe_date(_first_present(row, "trade_date", "val_date"))
            if val_date is None:
                continue
            facts.append(
                ValuationFact(
                    asset_code=normalize_asset_code(asset_code, "tushare"),
                    val_date=val_date,
                    pe_ttm=safe_float(_first_present(row, "pe_ttm", "pe")),
                    pb=safe_float(_first_present(row, "pb")),
                    ps_ttm=safe_float(_first_present(row, "ps_ttm", "ps")),
                    market_cap=_optional_nonnegative_float(_first_present(row, "total_mv")),
                    float_market_cap=_optional_nonnegative_float(_first_present(row, "circ_mv")),
                    dv_ratio=safe_float(_first_present(row, "dv_ttm", "dv_ratio")),
                    source=self.provider_source(),
                    extra=self._provider_extra(),
                )
            )
        return facts
