"""Unified provider adapters for Data Center Phase 3.

These adapters wrap existing module-specific gateways/adapters and expose
standardized data_center domain entities only.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
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
    QuoteSnapshot,
    SectorMembershipFact,
    ValuationFact,
)
from apps.data_center.domain.enums import (
    DataQualityStatus,
)
from apps.data_center.domain.rules import normalize_asset_code
from apps.data_center.infrastructure._provider_adapter_base import (
    BaseUnifiedProviderAdapter,
    _ensure_aware,
    _fetch_macro_points,
    _first_present,
    _period_type_from_period_end,
    _request_error_is_permission_denied,
    _safe_date,
    _score_market_news_sentiment,
    _valuation_period,
)
from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module
from apps.data_center.infrastructure.macro_sources import AKShareAdapter
from apps.data_center.infrastructure.sse_investor_accounts import fetch_investor_account_facts
from shared.numeric import safe_float

logger = logging.getLogger(__name__)


def _available_at_from_report_date(report_date: date | None) -> datetime | None:
    """Convert an AKShare notice/report date into an explicit availability instant."""

    if report_date is None:
        return None
    return datetime.combine(report_date, datetime.min.time(), tzinfo=UTC)


_A_SHARE_BEHAVIOR_CODES = frozenset(
    {
        "CN_A_ADVANCE_COUNT",
        "CN_A_DECLINE_COUNT",
        "CN_A_LIMIT_UP_COUNT",
        "CN_A_LIMIT_DOWN_COUNT",
    }
)


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
            return fetch_investor_account_facts(
                start_date=start_date,
                end_date=end_date,
                provider_source=self.provider_source(),
                provider_name=self.provider_name(),
            )
        if indicator_code in _A_SHARE_BEHAVIOR_CODES:
            return self._fetch_a_share_behavior(indicator_code, start_date, end_date)

        adapter = AKShareAdapter()
        points = _fetch_macro_points(adapter, indicator_code, start_date, end_date)
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

    def _fetch_a_share_behavior(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        """Fetch one observed A-share breadth or price-limit count without zero filling."""

        from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module

        if indicator_code in {"CN_A_ADVANCE_COUNT", "CN_A_DECLINE_COUNT"}:
            observed_at = date.today()
            if observed_at < start_date or observed_at > end_date:
                return []
            try:
                frame = get_akshare_module().stock_zh_a_spot_em()
            except Exception as exc:
                logger.warning("AKShare A-share breadth fetch failed closed: %s", exc)
                return []
            if frame is None or frame.empty:
                return []
            changes = [
                value
                for row in frame.to_dict("records")
                if "ST" not in str(_first_present(row, "名称", "name") or "").upper()
                and (value := safe_float(_first_present(row, "涨跌幅", "change_pct"))) is not None
            ]
            if not changes:
                return []
            if indicator_code == "CN_A_ADVANCE_COUNT":
                value = sum(1 for change in changes if change > 0)
                aggregation = "akshare_a_share_spot_non_st_positive_change_count"
            else:
                value = sum(1 for change in changes if change < 0)
                aggregation = "akshare_a_share_spot_non_st_negative_change_count"
        else:
            observed_at = end_date
            try:
                ak = get_akshare_module()
                if indicator_code == "CN_A_LIMIT_UP_COUNT":
                    frame = ak.stock_zt_pool_em(date=observed_at.strftime("%Y%m%d"))
                    aggregation = "akshare_limit_up_pool_non_st_row_count"
                else:
                    frame = ak.stock_zt_pool_dtgc_em(date=observed_at.strftime("%Y%m%d"))
                    aggregation = "akshare_limit_down_pool_non_st_row_count"
            except Exception as exc:
                logger.warning("AKShare A-share price-limit pool fetch failed closed: %s", exc)
                return []
            if frame is None or frame.empty:
                return []
            rows: list[dict[str, Any]] = []
            for row in frame.to_dict("records"):
                raw_name = _first_present(row, "名称", "name")
                name = "" if raw_name is None else str(raw_name).strip()
                if not name or name.lower() == "nan" or "ST" in name.upper():
                    continue
                rows.append(row)
            if not rows:
                return []
            value = len(rows)

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
                        "market_scope": "a_share_non_st",
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
        """Fetch official SH/SZ A-share turnover totals through AKShare."""
        from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module

        rows_by_date: dict[date, float] = {}
        try:
            ak = get_akshare_module()
            current_date = start_date
            while current_date <= end_date:
                date_text = current_date.strftime("%Y%m%d")
                sh_df = ak.stock_sse_deal_daily(date=date_text)
                sz_df = ak.stock_szse_summary(date=date_text)

                sh_amount = 0.0
                if sh_df is not None and not sh_df.empty:
                    amount_rows = sh_df[sh_df["单日情况"].astype(str) == "成交金额"]
                    if not amount_rows.empty:
                        amount_row = amount_rows.iloc[0]
                        sh_amount = (
                            sum(
                                value or 0.0
                                for value in (
                                    safe_float(amount_row.get("主板A")),
                                    safe_float(amount_row.get("科创板")),
                                )
                            )
                            * 100_000_000.0
                        )

                sz_amount = 0.0
                if sz_df is not None and not sz_df.empty:
                    for row in sz_df.to_dict("records"):
                        category = str(row.get("证券类别") or "")
                        if "A股" not in category and category != "中小板":
                            continue
                        amount = safe_float(row.get("成交金额"))
                        if amount is not None:
                            sz_amount += amount

                if sh_amount > 0.0 and sz_amount > 0.0:
                    rows_by_date[current_date] = sh_amount + sz_amount
                current_date += timedelta(days=1)
        except Exception as exc:
            logger.warning("AKShare official-market turnover fetch failed closed: %s", exc)
            return []

        if not rows_by_date:
            return []

        return [
            MacroFact(
                indicator_code="CN_A_TOTAL_TURNOVER",
                reporting_period=observed_at,
                value=value,
                unit="元",
                source=self.provider_source(),
                quality=DataQualityStatus.VALID,
                extra=self._provider_extra(
                    {
                        "aggregation": "sse_a_share_plus_szse_a_share_official_summary",
                        "original_unit": "元",
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
                value = safe_float(_first_present(row, "融资余额"))
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
            flow = safe_float(_first_present(row, "主力净流入-净额", "f62"))
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
                        if _request_error_is_permission_denied(exc):
                            raise
                if attempt < 3:
                    sleep(1.5 * attempt)
            if last_error is not None:
                raise last_error
            return []

        try:
            return _fetch_with_retries()
        except requests.RequestException as exc:
            if _request_error_is_permission_denied(exc):
                raise ConnectionError(str(exc)) from exc
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
                source=str(getattr(bar, "source", "") or self.provider_source()).strip(),
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
                snapshot_at=_ensure_aware(quote.observed_at),
                fetched_at=_ensure_aware(quote.fetched_at),
                current_price=float(quote.price),
                source=str(quote.source or self.provider_source()).strip(),
                open=safe_float(quote.open),
                high=safe_float(quote.high),
                low=safe_float(quote.low),
                prev_close=safe_float(quote.pre_close),
                volume=float(quote.volume) if quote.volume is not None else None,
                amount=safe_float(quote.amount),
                extra=self._provider_extra(
                    {
                        "actual_source": str(quote.source or self.provider_source()).strip(),
                        "observation_contract": "batch_quote_snapshot",
                    }
                ),
            )
            for quote in quotes
            if quote.observed_at is not None
        ]

    def fetch_fund_nav(
        self,
        fund_code: str,
        start_date: date,
        end_date: date,
    ) -> list[FundNavFact]:
        ak = get_akshare_module()
        normalized_code = fund_code.split(".")[0]
        fetcher = getattr(ak, "fund_open_fund_info_em", None)
        df = (
            fetcher(fund=normalized_code, indicator="单位净值走势") if fetcher is not None else None
        )
        if df is None or df.empty:
            return []

        facts: list[FundNavFact] = []
        for row in df.to_dict("records"):
            nav_date = _first_present(row, "nav_date", "净值日期", "日期")
            if nav_date is None:
                continue
            nav_date = nav_date.date() if hasattr(nav_date, "date") else nav_date
            if nav_date < start_date or nav_date > end_date:
                continue
            facts.append(
                FundNavFact(
                    fund_code=fund_code,
                    nav_date=nav_date,
                    nav=float(_first_present(row, "unit_nav", "单位净值", "净值")),
                    acc_nav=safe_float(_first_present(row, "accum_nav", "累计净值")),
                    source=self.provider_source(),
                    extra=self._provider_extra(),
                )
            )
        return facts

    def fetch_financials(self, asset_code: str, periods: int = 8) -> list[FinancialFact]:
        from apps.data_center.infrastructure.legacy_sdk_bridge import get_akshare_module

        if isinstance(periods, bool) or not isinstance(periods, int) or periods <= 0:
            raise ValueError("periods must be a positive integer")

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
            report_date = _safe_date(
                _first_present(
                    row,
                    "NOTICE_DATE",
                    "公告日期",
                    "公告日",
                )
            )

            revenue = safe_float(_first_present(row, "TOTALOPERATEREVE", "营业总收入"))
            net_profit = safe_float(_first_present(row, "PARENTNETPROFIT", "归母净利润"))
            roe = safe_float(_first_present(row, "ROEJQ", "ROE_DILUTED", "净资产收益率"))
            debt_ratio = safe_float(_first_present(row, "ZCFZL", "资产负债率"))
            total_liabilities = safe_float(_first_present(row, "LIABILITY", "负债合计"))
            total_assets = safe_float(_first_present(row, "TOTAL_ASSETS", "总资产"))
            derived_metrics: dict[str, str] = {}
            if (
                total_assets is None
                and total_liabilities is not None
                and debt_ratio is not None
                and debt_ratio != 0.0
            ):
                total_assets = total_liabilities / (debt_ratio / 100)
                derived_metrics["total_assets"] = "total_liabilities_divided_by_debt_ratio"
            if total_liabilities is None and total_assets is not None and debt_ratio is not None:
                total_liabilities = total_assets * debt_ratio / 100
                derived_metrics["total_liabilities"] = "total_assets_multiplied_by_debt_ratio"
            equity = safe_float(_first_present(row, "TOTAL_EQUITY", "股东权益合计"))
            if equity is None and total_assets is not None and total_liabilities is not None:
                equity = total_assets - total_liabilities
                derived_metrics["equity"] = "total_assets_minus_total_liabilities"

            metric_values: dict[str, tuple[float | None, str]] = {
                "revenue": (revenue, "元"),
                "net_profit": (net_profit, "元"),
                "revenue_growth": (
                    safe_float(_first_present(row, "TOTALOPERATEREVETZ", "营收同比")),
                    "%",
                ),
                "net_profit_growth": (
                    safe_float(_first_present(row, "PARENTNETPROFITTZ", "归母净利润同比")),
                    "%",
                ),
                "total_assets": (total_assets, "元"),
                "total_liabilities": (total_liabilities, "元"),
                "equity": (equity, "元"),
                "roe": (roe, "%"),
                "roa": (safe_float(_first_present(row, "JROA", "ZZCJLL", "总资产收益率")), "%"),
                "debt_ratio": (debt_ratio, "%"),
            }
            for metric_code, (value, unit) in metric_values.items():
                if value is None:
                    continue
                facts.append(
                    FinancialFact(
                        asset_code=canonical_asset_code,
                        period_end=period_end,
                        period_type=_period_type_from_period_end(period_end),
                        metric_code=metric_code,
                        value=value,
                        unit=unit,
                        source=self.provider_source(),
                        report_date=report_date,
                        available_at=_available_at_from_report_date(report_date),
                        extra=self._provider_extra(
                            {"derived_from": derived_metrics[metric_code]}
                            if metric_code in derived_metrics
                            else None
                        ),
                    )
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
                value = safe_float(_first_present(row, "value", "数值"))
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

    def fetch_current_valuations(
        self,
        asset_codes: list[str],
        as_of_date: date,
    ) -> list[ValuationFact]:
        """Fetch current valuation coverage through Tencent's batch quote contract."""

        from apps.data_center.infrastructure.gateways.tencent_gateway import TencentGateway

        gateway = TencentGateway()
        snapshots = []
        batch_size = 200
        for offset in range(0, len(asset_codes), batch_size):
            snapshots.extend(
                gateway.get_valuation_snapshots(asset_codes[offset : offset + batch_size])
            )
        return [
            ValuationFact(
                asset_code=snapshot.stock_code,
                val_date=snapshot.observed_at.date(),
                pe_ttm=snapshot.pe_ttm,
                pb=snapshot.pb,
                market_cap=snapshot.market_cap,
                float_market_cap=snapshot.float_market_cap,
                source=snapshot.source,
                extra=self._provider_extra(
                    {
                        "actual_source": snapshot.source,
                        "observation_contract": "tencent_quote_batch",
                    }
                ),
            )
            for snapshot in snapshots
            if snapshot.observed_at.date() <= as_of_date
        ]

    def fetch_sector_memberships(
        self,
        sector_code: str = "",
        sector_name: str = "",
        effective_date: date | None = None,
    ) -> list[SectorMembershipFact]:
        # AKShare does not expose a stable historical constituent contract for
        # this capability.  Returning an empty result keeps the provider
        # fail-closed instead of importing the sector app's local ORM adapter.
        del sector_code, sector_name, effective_date
        return []

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
