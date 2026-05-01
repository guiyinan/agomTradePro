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

from apps.data_center.application.repository_provider import get_valuation_fact_repository
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
            rows = [row for row in rows if self.provider_name in (row.source or "").lower()]
        previous_pb: float | None = None
        previous_pe: float | None = None
        records: list[ValuationMetrics] = []

        for row in rows:
            pb = float(row.pb) if row.pb is not None else None
            pe_static = float(row.pe_static) if row.pe_static is not None else None
            pe_ttm = float(row.pe_ttm) if row.pe_ttm is not None else None
            ps_ttm = float(row.ps_ttm) if row.ps_ttm is not None else 0.0
            dv_ratio = float(row.dv_ratio) if row.dv_ratio is not None else 0.0
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
                    pe=pe_ttm or pe_static or 0.0,
                    pb=pb or 0.0,
                    ps=ps_ttm,
                    total_mv=Decimal(str(row.market_cap or 0)),
                    circ_mv=Decimal(str(row.float_market_cap or row.market_cap or 0)),
                    dividend_yield=dv_ratio,
                    source_provider=row.source,
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


class TushareValuationGateway(_BaseValuationGateway):
    """Tushare compatibility gateway backed by data_center valuation facts."""

    provider_name = "tushare"

    def __init__(self, token: str, http_url: str | None = None):
        super().__init__()
        self.token = token
        self.http_url = http_url
