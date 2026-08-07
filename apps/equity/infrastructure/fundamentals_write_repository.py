"""Canonical equity fundamental write repository slice."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.data_center.domain.entities import AssetMaster, FinancialFact, ValuationFact
from apps.data_center.domain.enums import AssetType, FinancialPeriodType, MarketExchange
from apps.data_center.domain.protocols import (
    AssetRepositoryProtocol,
    FinancialFactRepositoryProtocol,
    ValuationFactRepositoryProtocol,
)
from apps.equity.domain.entities import FinancialData, StockInfo, ValuationMetrics
from apps.equity.infrastructure.fundamentals_fact_helpers import (
    canonical_fact_source as _canonical_fact_source,
)
from apps.equity.infrastructure.fundamentals_fact_helpers import (
    parse_fact_datetime as _parse_fact_datetime,
)

logger = logging.getLogger(__name__)


class StockFundamentalsWriteRepositoryMixin:
    """Persist equity identity, financial, and valuation facts canonically."""

    _dc_asset_repo: AssetRepositoryProtocol
    _dc_financial_repo: FinancialFactRepositoryProtocol
    _dc_valuation_repo: ValuationFactRepositoryProtocol

    if TYPE_CHECKING:

        def _infer_exchange_from_market(self, market: str) -> str: ...

        def _infer_market_from_stock_code(self, stock_code: str) -> str: ...

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


__all__ = ["StockFundamentalsWriteRepositoryMixin"]
