"""Adapters for formal valuations, valuation facts, and observable prices."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from importlib import import_module
from typing import Any, Protocol, cast

from apps.data_center.application.price_service import (
    PriceLookupResult,
    UnifiedPriceService,
)
from apps.data_center.application.public import get_valuation_fact_repository_port
from core.exceptions import DataFetchError

from ..domain.rules import ValuationPayloadPolicy

logger = logging.getLogger(__name__)


class _LegacyValuationServiceProtocol(Protocol):
    """Optional legacy valuation service boundary."""

    def get_latest_valuation(self, security_code: str) -> object | None: ...


class _CanonicalPriceServiceProtocol(Protocol):
    """Decision-safe latest-price boundary owned by data_center."""

    def require_latest_price_result(
        self,
        asset_code: str,
        asset_type: str | None = None,
    ) -> PriceLookupResult:
        """Return a freshness-validated canonical price result."""


class AssetAnalysisValuationSource:
    """Adapt asset-analysis valuation results to the canonical payload."""

    def __init__(self) -> None:
        self._service: _LegacyValuationServiceProtocol | None = None

    def get_payload(self, security_code: str) -> dict[str, Any] | None:
        """Return the latest asset-analysis valuation when available."""
        if self._service is None:
            try:
                services_module = import_module("apps.asset_analysis.application.services")
                service_class = vars(services_module).get("ValuationService")
                if not callable(service_class):
                    return None
                self._service = cast(_LegacyValuationServiceProtocol, service_class())
            except (AttributeError, ImportError, TypeError):
                return None
        try:
            valuation = self._service.get_latest_valuation(security_code)
        except Exception as exc:
            logger.debug(
                "Legacy formal valuation lookup failed for %s: error_type=%s",
                security_code,
                exc.__class__.__name__,
            )
            return None
        if valuation is None:
            return None
        return {
            "fair_value": getattr(valuation, "fair_value", 0),
            "entry_price_low": getattr(valuation, "entry_price_low", 0),
            "entry_price_high": getattr(valuation, "entry_price_high", 0),
            "target_price_low": getattr(valuation, "target_price_low", 0),
            "target_price_high": getattr(valuation, "target_price_high", 0),
            "stop_loss_price": getattr(valuation, "stop_loss_price", 0),
            "valuation_date": self._first_present_attr(
                valuation,
                (
                    "valuation_date",
                    "as_of_date",
                    "trade_date",
                    "calculated_at",
                    "fetched_at",
                ),
            ),
            "is_valid": getattr(valuation, "is_valid", True),
            "quality_flag": getattr(valuation, "quality_flag", "ok"),
            "is_legacy": getattr(valuation, "is_legacy", False),
            "valuation_source": "asset_analysis",
        }

    @staticmethod
    def _first_present_attr(source: Any, names: tuple[str, ...]) -> Any:
        for name in names:
            value = getattr(source, name, None)
            if value is not None:
                return value
        return None


class DataCenterValuationFactSource:
    """Read canonical valuation facts from data_center."""

    def list_recent(
        self,
        security_code: str,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        """Return normalized recent facts, newest first when supported."""
        try:
            repository = get_valuation_fact_repository_port()
            get_series = getattr(repository, "get_series", None)
            facts = (
                get_series(security_code, start=start, end=end) if callable(get_series) else None
            )
            if not isinstance(facts, list):
                latest = repository.get_latest(security_code)
                facts = [latest] if latest is not None else []
            return [self._normalize(fact) for fact in facts]
        except Exception as exc:
            logger.debug(
                "Data center valuation fact lookup failed for %s: error_type=%s",
                security_code,
                exc.__class__.__name__,
            )
            return []

    @staticmethod
    def _normalize(fact: Any) -> dict[str, Any]:
        fact_date = getattr(fact, "val_date", None)
        return {
            "valuation_fact_date": fact_date.isoformat() if fact_date else None,
            "fetched_at": getattr(fact, "fetched_at", None),
            "extra": getattr(fact, "extra", None) or {},
        }


class ObservableMarketPriceSource:
    """Adapt the canonical decision-safe price result for valuation."""

    def __init__(
        self,
        price_service: _CanonicalPriceServiceProtocol | None = None,
    ) -> None:
        self._price_service = price_service or UnifiedPriceService()

    def get_latest(self, security_code: str) -> tuple[Decimal, str]:
        """Return a freshness-validated positive price and provenance label."""
        try:
            result = self._price_service.require_latest_price_result(security_code)
        except (DataFetchError, ValueError) as exc:
            logger.debug(
                "Canonical market price unavailable for %s: error_type=%s",
                security_code,
                exc.__class__.__name__,
            )
            return Decimal("0"), "unavailable"

        price = ValuationPayloadPolicy.to_decimal(result.price)
        source = result.source.strip()
        freshness = result.freshness.strip()
        if (
            not price.is_finite()
            or price <= Decimal("0")
            or not source
            or freshness not in {"realtime", "close_fallback"}
        ):
            return Decimal("0"), "unavailable"
        return price, f"{source}:{freshness}"
