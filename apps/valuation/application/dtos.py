"""Valuation application DTOs."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class MarketPrice:
    """Latest observable market price with provenance."""

    amount: Decimal
    source: str
