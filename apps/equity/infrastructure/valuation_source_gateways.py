"""
估值数据外部来源网关。

本期提供：
- AKShare 主源：基于百度股市通估值序列
- Tushare 备源：基于 daily_basic
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import List, Optional

from apps.equity.domain.entities import ValuationMetrics
from apps.equity.infrastructure.repositories import compute_valuation_quality_flag

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValuationSyncBatch:
    source_provider: str
    stock_code: str
    records: List[ValuationMetrics]


class AKShareValuationGateway:
    """AKShare 主源网关。"""

    _IND_TOTAL_MV = "\u603b\u5e02\u503c"
    _IND_PE_TTM = "\u5e02\u76c8\u7387(TTM)"
    _IND_PB = "\u5e02\u51c0\u7387"

    def fetch(self, stock_code: str, start_date: date, end_date: date) -> ValuationSyncBatch:
        import akshare as ak
        import pandas as pd

        symbol = self._to_akshare_symbol(stock_code)
        period = self._to_period(start_date, end_date)

        total_mv_df = ak.stock_zh_valuation_baidu(symbol=symbol, indicator=self._IND_TOTAL_MV, period=period)
        pe_ttm_df = ak.stock_zh_valuation_baidu(symbol=symbol, indicator=self._IND_PE_TTM, period=period)
        pb_df = ak.stock_zh_valuation_baidu(symbol=symbol, indicator=self._IND_PB, period=period)

        merged = self._merge_frames(total_mv_df, pe_ttm_df, pb_df, start_date, end_date)
        records = self._to_metrics(stock_code, merged)
        return ValuationSyncBatch(source_provider="akshare", stock_code=stock_code, records=records)

    def _merge_frames(self, total_mv_df, pe_ttm_df, pb_df, start_date: date, end_date: date):
        import pandas as pd

        total_mv_df = total_mv_df.rename(columns={"date": "trade_date", "value": "total_mv"})
        pe_ttm_df = pe_ttm_df.rename(columns={"date": "trade_date", "value": "pe_ttm"})
        pb_df = pb_df.rename(columns={"date": "trade_date", "value": "pb"})

        merged = total_mv_df.merge(pe_ttm_df, on="trade_date", how="outer").merge(pb_df, on="trade_date", how="outer")
        merged["trade_date"] = pd.to_datetime(merged["trade_date"]).dt.date
        merged = merged[(merged["trade_date"] >= start_date) & (merged["trade_date"] <= end_date)]
        merged = merged.sort_values("trade_date")
        return merged

    def _to_metrics(self, stock_code: str, merged) -> List[ValuationMetrics]:
        records: List[ValuationMetrics] = []
        previous_pb: Optional[float] = None
        previous_pe: Optional[float] = None

        for row in merged.itertuples(index=False):
            pb = float(row.pb) if row.pb == row.pb else None
            pe_ttm = float(row.pe_ttm) if row.pe_ttm == row.pe_ttm else None
            total_mv_raw = float(row.total_mv) if row.total_mv == row.total_mv else 0.0

            is_valid, quality_flag, quality_notes = compute_valuation_quality_flag(
                pb=pb,
                pe=None,
                previous_pb=previous_pb,
                previous_pe=previous_pe,
            )

            payload = {
                "stock_code": stock_code,
                "trade_date": row.trade_date.isoformat(),
                "pb": pb,
                "pe_ttm": pe_ttm,
                "total_mv": total_mv_raw,
                "source": "akshare",
            }
            payload_hash = hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
            ).hexdigest()

            records.append(
                ValuationMetrics(
                    stock_code=stock_code,
                    trade_date=row.trade_date,
                    pe=pe_ttm or 0.0,
                    pb=pb or 0.0,
                    ps=0.0,
                    total_mv=Decimal(str(total_mv_raw * 100000000)),
                    circ_mv=Decimal(str(total_mv_raw * 100000000)),
                    dividend_yield=0.0,
                    source_provider="akshare",
                    source_updated_at=datetime.combine(row.trade_date, time(15, 0)),
                    pe_type="ttm",
                    is_valid=is_valid,
                    quality_flag=quality_flag,
                    quality_notes=quality_notes,
                    raw_payload_hash=payload_hash,
                )
            )
            previous_pb = pb
            previous_pe = pe_ttm

        return records

    def _to_akshare_symbol(self, stock_code: str) -> str:
        return stock_code.split(".")[0]

    def _to_period(self, start_date: date, end_date: date) -> str:
        span_days = max((end_date - start_date).days, 1)
        if span_days <= 366:
            return "\u8fd1\u4e00\u5e74"
        if span_days <= 366 * 3:
            return "\u8fd1\u4e09\u5e74"
        if span_days <= 366 * 5:
            return "\u8fd1\u4e94\u5e74"
        return "\u5168\u90e8"


class TushareValuationGateway:
    """Tushare 备源网关。"""

    def __init__(self, token: str):
        self.token = token

    def fetch(self, stock_code: str, start_date: date, end_date: date) -> ValuationSyncBatch:
        import pandas as pd
        import tushare as ts

        pro = ts.pro_api(self.token)
        df = pro.daily_basic(
            ts_code=stock_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            fields="ts_code,trade_date,pe,pe_ttm,pb,ps,dv_ratio,total_mv,circ_mv",
        )

        if df is None or df.empty:
            return ValuationSyncBatch(source_provider="tushare", stock_code=stock_code, records=[])

        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df = df.sort_values("trade_date")
        records: List[ValuationMetrics] = []
        previous_pb: Optional[float] = None
        previous_pe: Optional[float] = None

        for row in df.itertuples(index=False):
            pb = float(row.pb) if row.pb == row.pb else None
            pe = float(row.pe) if row.pe == row.pe else None
            pe_ttm = float(row.pe_ttm) if row.pe_ttm == row.pe_ttm else None
            ps = float(row.ps) if row.ps == row.ps else 0.0
            dividend_yield = float(row.dv_ratio) if row.dv_ratio == row.dv_ratio else 0.0
            is_valid, quality_flag, quality_notes = compute_valuation_quality_flag(
                pb=pb,
                pe=pe,
                previous_pb=previous_pb,
                previous_pe=previous_pe,
            )

            payload = {
                "stock_code": stock_code,
                "trade_date": row.trade_date.isoformat(),
                "pe": pe,
                "pe_ttm": pe_ttm,
                "pb": pb,
                "ps": ps,
                "source": "tushare",
            }
            payload_hash = hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
            ).hexdigest()

            records.append(
                ValuationMetrics(
                    stock_code=stock_code,
                    trade_date=row.trade_date,
                    pe=pe or 0.0,
                    pb=pb or 0.0,
                    ps=ps,
                    total_mv=Decimal(str(float(row.total_mv or 0.0) * 10000)),
                    circ_mv=Decimal(str(float(row.circ_mv or 0.0) * 10000)),
                    dividend_yield=dividend_yield,
                    source_provider="tushare",
                    source_updated_at=datetime.combine(row.trade_date, time(15, 0)),
                    pe_type="dynamic",
                    is_valid=is_valid,
                    quality_flag=quality_flag,
                    quality_notes=quality_notes,
                    raw_payload_hash=payload_hash,
                )
            )
            previous_pb = pb
            previous_pe = pe

        return ValuationSyncBatch(source_provider="tushare", stock_code=stock_code, records=records)
