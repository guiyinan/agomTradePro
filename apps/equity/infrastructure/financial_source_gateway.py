"""财务数据读取网关。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.data_center.application.repository_provider import get_financial_fact_repository
from apps.data_center.domain.entities import FinancialFact

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FinancialRecord:
    """财务数据记录"""

    stock_code: str
    report_date: date
    report_type: str
    revenue: Decimal
    net_profit: Decimal
    revenue_growth: float | None
    net_profit_growth: float | None
    total_assets: Decimal
    total_liabilities: Decimal
    equity: Decimal
    roe: float
    roa: float | None
    debt_ratio: float


@dataclass
class FinancialSyncBatch:
    source_provider: str
    stock_code: str
    records: list[FinancialRecord]


def _to_report_type(period_end: date) -> str:
    if period_end.month == 3:
        return "1Q"
    if period_end.month == 6:
        return "2Q"
    if period_end.month == 9:
        return "3Q"
    return "4Q"


class _BaseFinancialGateway:
    provider_name = ""

    def __init__(self) -> None:
        self._fact_repo = get_financial_fact_repository()

    def fetch(self, stock_code: str, periods: int = 8) -> FinancialSyncBatch:
        rows = self._fact_repo.get_facts(stock_code, limit=max(periods * 12, 80))
        if self.provider_name:
            rows = [row for row in rows if self.provider_name in (row.source or "").lower()]
        if not rows:
            return FinancialSyncBatch(
                source_provider=self.provider_name,
                stock_code=stock_code,
                records=[],
            )

        grouped: dict[date, dict[str, FinancialFact]] = {}
        for row in rows:
            grouped.setdefault(row.period_end, {})[row.metric_code] = row

        records: list[FinancialRecord] = []
        for period_end in sorted(grouped.keys(), reverse=True):
            metric_map = grouped[period_end]
            anchor = metric_map.get("revenue") or next(iter(metric_map.values()))
            records.append(
                FinancialRecord(
                    stock_code=stock_code,
                    report_date=anchor.report_date or period_end,
                    report_type=_to_report_type(period_end),
                    revenue=self._safe_decimal(
                        metric_map.get("revenue").value if metric_map.get("revenue") else 0
                    ),
                    net_profit=self._safe_decimal(
                        metric_map.get("net_profit").value if metric_map.get("net_profit") else 0
                    ),
                    revenue_growth=self._safe_float(
                        metric_map.get("revenue_growth").value
                        if metric_map.get("revenue_growth")
                        else None
                    ),
                    net_profit_growth=self._safe_float(
                        metric_map.get("net_profit_growth").value
                        if metric_map.get("net_profit_growth")
                        else None
                    ),
                    total_assets=self._safe_decimal(
                        metric_map.get("total_assets").value
                        if metric_map.get("total_assets")
                        else 0
                    ),
                    total_liabilities=self._safe_decimal(
                        metric_map.get("total_liabilities").value
                        if metric_map.get("total_liabilities")
                        else 0
                    ),
                    equity=self._safe_decimal(
                        metric_map.get("equity").value if metric_map.get("equity") else 0
                    ),
                    roe=self._safe_float(
                        metric_map.get("roe").value if metric_map.get("roe") else 0
                    )
                    or 0.0,
                    roa=self._safe_float(
                        metric_map.get("roa").value if metric_map.get("roa") else None
                    ),
                    debt_ratio=self._safe_float(
                        metric_map.get("debt_ratio").value if metric_map.get("debt_ratio") else 0
                    )
                    or 0.0,
                )
            )
            if len(records) >= periods:
                break

        return FinancialSyncBatch(
            source_provider=self.provider_name,
            stock_code=stock_code,
            records=records,
        )

    @staticmethod
    def _safe_float(value) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_decimal(value) -> Decimal:
        try:
            if value in (None, ""):
                return Decimal("0")
            return Decimal(str(value))
        except Exception:
            return Decimal("0")


class TushareFinancialGateway(_BaseFinancialGateway):
    """Compatibility gateway reading Tushare-sourced facts from data_center."""

    provider_name = "tushare"

    def __init__(self, token: str, http_url: str | None = None):
        super().__init__()
        self.token = token
        self.http_url = http_url


class AKShareFinancialGateway(_BaseFinancialGateway):
    """Compatibility gateway reading AKShare-sourced facts from data_center."""

    provider_name = "akshare"
