"""Typed published-close evidence used by simulated-trading previews."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID

from apps.account.application.market_price_contracts import MarketPriceResult
from apps.data_center.domain.publication_lanes import (
    M1_REBALANCE_REFERENCE_PUBLICATION_KEY as M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
)

ReferencePriceBasis = Literal["market", "published_close"]
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class PricePublicationReference:
    """Provenance for one close-price row selected from a sealed publication."""

    dataset_key: str
    publication_key: str
    publication_id: str
    publication_hash: str
    publication_run_id: str
    published_at: datetime
    publication_as_of: datetime
    knowledge_cutoff: datetime
    bar_date: date
    source_observed_at: datetime
    freshness_status: str

    def __post_init__(self) -> None:
        """Reject incomplete publication identity or unbounded source clocks."""

        for name in (
            "dataset_key",
            "publication_key",
            "publication_id",
            "publication_run_id",
            "freshness_status",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"PricePublicationReference.{name} is required")
        if self.dataset_key != "equity.price.bar":
            raise ValueError("PricePublicationReference.dataset_key is unsupported")
        if self.publication_key != M1_REBALANCE_REFERENCE_PUBLICATION_KEY:
            raise ValueError("PricePublicationReference.publication_key is unsupported")
        if _SHA256_RE.fullmatch(self.publication_hash) is None:
            raise ValueError("PricePublicationReference.publication_hash must be lowercase SHA-256")
        try:
            parsed_run_id = UUID(self.publication_run_id)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "PricePublicationReference.publication_run_id must be a UUID"
            ) from error
        if str(parsed_run_id) != self.publication_run_id.lower():
            raise ValueError("PricePublicationReference.publication_run_id must be canonical")
        for name in ("published_at", "publication_as_of", "knowledge_cutoff", "source_observed_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"PricePublicationReference.{name} must be timezone-aware")
        if type(self.bar_date) is not date:
            raise ValueError("PricePublicationReference.bar_date must be a date")
        if self.source_observed_at > self.publication_as_of:
            raise ValueError("PricePublicationReference observation exceeds publication boundary")
        if self.publication_as_of > self.published_at:
            raise ValueError("PricePublicationReference publication boundary follows publish time")
        if self.published_at > self.knowledge_cutoff:
            raise ValueError("PricePublicationReference was published after the knowledge cutoff")

    def to_payload(self) -> dict[str, str]:
        """Serialize exact publication provenance without introducing fallback clocks."""

        return {
            "dataset_key": self.dataset_key,
            "publication_key": self.publication_key,
            "publication_id": self.publication_id,
            "publication_hash": self.publication_hash,
            "publication_run_id": self.publication_run_id,
            "published_at": self.published_at.isoformat(),
            "publication_as_of": self.publication_as_of.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "bar_date": self.bar_date.isoformat(),
            "source_observed_at": self.source_observed_at.isoformat(),
            "freshness_status": self.freshness_status,
        }


@dataclass(frozen=True, slots=True)
class ReferenceCloseReadResult:
    """One validated close observation or a stable blocking reason."""

    price_result: MarketPriceResult | None
    publication: PricePublicationReference | None
    blocked_reason: str | None

    def __post_init__(self) -> None:
        """Keep incomplete evidence out of successful close results."""

        if self.price_result is None:
            if self.publication is not None or not self.blocked_reason:
                raise ValueError("blocked close results require only a stable blocking reason")
            return
        if self.publication is None or self.blocked_reason is not None:
            raise ValueError("usable close results require a publication reference")
        if type(self.publication) is not PricePublicationReference:
            raise TypeError("publication must be a PricePublicationReference")
        if type(self.price_result) is not MarketPriceResult:
            raise TypeError("price_result must be a MarketPriceResult")


class ReferenceClosePriceReader(Protocol):
    """Read one published close under the exact caller-supplied knowledge cutoff."""

    def read(self, *, asset_code: str, cutoff: datetime) -> ReferenceCloseReadResult:
        """Return one validated close or an explicit blocked result."""


__all__: tuple[str, ...] = (
    "M1_REBALANCE_REFERENCE_PUBLICATION_KEY",
    "PricePublicationReference",
    "ReferenceClosePriceReader",
    "ReferenceCloseReadResult",
    "ReferencePriceBasis",
)
