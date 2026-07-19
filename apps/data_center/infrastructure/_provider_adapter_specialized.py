"""Unified provider adapters for Data Center Phase 3.

These adapters wrap existing module-specific gateways/adapters and expose
standardized data_center domain entities only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from time import perf_counter
from typing import Any, TypeVar

import requests

from apps.data_center.domain.entities import (
    MacroFact,
    PriceBar,
    ProviderConfig,
    QuoteSnapshot,
)
from apps.data_center.domain.enums import (
    DataQualityStatus,
)
from apps.data_center.domain.protocols import UnifiedDataProviderProtocol
from apps.data_center.domain.rules import normalize_asset_code
from apps.data_center.infrastructure._provider_adapter_akshare import AkshareUnifiedProviderAdapter
from apps.data_center.infrastructure._provider_adapter_base import (
    _FRED_SERIES_MAP,
    BaseUnifiedProviderAdapter,
    _ensure_aware,
)
from apps.data_center.infrastructure._provider_adapter_tushare import TushareUnifiedProviderAdapter
from shared.numeric import safe_float

logger = logging.getLogger(__name__)
_ResultT = TypeVar("_ResultT")


class EastMoneyUnifiedProviderAdapter(AkshareUnifiedProviderAdapter):
    """EastMoney provider is implemented via the dedicated EastMoney gateway."""


class QmtUnifiedProviderAdapter(BaseUnifiedProviderAdapter):
    """Standardized QMT provider wrapper."""

    def _gateway(self) -> Any:
        from apps.data_center.infrastructure.gateways.qmt_gateway import QMTGateway

        return QMTGateway(
            source_name=self.provider_name(),
            extra_config=self._config.extra_config,
        )

    def fetch_price_history(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[PriceBar]:
        canonical_asset_code = normalize_asset_code(asset_code, "qmt")
        bars = self._gateway().get_historical_prices(
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
                source=self.provider_source(),
            )
            for bar in bars
        ]

    def fetch_quote_snapshots(self, asset_codes: list[str]) -> list[QuoteSnapshot]:
        quotes = self._gateway().get_quote_snapshots(asset_codes)
        return [
            QuoteSnapshot(
                asset_code=normalize_asset_code(quote.stock_code, "qmt"),
                snapshot_at=_ensure_aware(getattr(quote, "fetched_at", None)),
                current_price=float(quote.price),
                source=self.provider_source(),
                open=safe_float(quote.open),
                high=safe_float(quote.high),
                low=safe_float(quote.low),
                prev_close=safe_float(quote.pre_close),
                volume=float(quote.volume) if quote.volume is not None else None,
                amount=safe_float(quote.amount),
                extra=self._provider_extra(),
            )
            for quote in quotes
        ]


class FredUnifiedProviderAdapter(BaseUnifiedProviderAdapter):
    """Minimal FRED macro adapter using the official HTTP API."""

    def fetch_macro_series(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]:
        if indicator_code not in _FRED_SERIES_MAP:
            return []

        series_id, unit, _period_type = _FRED_SERIES_MAP[indicator_code]
        response = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "api_key": self._config.api_key,
                "file_type": "json",
                "observation_start": start_date.isoformat(),
                "observation_end": end_date.isoformat(),
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()

        facts: list[MacroFact] = []
        for row in payload.get("observations", []):
            value = row.get("value")
            if value in (None, ".", ""):
                continue
            facts.append(
                MacroFact(
                    indicator_code=indicator_code,
                    reporting_period=date.fromisoformat(row["date"]),
                    value=float(value),
                    unit=unit,
                    source=self.provider_source(),
                    published_at=date.fromisoformat(row["date"]),
                    quality=DataQualityStatus.VALID,
                    extra=self._provider_extra({"original_unit": unit}),
                )
            )
        return facts


def build_unified_provider_adapter(config: ProviderConfig) -> UnifiedDataProviderProtocol:
    """Create a standardized provider adapter from config."""

    mapping = {
        "tushare": TushareUnifiedProviderAdapter,
        "akshare": AkshareUnifiedProviderAdapter,
        "eastmoney": EastMoneyUnifiedProviderAdapter,
        "qmt": QmtUnifiedProviderAdapter,
        "fred": FredUnifiedProviderAdapter,
    }
    adapter_cls = mapping.get(config.source_type)
    if adapter_cls is None:
        raise ValueError(f"Unsupported provider source_type: {config.source_type}")
    return adapter_cls(config)


def time_adapter_call(
    fn: Callable[..., _ResultT], *args: Any, **kwargs: Any
) -> tuple[_ResultT, float]:
    """Run a provider call and return (result, latency_ms)."""

    started = perf_counter()
    result = fn(*args, **kwargs)
    return result, (perf_counter() - started) * 1000
