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
from apps.data_center.application.public import get_published_valuation_facts
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
            "fair_value": getattr(valuation, "fair_value", None),
            "entry_price_low": getattr(valuation, "entry_price_low", None),
            "entry_price_high": getattr(valuation, "entry_price_high", None),
            "target_price_low": getattr(valuation, "target_price_low", None),
            "target_price_high": getattr(valuation, "target_price_high", None),
            "stop_loss_price": getattr(valuation, "stop_loss_price", None),
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
        """Return normalized recent facts only after the current publication gate."""
        try:
            payload = get_published_valuation_facts(
                security_code,
                as_of=end,
                limit=None,
            )
            if bool(payload.get("must_not_use_for_decision")):
                return []
            rows = payload.get("rows", [])
            if not isinstance(rows, list):
                return []
            return [
                self._normalize(fact)
                for fact in rows
                if isinstance(fact, dict) and self._within_window(fact, start=start, end=end)
            ]
        except Exception as exc:
            logger.debug(
                "Data center valuation fact lookup failed for %s: error_type=%s",
                security_code,
                exc.__class__.__name__,
            )
            return []

    @staticmethod
    def _normalize(fact: Any) -> dict[str, Any]:
        if isinstance(fact, dict):
            fact_date = fact.get("val_date")
            fetched_at = fact.get("fetched_at")
            extra = fact.get("extra") or {}
        else:
            fact_date = getattr(fact, "val_date", None)
            fetched_at = getattr(fact, "fetched_at", None)
            extra = getattr(fact, "extra", None) or {}
        return {
            "valuation_fact_date": (
                fact_date.isoformat() if isinstance(fact_date, date) else fact_date
            ),
            "fetched_at": fetched_at,
            "extra": extra,
        }

    @staticmethod
    def _within_window(fact: dict[str, Any], *, start: date, end: date) -> bool:
        """Keep only valuation observations inside the requested as-of window."""

        raw_date = fact.get("val_date")
        if isinstance(raw_date, date):
            fact_date = raw_date
        elif isinstance(raw_date, str):
            try:
                fact_date = date.fromisoformat(raw_date[:10])
            except ValueError:
                return False
        else:
            return False
        return start <= fact_date <= end


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
