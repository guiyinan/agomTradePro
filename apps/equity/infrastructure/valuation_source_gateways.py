"""
估值数据读取网关。

保留原有主备 provider 类名，但实际从 data_center 估值事实表读取，
不再直接连外部 SDK。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.data_center.composition import get_valuation_fact_repository
from apps.data_center.domain.entities import ValuationFact
from apps.equity.domain.entities import ValuationMetrics
from apps.equity.infrastructure.repositories import compute_valuation_quality_flag

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValuationSyncBatch:
    source_provider: str
    stock_code: str
    records: list[ValuationMetrics]


class _BaseValuationGateway:
    provider_name = ""

    def __init__(self) -> None:
        self._valuation_repo = get_valuation_fact_repository()

    @staticmethod
    def _fact_provider_name(row: ValuationFact) -> str:
        """Resolve the configured provider preserved in canonical fact metadata."""

        provider_name = row.extra.get("provider_name")
        return str(provider_name or row.source).strip()

    def fetch(self, stock_code: str, start_date: date, end_date: date) -> ValuationSyncBatch:
        rows = list(
            reversed(
                self._valuation_repo.get_series(
                    stock_code,
                    start=start_date,
                    end=end_date,
                )
            )
        )
        if self.provider_name:
            expected_provider = self.provider_name.casefold()
            rows = [
                row for row in rows if self._fact_provider_name(row).casefold() == expected_provider
            ]
        previous_pb: float | None = None
        previous_pe: float | None = None
        records: list[ValuationMetrics] = []

        for row in rows:
            provider_name = self._fact_provider_name(row)
            pb = float(row.pb) if row.pb is not None else None
            pe_static = float(row.pe_static) if row.pe_static is not None else None
            pe_ttm = float(row.pe_ttm) if row.pe_ttm is not None else None
            ps_ttm = float(row.ps_ttm) if row.ps_ttm is not None else None
            dv_ratio = float(row.dv_ratio) if row.dv_ratio is not None else None
            is_valid, quality_flag, quality_notes = compute_valuation_quality_flag(
                pb=pb,
                pe=pe_static or pe_ttm,
                previous_pb=previous_pb,
                previous_pe=previous_pe,
            )
            payload_hash = hashlib.sha256(
                json.dumps(
                    {
                        "stock_code": stock_code,
                        "trade_date": row.val_date.isoformat(),
                        "source": row.source,
                        "provider_name": provider_name,
                        "pe_ttm": pe_ttm,
                        "pe_static": pe_static,
                        "pb": pb,
                        "ps_ttm": ps_ttm,
                    },
                    sort_keys=True,
                    ensure_ascii=True,
                ).encode("utf-8")
            ).hexdigest()
            records.append(
                ValuationMetrics(
                    stock_code=stock_code,
                    trade_date=row.val_date,
                    pe=pe_ttm if pe_ttm is not None else pe_static,
                    pb=pb,
                    ps=ps_ttm,
                    total_mv=(
                        Decimal(str(row.market_cap)) if row.market_cap is not None else None
                    ),
                    circ_mv=(
                        Decimal(str(row.float_market_cap))
                        if row.float_market_cap is not None
                        else (
                            Decimal(str(row.market_cap)) if row.market_cap is not None else None
                        )
                    ),
                    dividend_yield=dv_ratio,
                    source_provider=provider_name,
                    source_updated_at=row.fetched_at,
                    fetched_at=row.fetched_at,
                    pe_type="ttm" if row.pe_ttm is not None else "dynamic",
                    is_valid=is_valid,
                    quality_flag=quality_flag,
                    quality_notes=quality_notes,
                    raw_payload_hash=payload_hash,
                )
            )
            previous_pb = pb
            previous_pe = pe_static or pe_ttm

        return ValuationSyncBatch(
            source_provider=self.provider_name,
            stock_code=stock_code,
            records=records,
        )


class AKShareValuationGateway(_BaseValuationGateway):
    """AKShare compatibility gateway backed by data_center valuation facts."""

    provider_name = "akshare"


class ConfiguredValuationGateway(_BaseValuationGateway):
    """Read canonical valuation facts for one database-configured provider."""

    def __init__(self, provider_name: str) -> None:
        normalized = provider_name.strip()
        if not normalized:
            raise ValueError("provider_name cannot be empty")
        self.provider_name = normalized
        super().__init__()


class TushareValuationGateway(_BaseValuationGateway):
    """Tushare compatibility gateway backed by data_center valuation facts."""

    provider_name = "tushare"

    def __init__(self, token: str, http_url: str | None = None) -> None:
        super().__init__()
        self.token = token
        self.http_url = http_url
