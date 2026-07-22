"""Fundamental data (financials/valuation) slice of the equity stock repository.

This module owns the `StockFundamentalsRepositoryMixin` slice of
`DjangoStockRepository`, including Data Center fact-table mappings. Shared
helpers and dependency wiring live in `stock_repository.py`; do not import the
compatibility facade here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from apps.data_center.domain.entities import FinancialFact, ValuationFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.protocols import (
    FinancialFactRepositoryProtocol,
    ValuationFactRepositoryProtocol,
)
from apps.equity.domain.entities import (
    FinancialData,
    StockInfo,
    ValuationMetrics,
)
from shared.numeric import safe_float

from .models import (
    FinancialDataModel,
    StockDailyModel,
    StockInfoModel,
    ValuationModel,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from apps.data_center.application.on_demand import OnDemandDataCenterService


class StockFundamentalsRepositoryMixin:
    """Financial, valuation, and aggregated fundamental context persistence."""

    _dc_financial_repo: FinancialFactRepositoryProtocol
    _dc_valuation_repo: ValuationFactRepositoryProtocol
    _dc_on_demand: OnDemandDataCenterService

    if TYPE_CHECKING:

        def _build_stock_code_candidates(self, stock_code: str) -> list[str]: ...

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

        # 获取所有活跃股票的基本信息
        stock_infos = StockInfoModel._default_manager.filter(is_active=True)

        for stock_info_model in stock_infos:
            stock_code = stock_info_model.stock_code

            # 转换为 Domain 层实体
            stock_info = StockInfo(
                stock_code=stock_info_model.stock_code,
                name=stock_info_model.name,
                sector=stock_info_model.sector,
                market=stock_info_model.market,
                list_date=stock_info_model.list_date,
            )

            # 获取最新财务数据
            financial = self._get_latest_financial(stock_code)
            if not financial:
                # 没有财务数据，跳过
                continue

            # 获取最新估值数据
            valuation = self._get_latest_valuation(stock_code)
            if not valuation:
                # 没有估值数据，跳过
                continue

            result.append((stock_info, financial, valuation))

        return result

    def get_stock_context_rows(self, stock_codes: list[str]) -> dict[str, dict[str, Any]]:
        """Return stock info plus latest market and canonical fundamental context."""

        normalized_codes = [str(code).upper() for code in stock_codes if code]
        if not normalized_codes:
            return {}

        requested_codes = list(dict.fromkeys(normalized_codes))
        candidate_codes = {
            candidate
            for code in requested_codes
            for candidate in self._build_stock_code_candidates(code)
        }
        info_rows = StockInfoModel._default_manager.filter(
            stock_code__in=list(candidate_codes)
        ).values(
            "stock_code",
            "name",
            "sector",
            "market",
        )
        info_map = {str(row["stock_code"]).upper(): row for row in info_rows}

        daily_rows = (
            StockDailyModel._default_manager.filter(stock_code__in=list(candidate_codes))
            .order_by("stock_code", "-trade_date")
            .values("stock_code", "trade_date", "close", "volume")
        )
        daily_map: dict[str, Mapping[str, object]] = {}
        for daily_row in daily_rows:
            code = str(daily_row["stock_code"]).upper()
            if code not in daily_map:
                daily_map[code] = daily_row

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
            latest_financial = self._get_stock_context_financial_fact_row(requested_code)
            latest_valuation = self._get_stock_context_valuation_fact_row(requested_code)
            context[requested_code] = {
                **context_row,
                "trade_date": latest_daily.get("trade_date"),
                "close": safe_float(latest_daily.get("close"), default=0.0),
                "volume": safe_float(latest_daily.get("volume"), default=0.0),
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

    def _get_stock_context_financial_fact_row(self, stock_code: str) -> dict[str, Any]:
        latest_financials = self._get_financials_from_data_center(stock_code, limit=1)
        if not latest_financials:
            return {}

        latest = latest_financials[0]
        return {
            "report_date": latest.report_date,
            "roe": latest.roe,
            "debt_ratio": latest.debt_ratio,
            "revenue_growth": latest.revenue_growth,
            "net_profit_growth": latest.net_profit_growth,
        }

    def _get_stock_context_valuation_fact_row(self, stock_code: str) -> dict[str, Any]:
        latest_fact = self._dc_valuation_repo.get_latest(stock_code)
        if latest_fact is None:
            return {}

        latest = self._dc_fact_to_valuation(latest_fact)
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
        if dc_financials:
            return dc_financials

        for candidate in self._build_stock_code_candidates(stock_code):
            models = FinancialDataModel._default_manager.filter(stock_code=candidate).order_by(
                "-report_date"
            )[:limit]
            if not models:
                continue
            return [
                FinancialData(
                    stock_code=m.stock_code,
                    report_date=m.report_date,
                    revenue=m.revenue,
                    net_profit=m.net_profit,
                    revenue_growth=m.revenue_growth or 0.0,
                    net_profit_growth=m.net_profit_growth or 0.0,
                    total_assets=m.total_assets,
                    total_liabilities=m.total_liabilities,
                    equity=m.equity,
                    roe=m.roe,
                    roa=m.roa or 0.0,
                    debt_ratio=m.debt_ratio,
                )
                for m in models
            ]
        return []

    def get_valuation_history(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        *,
        hydrate: bool = False,
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
        if hydrate:
            self._dc_on_demand.ensure_valuations(stock_code, start_date, end_date)
        dc_valuations = self._get_valuations_from_data_center(stock_code, start_date, end_date)
        if dc_valuations:
            return dc_valuations

        for candidate in self._build_stock_code_candidates(stock_code):
            models = ValuationModel._default_manager.filter(
                stock_code=candidate,
                trade_date__gte=start_date,
                trade_date__lte=end_date,
            ).order_by("trade_date")
            if not models:
                continue
            return [
                ValuationMetrics(
                    stock_code=m.stock_code,
                    trade_date=m.trade_date,
                    pe=m.pe or 0.0,
                    pb=m.pb or 0.0,
                    ps=m.ps or 0.0,
                    total_mv=m.total_mv,
                    circ_mv=m.circ_mv,
                    dividend_yield=m.dividend_yield or 0.0,
                    source_provider=m.source_provider,
                    source_updated_at=m.source_updated_at,
                    fetched_at=m.fetched_at,
                    pe_type=m.pe_type,
                    is_valid=m.is_valid,
                    quality_flag=m.quality_flag,
                    quality_notes=m.quality_notes,
                    raw_payload_hash=m.raw_payload_hash,
                )
                for m in models
            ]
        return []

    def save_stock_info(self, stock_info: StockInfo) -> None:
        """
        保存股票基本信息

        Args:
            stock_info: StockInfo 实体
        """
        # Remote fallback metadata can be partial; skip caching if required fields are missing.
        if stock_info.list_date is None:
            logger.info(
                "Skip caching stock info for %s because list_date is unavailable",
                stock_info.stock_code,
            )
            return

        StockInfoModel._default_manager.update_or_create(
            stock_code=stock_info.stock_code,
            defaults={
                "name": stock_info.name,
                "sector": stock_info.sector,
                "market": stock_info.market,
                "list_date": stock_info.list_date,
            },
        )

    def save_financial_data(self, financial: FinancialData) -> None:
        """
        保存财务数据

        Args:
            financial: FinancialData 实体
        """
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

        FinancialDataModel._default_manager.update_or_create(
            stock_code=financial.stock_code,
            report_date=financial.report_date,
            report_type=report_type,
            defaults={
                "revenue": financial.revenue,
                "net_profit": financial.net_profit,
                "revenue_growth": financial.revenue_growth,
                "net_profit_growth": financial.net_profit_growth,
                "total_assets": financial.total_assets,
                "total_liabilities": financial.total_liabilities,
                "equity": financial.equity,
                "roe": financial.roe,
                "roa": financial.roa,
                "debt_ratio": financial.debt_ratio,
            },
        )
        self._dc_financial_repo.bulk_upsert(
            self._financial_entity_to_dc_facts(financial, report_type)
        )

    def save_valuation(self, valuation: ValuationMetrics) -> None:
        """
        保存估值数据

        Args:
            valuation: ValuationMetrics 实体
        """
        ValuationModel._default_manager.update_or_create(
            stock_code=valuation.stock_code,
            trade_date=valuation.trade_date,
            defaults={
                "pe": valuation.pe,
                "pb": valuation.pb,
                "ps": valuation.ps,
                "total_mv": valuation.total_mv,
                "circ_mv": valuation.circ_mv,
                "dividend_yield": valuation.dividend_yield,
                "source_provider": valuation.source_provider,
                "source_updated_at": valuation.source_updated_at,
                "fetched_at": valuation.fetched_at or timezone.now(),
                "pe_type": valuation.pe_type,
                "is_valid": valuation.is_valid,
                "quality_flag": valuation.quality_flag,
                "quality_notes": valuation.quality_notes,
                "raw_payload_hash": valuation.raw_payload_hash,
            },
        )
        self._dc_valuation_repo.bulk_upsert([self._valuation_entity_to_dc_fact(valuation)])

    def _get_latest_financial(self, stock_code: str) -> FinancialData | None:
        dc_items = self._get_financials_from_data_center(stock_code, limit=1)
        if dc_items:
            return dc_items[0]

        for candidate in self._build_stock_code_candidates(stock_code):
            financial_model = (
                FinancialDataModel._default_manager.filter(stock_code=candidate)
                .order_by("-report_date")
                .first()
            )
            if financial_model is None:
                continue
            return FinancialData(
                stock_code=financial_model.stock_code,
                report_date=financial_model.report_date,
                revenue=financial_model.revenue,
                net_profit=financial_model.net_profit,
                revenue_growth=financial_model.revenue_growth or 0.0,
                net_profit_growth=financial_model.net_profit_growth or 0.0,
                total_assets=financial_model.total_assets,
                total_liabilities=financial_model.total_liabilities,
                equity=financial_model.equity,
                roe=financial_model.roe,
                roa=financial_model.roa or 0.0,
                debt_ratio=financial_model.debt_ratio,
            )
        return None

    def _get_latest_valuation(self, stock_code: str) -> ValuationMetrics | None:
        dc_item = self._dc_valuation_repo.get_latest(stock_code)
        if dc_item is not None:
            return self._dc_fact_to_valuation(dc_item)

        for candidate in self._build_stock_code_candidates(stock_code):
            valuation_model = (
                ValuationModel._default_manager.filter(stock_code=candidate)
                .order_by("-trade_date")
                .first()
            )
            if valuation_model is None:
                continue
            return ValuationMetrics(
                stock_code=valuation_model.stock_code,
                trade_date=valuation_model.trade_date,
                pe=valuation_model.pe or 0.0,
                pb=valuation_model.pb or 0.0,
                ps=valuation_model.ps or 0.0,
                total_mv=valuation_model.total_mv,
                circ_mv=valuation_model.circ_mv,
                dividend_yield=valuation_model.dividend_yield or 0.0,
                source_provider=valuation_model.source_provider,
                source_updated_at=valuation_model.source_updated_at,
                fetched_at=valuation_model.fetched_at,
                pe_type=valuation_model.pe_type,
                is_valid=valuation_model.is_valid,
                quality_flag=valuation_model.quality_flag,
                quality_notes=valuation_model.quality_notes,
                raw_payload_hash=valuation_model.raw_payload_hash,
            )
        return None

    def _get_financials_from_data_center(
        self,
        stock_code: str,
        limit: int,
    ) -> list[FinancialData]:
        facts = self._dc_financial_repo.get_facts(stock_code, limit=max(limit * 12, 40))
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
                        float(revenue_growth_fact.value) if revenue_growth_fact else 0.0
                    ),
                    net_profit_growth=(
                        float(net_profit_growth_fact.value) if net_profit_growth_fact else 0.0
                    ),
                    total_assets=Decimal(str(metric_map["total_assets"].value)),
                    total_liabilities=Decimal(str(metric_map["total_liabilities"].value)),
                    equity=Decimal(str(metric_map["equity"].value)),
                    roe=float(metric_map["roe"].value),
                    roa=float(roa_fact.value) if roa_fact else 0.0,
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
        return [self._dc_fact_to_valuation(fact) for fact in reversed(facts)]

    def _dc_fact_to_valuation(self, fact: ValuationFact) -> ValuationMetrics:
        total_mv = fact.market_cap if fact.market_cap is not None else 0.0
        circ_mv = fact.float_market_cap if fact.float_market_cap is not None else total_mv
        return ValuationMetrics(
            stock_code=fact.asset_code,
            trade_date=fact.val_date,
            pe=fact.pe_ttm or fact.pe_static or 0.0,
            pb=fact.pb or 0.0,
            ps=fact.ps_ttm or 0.0,
            total_mv=Decimal(str(total_mv)),
            circ_mv=Decimal(str(circ_mv)),
            dividend_yield=fact.dv_ratio or 0.0,
            source_provider=fact.source,
            source_updated_at=fact.fetched_at,
            fetched_at=fact.fetched_at,
            pe_type="ttm" if fact.pe_ttm is not None else "static",
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

        def build_fact(metric_code: str, value: float, unit: str) -> FinancialFact:
            return FinancialFact(
                asset_code=financial.stock_code,
                period_end=financial.report_date,
                period_type=period_type,
                metric_code=metric_code,
                value=value,
                unit=unit,
                source="equity_legacy_repo",
                report_date=financial.report_date,
            )

        return [
            build_fact("revenue", float(financial.revenue), "元"),
            build_fact("net_profit", float(financial.net_profit), "元"),
            build_fact("revenue_growth", float(financial.revenue_growth), "%"),
            build_fact("net_profit_growth", float(financial.net_profit_growth), "%"),
            build_fact("total_assets", float(financial.total_assets), "元"),
            build_fact("total_liabilities", float(financial.total_liabilities), "元"),
            build_fact("equity", float(financial.equity), "元"),
            build_fact("roe", float(financial.roe), "%"),
            build_fact("roa", float(financial.roa), "%"),
            build_fact("debt_ratio", float(financial.debt_ratio), "%"),
        ]

    def _valuation_entity_to_dc_fact(self, valuation: ValuationMetrics) -> ValuationFact:
        return ValuationFact(
            asset_code=valuation.stock_code,
            val_date=valuation.trade_date,
            pe_ttm=valuation.pe,
            pb=valuation.pb,
            ps_ttm=valuation.ps,
            market_cap=float(valuation.total_mv),
            float_market_cap=float(valuation.circ_mv),
            dv_ratio=valuation.dividend_yield,
            source=valuation.source_provider or "equity_legacy_repo",
            fetched_at=valuation.fetched_at or timezone.now(),
        )

    def get_latest_financial_data(
        self,
        stock_code: str,
        *,
        hydrate: bool = False,
    ) -> FinancialData | None:
        """
        获取股票最新的财务数据

        Args:
            stock_code: 股票代码

        Returns:
            FinancialData 或 None
        """
        if hydrate:
            items = self.get_financial_data(stock_code, limit=1, hydrate=True)
            return items[0] if items else None
        return self._get_latest_financial(stock_code)

    def get_latest_valuation_date(self) -> date | None:
        """获取最新估值日期。"""
        latest: date | None = (
            ValuationModel._default_manager.order_by("-trade_date")
            .values_list("trade_date", flat=True)
            .first()
        )
        return latest

    def get_valuation_models_by_date(self, as_of_date: date) -> list[ValuationModel]:
        """获取指定日期的原始估值模型记录。"""
        return list(
            ValuationModel._default_manager.filter(trade_date=as_of_date).order_by("stock_code")
        )


__all__ = ["StockFundamentalsRepositoryMixin"]
