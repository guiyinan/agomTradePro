"""Injected valuation selection and fallback orchestration."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Protocol

from ..domain.entities import ValuationSnapshot
from ..domain.rules import ValuationPayloadPolicy
from ..domain.services import ValuationSnapshotService

logger = logging.getLogger(__name__)

_SECURITY_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{0,19}$")
_MAX_PROVENANCE_LENGTH = 128


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
        normalized_code = self._normalize_security_code(security_code)
        if normalized_code is None:
            return None
        today = self._today_provider()
        try:
            formal = self._formal_source.get_payload(normalized_code)
            if formal and ValuationPayloadPolicy.is_usable(formal, today=today):
                return dict(formal)

            for snapshot_payload in self._snapshot_source.list_recent_payloads(normalized_code):
                if ValuationPayloadPolicy.is_usable(snapshot_payload, today=today):
                    return dict(snapshot_payload)

            start = today - timedelta(days=self.MAX_FORMAL_VALUATION_AGE_DAYS)
            for fact in self._fact_source.list_recent(normalized_code, start, today):
                fact_payload = ValuationPayloadPolicy.build_fact_payload(fact, today=today)
                if fact_payload is not None:
                    return fact_payload

            price, raw_source = self._market_price_source.get_latest(normalized_code)
            source = self._normalize_provenance(raw_source)
            if not self._is_positive_finite_price(price) or source is None:
                return None

            fallback = self._snapshot_source.get_today_fallback(normalized_code, today)
            if not self._matches_current_price(fallback, normalized_code, price, source):
                fallback = self._snapshot_service.create_current_price_fallback_snapshot(
                    security_code=normalized_code,
                    current_price=price,
                    source=source,
                )
                fallback = self._snapshot_source.save_fallback(fallback)
            if fallback is None or not self._is_valid_fallback(fallback, normalized_code):
                return None
            fallback_payload = ValuationPayloadPolicy.snapshot_to_payload(
                fallback,
                valuation_source="current_price_fallback",
            )
            return (
                fallback_payload
                if ValuationPayloadPolicy.has_positive_price_contract(fallback_payload)
                else None
            )
        except Exception as exc:
            logger.warning(
                "Failed to get valuation security_code=%s exception_type=%s",
                normalized_code,
                type(exc).__name__,
            )
            return None

    @staticmethod
    def _normalize_security_code(value: object) -> str | None:
        """Return a bounded canonical security code before any source I/O."""

        if not isinstance(value, str):
            return None
        normalized = value.strip().upper()
        return normalized if _SECURITY_CODE_PATTERN.fullmatch(normalized) else None

    @staticmethod
    def _normalize_provenance(value: object) -> str | None:
        """Return a bounded single-line source label safe for audit storage."""

        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > _MAX_PROVENANCE_LENGTH
            or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
        ):
            return None
        return normalized

    @staticmethod
    def _is_positive_finite_price(value: object) -> bool:
        """Return whether a market price is a positive finite Decimal."""

        return isinstance(value, Decimal) and value.is_finite() and value > Decimal("0")

    @classmethod
    def _is_valid_fallback(
        cls,
        snapshot: object,
        security_code: str,
    ) -> bool:
        """Validate a persisted fallback before it reaches recommendations."""

        if (
            not isinstance(snapshot, ValuationSnapshot)
            or snapshot.security_code != security_code
            or snapshot.valuation_method != "FALLBACK"
        ):
            return False
        return all(
            cls._is_positive_finite_price(price)
            for price in (
                snapshot.fair_value,
                snapshot.entry_price_low,
                snapshot.entry_price_high,
                snapshot.target_price_low,
                snapshot.target_price_high,
                snapshot.stop_loss_price,
            )
        )

    @classmethod
    def _matches_current_price(
        cls,
        snapshot: ValuationSnapshot | None,
        security_code: str,
        price: Decimal,
        source: str,
    ) -> bool:
        """Return whether a cached fallback matches a freshly validated observation."""

        if snapshot is None or not cls._is_valid_fallback(snapshot, security_code):
            return False
        stored_source = snapshot.input_parameters.get("source")
        return snapshot.fair_value == price and stored_source == source


__all__ = [
    "AssetValuationService",
    "FormalValuationSource",
    "MarketPriceSource",
    "SnapshotSource",
    "ValuationFactSource",
]
