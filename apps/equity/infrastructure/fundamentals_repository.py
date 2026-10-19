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

from apps.data_center.application.public import (
    get_published_equity_analysis_context_payloads,
    get_published_financial_facts,
    get_published_price_bar_series,
    get_published_valuation_facts,
)
from apps.data_center.domain.entities import FinancialFact, PriceBar, ValuationFact
from apps.data_center.domain.enums import AssetType
from apps.data_center.domain.protocols import (
    AssetRepositoryProtocol,
    FinancialFactRepositoryProtocol,
    PriceBarRepositoryProtocol,
    ValuationFactRepositoryProtocol,
)
from apps.equity.application.use_case_protocols import (
    EquityPublicationGate,
    PublicationEvidenceValue,
    PublishedEquityValuationInputs,
)
from apps.equity.domain.entities import (
    FinancialData,
    StockInfo,
    ValuationMetrics,
)
from apps.equity.infrastructure.fundamentals_fact_helpers import parse_fact_date as _parse_fact_date
from apps.equity.infrastructure.fundamentals_fact_helpers import (
    parse_fact_datetime as _parse_fact_datetime,
)
from apps.equity.infrastructure.fundamentals_published_fact_mappers import (
    parse_public_financial_fact as _parse_public_financial_fact,
)
from apps.equity.infrastructure.fundamentals_published_fact_mappers import (
    parse_public_price_bar as _parse_public_price_bar,
)
from apps.equity.infrastructure.fundamentals_published_fact_mappers import (
    parse_public_valuation_fact as _parse_public_valuation_fact,
)
from apps.equity.infrastructure.fundamentals_published_fact_mappers import (
    valuation_metrics_from_fact as _valuation_metrics_from_fact,
)
from apps.equity.infrastructure.fundamentals_write_repository import (
    StockFundamentalsWriteRepositoryMixin,
)
from shared.numeric import safe_float

logger = logging.getLogger(__name__)

_PUBLISHED_EQUITY_DATASETS = (
    ("price", "equity.price.bar"),
    ("financial", "equity.financial.fact"),
    ("valuation", "equity.valuation.fact"),
)
_PUBLICATION_GATE_FIELDS = (
    "publication_id",
    "dataset_key",
    "publication_key",
    "publication_hash",
    "published_at",
    "as_of",
    "must_not_use_for_decision",
    "blocked_reason",
    "policy_identity",
    "policy_version",
    "selected_source",
    "publication_run_id",
    "coverage_requested_count",
    "coverage_eligible_count",
    "coverage_selected_count",
    "coverage_missing_count",
    "publication_outcome",
    "freshness_status",
    "freshness_scope",
    "asset_code",
    "observed_at",
    "age_seconds",
    "max_age_seconds",
)

if TYPE_CHECKING:
    from apps.data_center.application.on_demand import OnDemandDataCenterService


