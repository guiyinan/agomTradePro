"""Fundamental data (financials/valuation) slice of the equity stock repository.

This module owns the `StockFundamentalsRepositoryMixin` slice of
`DjangoStockRepository`, including Data Center fact-table mappings. Shared
helpers and dependency wiring live in `stock_repository.py`; do not import the
compatibility facade here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from apps.data_center.application.public import (
    get_published_financial_facts,
    get_published_price_bar_series,
    get_published_valuation_facts,
)
from apps.data_center.domain.entities import AssetMaster, FinancialFact, PriceBar, ValuationFact
from apps.data_center.domain.enums import (
    AssetType,
    FinancialPeriodType,
    MarketExchange,
    PriceAdjustment,
)
from apps.data_center.domain.protocols import (
    AssetRepositoryProtocol,
    FinancialFactRepositoryProtocol,
    PriceBarRepositoryProtocol,
    ValuationFactRepositoryProtocol,
)
from apps.equity.domain.entities import (
    FinancialData,
    StockInfo,
    ValuationMetrics,
)
from shared.numeric import safe_float

logger = logging.getLogger(__name__)


def _parse_fact_date(value: object) -> date | None:
    """Parse a canonical fact date without substituting the request date."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _parse_fact_datetime(value: object) -> datetime | None:
    """Parse an aware canonical observation/fetch timestamp."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _canonical_fact_source(raw_source: str) -> tuple[str, dict[str, object]]:
    """Normalize compatibility DTO lineage without publishing a fake legacy owner."""

    normalized = str(raw_source or "").strip()
    if normalized and normalized.lower() != "unknown" and "legacy" not in normalized.lower():
        return normalized, {}
    extra: dict[str, object] = {}
    if normalized:
        extra["upstream_source"] = normalized
    return "equity_application_port", extra


if TYPE_CHECKING:
    from apps.data_center.application.on_demand import OnDemandDataCenterService


class StockFundamentalsRepositoryMixin:
    """Financial, valuation, and aggregated fundamental context persistence."""

    _dc_asset_repo: AssetRepositoryProtocol
    _dc_financial_repo: FinancialFactRepositoryProtocol
    _dc_price_bar_repo: PriceBarRepositoryProtocol
    _dc_valuation_repo: ValuationFactRepositoryProtocol
    _dc_on_demand: OnDemandDataCenterService

    if TYPE_CHECKING:

        def _build_stock_code_candidates(self, stock_code: str) -> list[str]: ...

        def _infer_exchange_from_market(self, market: str) -> str: ...

        def _infer_market_from_stock_code(self, stock_code: str) -> str: ...

        def _resolve_stock_name_from_data_center(self, stock_code: str) -> str: ...

    def get_all_stocks_with_fundamentals(
        self, as_of_date: date | None = None
    ) -> list[tuple[StockInfo, FinancialData, ValuationMetrics]]:
        """
        获取所有股票的基本面数据（最新财务数据 + 最新估值数据）

        Args:
            as_of_date: 截止日期（可选），如果不指定则使用最新数据

        Returns:
            [(StockInfo, FinancialData, ValuationMetrics), ...]
        """
        result = []

        # AssetMaster is the sole source of security identity and metadata.
        stock_assets = [
            asset
            for asset in self._dc_asset_repo.list_active()
            if asset.asset_type is AssetType.STOCK
        ]

        for asset in stock_assets:
            stock_code = asset.code
            stock_info = self._stock_info_from_asset(asset)

            # 获取最新财务数据
            financial = self._get_latest_financial(
                stock_code,
                published_only=as_of_date is None,
            )
            if not financial:
                # 没有财务数据，跳过
                continue

            # 获取最新估值数据
            valuation = self._get_latest_valuation(
                stock_code,
                published_only=as_of_date is None,
            )
            if not valuation:
                # 没有估值数据，跳过
                continue

            result.append((stock_info, financial, valuation))

        return result

    def get_stock_context_rows(
        self,
        stock_codes: list[str],
        *,
        published_only: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """Return stock context, with an explicit gate for current consumers.

        The default remains a historical/maintenance compatibility read.  All
        decision-facing callers use the application ``get_published_stock_context_map``
        or pass ``published_only=True`` so raw latest facts cannot masquerade as
        current observations.
        """

        normalized_codes = [str(code).upper() for code in stock_codes if code]
        if not normalized_codes:
            return {}

        requested_codes = list(dict.fromkeys(normalized_codes))
        candidate_codes = {
            candidate
            for code in requested_codes
            for candidate in self._build_stock_code_candidates(code)
        }
        info_map: dict[str, dict[str, str]] = {}
        for candidate in sorted(candidate_codes):
            asset = self._dc_asset_repo.get_by_code(candidate)
            if asset is None or not asset.is_active or asset.asset_type is not AssetType.STOCK:
                continue
            market_map = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}
            info_map[asset.code.upper()] = {
                "name": str(asset.short_name or asset.name or ""),
                "sector": str(asset.sector or asset.industry or ""),
                "market": market_map.get(asset.exchange.value, ""),
            }

        daily_map: dict[str, Mapping[str, object]] = {}
        for candidate in sorted(candidate_codes):
            latest_bar = self._get_latest_price_bar(
                candidate,
                published_only=published_only,
            )
            if latest_bar is None:
                continue
            daily_map[candidate.upper()] = {
                "trade_date": latest_bar.bar_date,
                "close": latest_bar.close,
                "volume": latest_bar.volume,
            }

        context: dict[str, dict[str, Any]] = {}
        for requested_code in requested_codes:
            context_row = {"name": "", "sector": "", "market": ""}
            latest_daily: Mapping[str, object] = {}
            for candidate in self._build_stock_code_candidates(requested_code):
                candidate_info = info_map.get(candidate.upper())
                if candidate_info and not any(context_row.values()):
                    context_row = {
                        "name": str(candidate_info.get("name") or ""),
                        "sector": str(candidate_info.get("sector") or ""),
                        "market": str(candidate_info.get("market") or ""),
                    }
                if not latest_daily and candidate.upper() in daily_map:
                    latest_daily = daily_map[candidate.upper()]
            if not context_row["name"]:
                data_center_name = self._resolve_stock_name_from_data_center(requested_code)
                if data_center_name:
                    context_row["name"] = data_center_name

            # Dashboard / equity-screen fundamental metrics must come from the
            # canonical data-center fact tables instead of legacy equity mirrors.
            latest_financial = self._get_stock_context_financial_fact_row(
                requested_code,
                published_only=published_only,
            )
            latest_valuation = self._get_stock_context_valuation_fact_row(
                requested_code,
                published_only=published_only,
            )
            context[requested_code] = {
                **context_row,
                "trade_date": latest_daily.get("trade_date"),
                "close": safe_float(latest_daily.get("close"), default=None),
                "volume": safe_float(latest_daily.get("volume"), default=None),
                "report_date": latest_financial.get("report_date"),
                "roe": latest_financial.get("roe"),
                "debt_ratio": latest_financial.get("debt_ratio"),
                "revenue_growth": latest_financial.get("revenue_growth"),
                "profit_growth": latest_financial.get("net_profit_growth"),
                "valuation_trade_date": latest_valuation.get("trade_date"),
                "pe": latest_valuation.get("pe"),
                "pb": latest_valuation.get("pb"),
                "ps": latest_valuation.get("ps"),
                "dividend_yield": latest_valuation.get("dividend_yield"),
            }
        return context

    def _get_stock_context_financial_fact_row(
        self,
        stock_code: str,
        *,
        published_only: bool = False,
    ) -> dict[str, Any]:
        latest = self._get_latest_financial(stock_code, published_only=published_only)
        if latest is None:
            return {}
        return {
            "report_date": latest.report_date,
            "roe": latest.roe,
            "debt_ratio": latest.debt_ratio,
            "revenue_growth": latest.revenue_growth,
            "net_profit_growth": latest.net_profit_growth,
        }

    def _get_stock_context_valuation_fact_row(
        self,
        stock_code: str,
        *,
        published_only: bool = False,
    ) -> dict[str, Any]:
        latest = self._get_latest_valuation(stock_code, published_only=published_only)
        if latest is None:
            return {}
        return {
            "trade_date": latest.trade_date,
            "pe": latest.pe,
            "pb": latest.pb,
            "ps": latest.ps,
            "dividend_yield": latest.dividend_yield,
        }

    def get_financial_data(
        self,
        stock_code: str,
        limit: int = 4,
        *,
        hydrate: bool = False,
    ) -> list[FinancialData]:
        """
        获取股票的财务数据

        Args:
            stock_code: 股票代码
            limit: 限制返回数量（默认 4，即最近 4 个季度）

        Returns:
            FinancialData 列表，按日期降序排列
        """
        if hydrate:
            self._dc_on_demand.ensure_financials(stock_code, periods=max(limit, 1))
        dc_financials = self._get_financials_from_data_center(stock_code, limit=limit)
        return dc_financials

    def get_valuation_history(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        *,
        hydrate: bool = False,
        published_only: bool = False,
        publication_key: str = "current",
    ) -> list[ValuationMetrics]:
        """
        获取股票的估值历史数据

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            ValuationMetrics 列表，按日期升序排列
        """
        if published_only:
            return self._get_published_valuations_from_data_center(
                stock_code,
                start_date=start_date,
                end_date=end_date,
                publication_key=publication_key,
            )
        if hydrate:
            self._dc_on_demand.ensure_valuations(stock_code, start_date, end_date)
        dc_valuations = self._get_valuations_from_data_center(stock_code, start_date, end_date)
        return dc_valuations

    def save_stock_info(self, stock_info: StockInfo) -> None:
        """
        保存股票基本信息

        Args:
            stock_info: StockInfo 实体
        """
        market = str(stock_info.market or "").strip().upper()
        if market not in {"SH", "SZ", "BJ"}:
            market = self._infer_market_from_stock_code(stock_info.stock_code)
        exchange = self._infer_exchange_from_market(market)
        base_code = str(stock_info.stock_code or "").strip().upper().split(".", 1)[0]
        if base_code[:2] in {"SH", "SZ", "BJ"} and len(base_code) > 2:
            base_code = base_code[2:]
        canonical_code = (
            f"{base_code}.{market}"
            if market in {"SH", "SZ", "BJ"} and base_code
            else str(stock_info.stock_code).strip().upper()
        )
        exchange_enum = MarketExchange(exchange)
        self._dc_asset_repo.upsert(
            AssetMaster(
                code=canonical_code,
                name=str(stock_info.name or canonical_code),
                short_name=str(stock_info.name or canonical_code),
                asset_type=AssetType.STOCK,
                exchange=exchange_enum,
                is_active=True,
                list_date=stock_info.list_date,
                sector=str(stock_info.sector or ""),
                industry=str(stock_info.sector or ""),
            )
        )

    @staticmethod
    def _stock_info_from_asset(asset: AssetMaster) -> StockInfo:
        """Convert a canonical AssetMaster record to the equity value object."""

        market_map = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}
        return StockInfo(
            stock_code=asset.code,
            name=asset.short_name or asset.name,
            sector=asset.sector or asset.industry or "",
            market=market_map.get(asset.exchange.value, ""),
            list_date=asset.list_date,
        )

    def save_financial_data(self, financial: FinancialData) -> None:
        """
        保存财务数据

        Args:
            financial: FinancialData 实体
        """
        required_values = (
            financial.revenue,
            financial.net_profit,
            financial.total_assets,
            financial.total_liabilities,
            financial.equity,
            financial.roe,
            financial.debt_ratio,
        )
        if any(value is None for value in required_values):
            logger.warning(
                "Skip persisting incomplete financial fact for %s/%s",
                financial.stock_code,
                financial.report_date,
            )
            return

        # 确定报告类型
        month = financial.report_date.month
        if month == 3:
            report_type = "1Q"
        elif month == 6:
            report_type = "2Q"
        elif month == 9:
            report_type = "3Q"
        else:
            report_type = "4Q"

        # Legacy equity rows are read-only migration fixtures.  New writes go
        # exclusively through the canonical Data Center repository below.
        self._dc_financial_repo.bulk_upsert(
            self._financial_entity_to_dc_facts(financial, report_type)
        )

    def save_valuation(self, valuation: ValuationMetrics) -> None:
        """
        保存估值数据

        Args:
            valuation: ValuationMetrics 实体
        """
        pe = valuation.pe
        pb = valuation.pb
        ps = valuation.ps
        total_mv = valuation.total_mv
        circ_mv = valuation.circ_mv
        dividend_yield = valuation.dividend_yield
        if not valuation.is_valid or any(
            value is None for value in (pe, pb, ps, total_mv, circ_mv, dividend_yield)
        ):
            logger.warning(
                "Skip persisting incomplete valuation fact for %s/%s",
                valuation.stock_code,
                valuation.trade_date,
            )
            return

        assert pe is not None
        assert pb is not None
        assert ps is not None
        assert total_mv is not None
        assert circ_mv is not None
        assert dividend_yield is not None

        # Legacy valuation rows are read-only migration fixtures.  New writes
        # go exclusively through the canonical Data Center repository below.
        self._dc_valuation_repo.bulk_upsert([self._valuation_entity_to_dc_fact(valuation)])

    def _get_latest_price_bar(
        self,
        stock_code: str,
        *,
        published_only: bool = False,
        publication_key: str = "current",
    ) -> PriceBar | None:
        if not published_only:
            return self._dc_price_bar_repo.get_latest(stock_code)

        payload = get_published_price_bar_series(
            stock_code,
            publication_key=publication_key,
            limit=1,
        )
        if bool(payload.get("must_not_use_for_decision")):
            return None
        rows = payload.get("rows", [])
        if not isinstance(rows, (list, tuple)):
            return None
        bars = [
            bar
            for row in rows
            if isinstance(row, Mapping)
            for bar in [self._price_bar_from_public_row(row, stock_code)]
            if bar is not None
        ]
        return max(bars, key=lambda bar: bar.bar_date) if bars else None

    @staticmethod
    def _price_bar_from_public_row(
        row: Mapping[str, object],
        default_asset_code: str,
    ) -> PriceBar | None:
        """Convert one publication-bound OHLCV row without fabricating time."""

        asset_code = str(row.get("asset_code") or default_asset_code).strip().upper()
        bar_date = _parse_fact_date(row.get("bar_date", row.get("timestamp")))
        fetched_at = _parse_fact_datetime(row.get("fetched_at"))
        if not asset_code or bar_date is None or fetched_at is None:
            return None

        def _number(field: str) -> float | None:
            return safe_float(row.get(field), default=None)

        open_price = _number("open")
        high = _number("high")
        low = _number("low")
        close = _number("close")
        if open_price is None or high is None or low is None or close is None:
            return None
        volume = _number("volume")
        amount = _number("amount")
        try:
            adjustment = PriceAdjustment(str(row.get("adjustment") or "none"))
            return PriceBar(
                asset_code=asset_code,
                bar_date=bar_date,
                open=open_price,
                high=high,
                low=low,
                close=close,
                freq=str(row.get("freq") or row.get("period") or "1d"),
                adjustment=adjustment,
                volume=volume,
                amount=amount,
                source=str(row.get("source") or ""),
                fetched_at=fetched_at,
            )
        except ValueError:
            return None

    def _get_latest_financial(
        self,
        stock_code: str,
        *,
        published_only: bool = False,
        publication_key: str = "current",
    ) -> FinancialData | None:
        if published_only:
            payload = get_published_financial_facts(
                stock_code,
                publication_key=publication_key,
                limit=120,
            )
            if bool(payload.get("must_not_use_for_decision")):
                return None
            rows = payload.get("rows", [])
            if not isinstance(rows, (list, tuple)):
                return None
            facts = [
                fact
                for row in rows
                if isinstance(row, Mapping)
                for fact in [self._financial_fact_from_public_row(row)]
                if fact is not None
            ]
            dc_items = self._financial_data_from_facts(stock_code, facts, limit=1)
        else:
            dc_items = self._get_financials_from_data_center(stock_code, limit=1)
        return dc_items[0] if dc_items else None

    @staticmethod
    def _financial_fact_from_public_row(row: Mapping[str, object]) -> FinancialFact | None:
        """Convert a publication-bound financial row without fabricating timestamps."""

        asset_code = str(row.get("asset_code") or "").strip().upper()
        metric_code = str(row.get("metric_code") or "").strip()
        period_end = _parse_fact_date(row.get("period_end"))
        fetched_at = _parse_fact_datetime(row.get("fetched_at"))
        value = safe_float(row.get("value"), default=None)
        if not asset_code or not metric_code or period_end is None or fetched_at is None:
            return None
        if value is None:
            return None

        try:
            period_type = FinancialPeriodType(str(row.get("period_type") or ""))
        except ValueError:
            return None

        report_raw = row.get("report_date")
        report_date = _parse_fact_date(report_raw) if report_raw not in (None, "") else None
        available_raw = row.get("available_at")
        available_at = (
            _parse_fact_datetime(available_raw) if available_raw not in (None, "") else None
        )
        if report_raw not in (None, "") and report_date is None:
            return None
        if available_raw not in (None, "") and available_at is None:
            return None
        raw_extra = row.get("extra")
        extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}

        try:
            return FinancialFact(
                asset_code=asset_code,
                period_end=period_end,
                period_type=period_type,
                metric_code=metric_code,
                value=value,
                unit=str(row.get("unit") or ""),
                source=str(row.get("source") or ""),
                report_date=report_date,
                available_at=available_at,
                fetched_at=fetched_at,
                extra=extra,
            )
        except ValueError:
            return None

    def _get_latest_valuation(
        self,
        stock_code: str,
        *,
        published_only: bool = False,
        publication_key: str = "current",
    ) -> ValuationMetrics | None:
        if published_only:
            payload = get_published_valuation_facts(
                stock_code,
                publication_key=publication_key,
                limit=20,
            )
            if bool(payload.get("must_not_use_for_decision")):
                return None
            rows = payload.get("rows", [])
            if not isinstance(rows, (list, tuple)):
                return None
            facts = [
                fact
                for row in rows
                if isinstance(row, Mapping)
                for fact in [self._valuation_fact_from_public_row(row)]
                if fact is not None
            ]
            if not facts:
                return None
            return self._dc_fact_to_valuation(max(facts, key=lambda fact: fact.val_date))
        dc_item = self._dc_valuation_repo.get_latest(stock_code)
        return self._dc_fact_to_valuation(dc_item) if dc_item is not None else None

    @staticmethod
    def _valuation_fact_from_public_row(row: Mapping[str, object]) -> ValuationFact | None:
        """Convert one publication-bound valuation row without fabricating time."""

        val_date = _parse_fact_date(row.get("val_date"))
        fetched_at = _parse_fact_datetime(row.get("fetched_at"))
        if val_date is None or fetched_at is None:
            return None
        available_raw = row.get("available_at")
        available_at = (
            _parse_fact_datetime(available_raw) if available_raw not in (None, "") else None
        )
        if available_raw not in (None, "") and available_at is None:
            return None
        raw_extra = row.get("extra")
        extra: dict[str, Any] = raw_extra if isinstance(raw_extra, dict) else {}

        def _number(field: str) -> float | None:
            return safe_float(row.get(field), default=None)

        try:
            return ValuationFact(
                asset_code=str(row.get("asset_code") or "").strip().upper(),
                val_date=val_date,
                pe_ttm=_number("pe_ttm"),
                pe_static=_number("pe_static"),
                pb=_number("pb"),
                ps_ttm=_number("ps_ttm"),
                market_cap=_number("market_cap"),
                float_market_cap=_number("float_market_cap"),
                dv_ratio=_number("dv_ratio"),
                source=str(row.get("source") or ""),
                available_at=available_at,
                fetched_at=fetched_at,
                extra=extra,
            )
        except ValueError:
            return None

    def _get_financials_from_data_center(
        self,
        stock_code: str,
        limit: int,
    ) -> list[FinancialData]:
        facts = self._dc_financial_repo.get_facts(stock_code, limit=max(limit * 12, 40))
        return self._financial_data_from_facts(stock_code, facts, limit=limit)

    def _financial_data_from_facts(
        self,
        stock_code: str,
        facts: Sequence[FinancialFact],
        *,
        limit: int,
    ) -> list[FinancialData]:
        if not facts:
            return []

        grouped: dict[date, dict[str, FinancialFact]] = {}
        report_dates: dict[date, date | None] = {}
        period_types: dict[date, str] = {}
        sources: dict[date, str] = {}
        fetched_ats: dict[date, datetime | None] = {}
        for fact in facts:
            grouped.setdefault(fact.period_end, {})[fact.metric_code] = fact
            if fact.period_end not in report_dates or report_dates[fact.period_end] is None:
                report_dates[fact.period_end] = fact.report_date
            period_types.setdefault(fact.period_end, fact.period_type.value)
            sources.setdefault(fact.period_end, fact.source)
            fetched_ats.setdefault(fact.period_end, fact.fetched_at)

        results: list[FinancialData] = []
        required_metrics = {
            "revenue",
            "net_profit",
            "total_assets",
            "total_liabilities",
            "equity",
            "roe",
            "debt_ratio",
        }
        for period_end in sorted(grouped.keys(), reverse=True):
            metric_map = grouped[period_end]
            if not required_metrics.issubset(metric_map.keys()):
                continue
            revenue_growth_fact = metric_map.get("revenue_growth")
            net_profit_growth_fact = metric_map.get("net_profit_growth")
            roa_fact = metric_map.get("roa")
            results.append(
                FinancialData(
                    stock_code=stock_code,
                    report_date=report_dates.get(period_end) or period_end,
                    revenue=Decimal(str(metric_map["revenue"].value)),
                    net_profit=Decimal(str(metric_map["net_profit"].value)),
                    revenue_growth=(
                        float(revenue_growth_fact.value) if revenue_growth_fact else None
                    ),
                    net_profit_growth=(
                        float(net_profit_growth_fact.value) if net_profit_growth_fact else None
                    ),
                    total_assets=Decimal(str(metric_map["total_assets"].value)),
                    total_liabilities=Decimal(str(metric_map["total_liabilities"].value)),
                    equity=Decimal(str(metric_map["equity"].value)),
                    roe=float(metric_map["roe"].value),
                    roa=float(roa_fact.value) if roa_fact else None,
                    debt_ratio=float(metric_map["debt_ratio"].value),
                    period_end=period_end,
                    period_type=period_types.get(period_end, ""),
                    source=sources.get(period_end, ""),
                    fetched_at=fetched_ats.get(period_end),
                )
            )
            if len(results) >= limit:
                break
        return results

    def _get_valuations_from_data_center(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationMetrics]:
        facts = self._dc_valuation_repo.get_series(stock_code, start=start_date, end=end_date)
        if not facts:
            return []
        return [
            valuation
            for fact in reversed(facts)
            for valuation in [self._dc_fact_to_valuation(fact)]
            if valuation.is_valid
        ]

    def _get_published_valuations_from_data_center(
        self,
        stock_code: str,
        *,
        start_date: date,
        end_date: date,
        publication_key: str,
    ) -> list[ValuationMetrics]:
        """Read valuation history only from the selected publication members."""

        payload = get_published_valuation_facts(
            stock_code,
            as_of=end_date,
            limit=5000,
            publication_key=publication_key,
        )
        if bool(payload.get("must_not_use_for_decision")):
            return []
        rows = payload.get("rows", [])
        if not isinstance(rows, (list, tuple)):
            return []
        facts = [
            fact
            for row in rows
            if isinstance(row, Mapping)
            for fact in [self._valuation_fact_from_public_row(row)]
            if fact is not None and start_date <= fact.val_date <= end_date
        ]
        return [
            valuation
            for fact in sorted(facts, key=lambda item: item.val_date)
            for valuation in [self._dc_fact_to_valuation(fact)]
            if valuation.is_valid
        ]

    def _dc_fact_to_valuation(self, fact: ValuationFact) -> ValuationMetrics:
        total_mv = Decimal(str(fact.market_cap)) if fact.market_cap is not None else None
        circ_mv = (
            Decimal(str(fact.float_market_cap)) if fact.float_market_cap is not None else total_mv
        )
        quality_is_complete = all(
            value is not None
            for value in (
                fact.pe_ttm if fact.pe_ttm is not None else fact.pe_static,
                fact.pb,
                fact.market_cap,
            )
        )
        return ValuationMetrics(
            stock_code=fact.asset_code,
            trade_date=fact.val_date,
            pe=fact.pe_ttm if fact.pe_ttm is not None else fact.pe_static,
            pb=fact.pb,
            ps=fact.ps_ttm,
            total_mv=total_mv,
            circ_mv=circ_mv,
            dividend_yield=fact.dv_ratio,
            source_provider=fact.source,
            source_updated_at=fact.fetched_at,
            fetched_at=fact.fetched_at,
            pe_type="ttm" if fact.pe_ttm is not None else "static",
            is_valid=quality_is_complete,
            quality_flag="ok" if quality_is_complete else "missing_required_metric",
            quality_notes=("" if quality_is_complete else "missing PE, PB, or market cap"),
        )

    def _financial_entity_to_dc_facts(
        self,
        financial: FinancialData,
        report_type: str,
    ) -> list[FinancialFact]:
        period_type_map = {
            "1Q": FinancialPeriodType.QUARTERLY,
            "2Q": FinancialPeriodType.SEMI_ANNUAL,
            "3Q": FinancialPeriodType.QUARTERLY,
            "4Q": FinancialPeriodType.ANNUAL,
        }
        period_type = period_type_map[report_type]
        source, lineage_extra = _canonical_fact_source(financial.source)
        fetched_at = _parse_fact_datetime(financial.fetched_at) or timezone.now()

        def build_fact(metric_code: str, value: float | None, unit: str) -> FinancialFact | None:
            if value is None:
                return None
            return FinancialFact(
                asset_code=financial.stock_code,
                period_end=financial.report_date,
                period_type=period_type,
                metric_code=metric_code,
                value=value,
                unit=unit,
                source=source,
                report_date=financial.report_date,
                fetched_at=fetched_at,
                extra=dict(lineage_extra),
            )

        raw_facts = [
            build_fact(
                "revenue", float(financial.revenue) if financial.revenue is not None else None, "元"
            ),
            build_fact(
                "net_profit",
                float(financial.net_profit) if financial.net_profit is not None else None,
                "元",
            ),
            build_fact("revenue_growth", financial.revenue_growth, "%"),
            build_fact("net_profit_growth", financial.net_profit_growth, "%"),
            build_fact(
                "total_assets",
                float(financial.total_assets) if financial.total_assets is not None else None,
                "元",
            ),
            build_fact(
                "total_liabilities",
                (
                    float(financial.total_liabilities)
                    if financial.total_liabilities is not None
                    else None
                ),
                "元",
            ),
            build_fact(
                "equity", float(financial.equity) if financial.equity is not None else None, "元"
            ),
            build_fact("roe", financial.roe, "%"),
            build_fact("roa", financial.roa, "%"),
            build_fact("debt_ratio", financial.debt_ratio, "%"),
        ]
        return [fact for fact in raw_facts if fact is not None]

    def _valuation_entity_to_dc_fact(self, valuation: ValuationMetrics) -> ValuationFact:
        source, lineage_extra = _canonical_fact_source(valuation.source_provider)
        fetched_at = _parse_fact_datetime(valuation.fetched_at) or timezone.now()
        return ValuationFact(
            asset_code=valuation.stock_code,
            val_date=valuation.trade_date,
            pe_ttm=valuation.pe,
            pb=valuation.pb,
            ps_ttm=valuation.ps,
            market_cap=(float(valuation.total_mv) if valuation.total_mv is not None else None),
            float_market_cap=(float(valuation.circ_mv) if valuation.circ_mv is not None else None),
            dv_ratio=valuation.dividend_yield,
            source=source,
            available_at=_parse_fact_datetime(valuation.source_updated_at),
            fetched_at=fetched_at,
            extra=lineage_extra,
        )

    def get_latest_financial_data(
        self,
        stock_code: str,
        *,
        hydrate: bool = False,
        published_only: bool = True,
        publication_key: str = "current",
    ) -> FinancialData | None:
        """
        获取股票最新的财务数据

        Args:
            stock_code: 股票代码

        Returns:
            FinancialData 或 None
        """
        if published_only:
            return self._get_latest_financial(
                stock_code,
                published_only=True,
                publication_key=publication_key,
            )
        if hydrate:
            items = self.get_financial_data(stock_code, limit=1, hydrate=True)
            return items[0] if items else None
        return self._get_latest_financial(stock_code, published_only=False)

    def get_latest_valuation_date(self) -> date | None:
        """获取最新估值日期。"""
        return self._dc_valuation_repo.get_latest_date()

    def get_valuation_models_by_date(self, as_of_date: date) -> list[ValuationMetrics]:
        """Return canonical valuation facts for quality validation on one date."""

        return [
            valuation
            for fact in self._dc_valuation_repo.list_by_date(as_of_date)
            for valuation in [self._dc_fact_to_valuation(fact)]
        ]


__all__ = ["StockFundamentalsRepositoryMixin"]
