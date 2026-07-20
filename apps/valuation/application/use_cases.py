"""Injected valuation selection and fallback orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Protocol

from ..domain.entities import ValuationSnapshot
from ..domain.rules import ValuationPayloadPolicy
from ..domain.services import ValuationSnapshotService

logger = logging.getLogger(__name__)


class FormalValuationSource(Protocol):
    """Port for a formal valuation source."""

    def get_payload(self, security_code: str) -> dict[str, Any] | None:
        """Return the latest formal valuation payload."""


class SnapshotSource(Protocol):
    """Port for persisted valuation snapshots."""

    def list_recent_payloads(self, security_code: str) -> list[dict[str, Any]]:
        """Return recent snapshot payloads newest first."""

    def get_today_fallback(
        self,
        security_code: str,
        today: date,
    ) -> ValuationSnapshot | None:
        """Return today's reusable fallback snapshot."""

    def save_fallback(self, snapshot: ValuationSnapshot) -> ValuationSnapshot:
        """Persist and return a fallback snapshot."""


class ValuationFactSource(Protocol):
    """Port for canonical data-center valuation facts."""

    def list_recent(
        self,
        security_code: str,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        """Return normalized valuation fact records."""


class MarketPriceSource(Protocol):
    """Port for the latest observable market price."""

    def get_latest(self, security_code: str) -> tuple[Decimal, str]:
        """Return price and stable provenance label."""


class AssetValuationService:
    """Select the best valuation contract through injected source ports."""

    MAX_FORMAL_VALUATION_AGE_DAYS = ValuationPayloadPolicy.MAX_FORMAL_VALUATION_AGE_DAYS

    def __init__(
        self,
        *,
        formal_source: FormalValuationSource,
        snapshot_source: SnapshotSource,
        fact_source: ValuationFactSource,
        market_price_source: MarketPriceSource,
        today_provider: Callable[[], date] = date.today,
    ) -> None:
        self._formal_source = formal_source
        self._snapshot_source = snapshot_source
        self._fact_source = fact_source
        self._market_price_source = market_price_source
        self._today_provider = today_provider
        self._snapshot_service = ValuationSnapshotService()

    def get_valuation(self, security_code: str) -> dict[str, Any] | None:
        """Return the freshest reliable valuation or an explicit price fallback."""
        today = self._today_provider()
        try:
            formal = self._formal_source.get_payload(security_code)
            if formal and ValuationPayloadPolicy.is_usable(formal, today=today):
                return formal

            for payload in self._snapshot_source.list_recent_payloads(security_code):
                if ValuationPayloadPolicy.is_usable(payload, today=today):
                    return payload

            start = today - timedelta(days=self.MAX_FORMAL_VALUATION_AGE_DAYS)
            for fact in self._fact_source.list_recent(security_code, start, today):
                payload = ValuationPayloadPolicy.build_fact_payload(fact, today=today)
                if payload is not None:
                    return payload

            fallback = self._snapshot_source.get_today_fallback(security_code, today)
            if fallback is None:
                price, source = self._market_price_source.get_latest(security_code)
                if price <= 0:
                    return None
                fallback = self._snapshot_service.create_current_price_fallback_snapshot(
                    security_code=security_code,
                    current_price=price,
                    source=source,
                )
                fallback = self._snapshot_source.save_fallback(fallback)
            payload = ValuationPayloadPolicy.snapshot_to_payload(
                fallback,
                valuation_source="current_price_fallback",
            )
            return payload if ValuationPayloadPolicy.has_positive_price_contract(payload) else None
        except Exception as exc:
            logger.warning("Failed to get valuation for %s: %s", security_code, exc)
            return None


__all__ = [
    "AssetValuationService",
    "FormalValuationSource",
    "MarketPriceSource",
    "SnapshotSource",
    "ValuationFactSource",
]