class StockFundamentalsRepositoryMixin(StockFundamentalsWriteRepositoryMixin):
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

    def get_published_valuation_inputs(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        *,
        publication_key: str = "current",
        valuation_limit: int = 5000,
    ) -> PublishedEquityValuationInputs:
        """Read valuation, financial, price, and gates in one Data Center snapshot."""

        asset_code = stock_code.strip().upper()
        payloads = get_published_equity_analysis_context_payloads(
            [asset_code],
            publication_key=publication_key,
            valuation_limit=valuation_limit,
        ).get(asset_code, {})
        publication_gates = {
            dataset_key: self._publication_gate_from_context_payload(
                dataset_key,
                publication_key,
                payloads.get(dataset_name),
            )
            for dataset_name, dataset_key in _PUBLISHED_EQUITY_DATASETS
        }

        valuation_payload = payloads.get("valuation")
        valuation_facts = [
            fact
            for row in self._published_context_rows(valuation_payload)
            for fact in [self._valuation_fact_from_public_row(row)]
            if fact is not None
            and fact.asset_code == asset_code
            and start_date <= fact.val_date <= end_date
        ]
        valuation_history = tuple(
            valuation
            for fact in sorted(valuation_facts, key=lambda item: item.val_date)
            for valuation in [self._dc_fact_to_valuation(fact)]
            if valuation.is_valid
        )

        financial_facts = [
            fact
            for row in self._published_context_rows(payloads.get("financial"))
            for fact in [self._financial_fact_from_public_row(row)]
            if fact is not None and fact.asset_code == asset_code
        ]
        financial_rows = self._financial_data_from_facts(
            asset_code,
            financial_facts,
            limit=1,
        )
        latest_financial = financial_rows[0] if financial_rows else None

        prices_by_date: dict[date, Decimal] = {}
        for row in self._published_context_rows(payloads.get("price")):
            row_asset_code = row.get("asset_code")
            if (
                row_asset_code not in (None, "")
                and str(row_asset_code).strip().upper() != asset_code
            ):
                continue
            price_date = _parse_fact_date(row.get("bar_date", row.get("timestamp")))
            fetched_at = _parse_fact_datetime(row.get("fetched_at"))
            close = safe_float(row.get("close"), default=None)
            if (
                price_date is None
                or fetched_at is None
                or fetched_at.tzinfo is None
                or fetched_at.utcoffset() is None
                or close is None
                or close <= 0
            ):
                continue
            prices_by_date[price_date] = Decimal(str(close))

        return PublishedEquityValuationInputs(
            valuation_history=valuation_history,
            latest_financial=latest_financial,
            daily_prices=tuple(sorted(prices_by_date.items())),
            publication_gates=publication_gates,
        )

    @staticmethod
    def _published_context_rows(payload: object) -> list[Mapping[str, object]]:
        """Narrow a selected dataset payload to mapping-shaped fact rows."""

        if not isinstance(payload, Mapping):
            return []
        rows = payload.get("rows")
        if not isinstance(rows, (list, tuple)):
            return []
        return [row for row in rows if isinstance(row, Mapping)]

    @staticmethod
    def _publication_gate_from_context_payload(
        dataset_key: str,
        publication_key: str,
        payload: object,
    ) -> EquityPublicationGate | None:
        """Narrow one context envelope into public scalar evidence, excluding rows."""

        if not isinstance(payload, Mapping):
            return None
        raw_dataset = payload.get("dataset_key")
        raw_publication_key = payload.get("publication_key")
        blocked_reason_raw = payload.get("blocked_reason")
        blocked_reason = (
            blocked_reason_raw.strip()
            if isinstance(blocked_reason_raw, str) and blocked_reason_raw.strip()
            else None
        )
        raw_publication_id = payload.get("publication_id")
        publication_id = (
            raw_publication_id.strip()
            if isinstance(raw_publication_id, str) and raw_publication_id.strip()
            else None
        )
        must_not_use = payload.get("must_not_use_for_decision") is not False
        if raw_dataset != dataset_key or raw_publication_key != publication_key:
            if (
                raw_dataset is None
                and raw_publication_key is None
                and publication_id is None
                and must_not_use
            ):
                blocked_reason = blocked_reason or "canonical_publication_missing"
            else:
                must_not_use = True
                blocked_reason = "publication_scope_mismatch"
        elif not must_not_use and publication_id is None:
            must_not_use = True
            blocked_reason = "publication_member_snapshot_invalid"
        elif must_not_use and blocked_reason is None:
            blocked_reason = (
                "canonical_publication_missing"
                if publication_id is None
                else "publication_member_snapshot_invalid"
            )

        evidence: dict[str, PublicationEvidenceValue] = {}
        for field in _PUBLICATION_GATE_FIELDS:
            value = payload.get(field)
            if value is None or isinstance(value, (str, int, float, bool)):
                evidence[field] = value
        evidence.update(
            publication_id=publication_id,
            must_not_use_for_decision=must_not_use,
            blocked_reason=blocked_reason,
        )
        raw_hash = evidence.get("publication_hash")
        freshness = evidence.get("freshness_status")
        return EquityPublicationGate(
            dataset_key=dataset_key,
            publication_key=publication_key,
            publication_id=publication_id,
            publication_hash=raw_hash if isinstance(raw_hash, str) else None,
            must_not_use_for_decision=must_not_use,
            blocked_reason=blocked_reason,
            freshness_status=freshness if isinstance(freshness, str) else None,
            public_evidence=evidence,
        )

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

        return _parse_public_price_bar(row, default_asset_code)

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

        return _parse_public_financial_fact(row)

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

        return _parse_public_valuation_fact(row)

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
        """Project one Data Center valuation fact into the equity value object."""

        return _valuation_metrics_from_fact(fact)

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
