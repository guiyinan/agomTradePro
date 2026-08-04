"""Focused price-history query use cases for the Data Center application."""

from __future__ import annotations

from apps.data_center.application.dtos import PriceBarResponse, PriceHistoryRequest
from apps.data_center.domain.protocols import PriceBarRepositoryProtocol


class QueryPriceHistoryUseCase:
    """Fetch OHLCV price bars for a security."""

    def __init__(self, repo: PriceBarRepositoryProtocol) -> None:
        self._repo = repo

    def execute(self, request: PriceHistoryRequest) -> list[PriceBarResponse]:
        if request.fact_pks is None:
            bars = self._repo.get_bars(
                asset_code=request.asset_code,
                start=request.start,
                end=request.end,
                limit=request.limit,
            )
        else:
            bars = self._repo.get_bars(
                asset_code=request.asset_code,
                start=request.start,
                end=request.end,
                limit=request.limit,
                fact_pks=request.fact_pks,
            )
        return [
            PriceBarResponse(
                asset_code=b.asset_code,
                bar_date=b.bar_date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
                amount=b.amount,
                source=b.source,
            )
            for b in bars
        ]


__all__ = ["QueryPriceHistoryUseCase"]
