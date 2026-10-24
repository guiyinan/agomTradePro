"""Real-time quote snapshot domain entity."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.data_center.domain.quote_change_pct import (
    QuoteChangePctCandidate as QuoteChangePctCandidate,
)
from apps.data_center.domain.quote_change_pct import (
    QuoteChangePctEvidence as QuoteChangePctEvidence,
)


@dataclass(frozen=True)
class QuoteSnapshot:
    """Real-time / intraday quote for a tradable asset."""

    asset_code: str
    snapshot_at: datetime
    current_price: float
    source: str
    fetched_at: datetime | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    volume: float | None = None
    amount: float | None = None
    bid: float | None = None
    ask: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    ingested_run_id: str = ""
    change_pct: Decimal | None = None
    change_pct_candidate: QuoteChangePctCandidate | None = None
    change_pct_evidence: QuoteChangePctEvidence | None = None
    contract_version: str | None = None
    schema_version: str | None = None

    def __post_init__(self) -> None:
        if not self.asset_code:
            raise ValueError("QuoteSnapshot.asset_code cannot be empty")
        if (
            isinstance(self.current_price, bool)
            or not math.isfinite(self.current_price)
            or self.current_price <= 0
        ):
            raise ValueError(
                "QuoteSnapshot.current_price must be positive and finite: " f"{self.current_price}"
            )
        if self.snapshot_at.utcoffset() is None:
            raise ValueError("QuoteSnapshot.snapshot_at must be timezone-aware")
        if self.change_pct is None:
            if self.change_pct_evidence is not None:
                raise ValueError("QuoteSnapshot metric evidence requires change_pct")
        else:
            if (
                not isinstance(self.change_pct, Decimal)
                or not self.change_pct.is_finite()
                or self.change_pct_evidence is None
            ):
                raise ValueError("QuoteSnapshot change_pct requires finite value and evidence")
            if self.change_pct_evidence.metric_value != self.change_pct:
                raise ValueError("QuoteSnapshot change_pct differs from its evidence value")
            if self.change_pct_evidence.observed_at != self.snapshot_at:
                raise ValueError("QuoteSnapshot change_pct evidence must use snapshot_at")
            if self.change_pct_evidence.quote_source != self.source:
                raise ValueError("QuoteSnapshot change_pct evidence quote source mismatch")
            if self.change_pct_evidence.dataset_contract_key != "equity.quote.snapshot":
                raise ValueError("QuoteSnapshot metric evidence dataset key mismatch")
            if (
                self.contract_version != self.change_pct_evidence.dataset_contract_version
                or self.schema_version != self.change_pct_evidence.dataset_schema_version
            ):
                raise ValueError("QuoteSnapshot version differs from metric contract evidence")
        if (self.contract_version is None) != (self.schema_version is None):
            raise ValueError("QuoteSnapshot contract and schema versions must be set together")
        if self.contract_version is not None and (
            not self.contract_version.strip()
            or self.schema_version is None
            or not self.schema_version.strip()
        ):
            raise ValueError("QuoteSnapshot contract and schema versions must be explicit")
        if self.fetched_at is not None:
            if self.fetched_at.utcoffset() is None:
                raise ValueError("QuoteSnapshot.fetched_at must be timezone-aware")
            if self.fetched_at < self.snapshot_at:
                raise ValueError("QuoteSnapshot.fetched_at cannot precede snapshot_at")
        if self.ingested_run_id:
            try:
                parsed_run_id = UUID(self.ingested_run_id)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "QuoteSnapshot.ingested_run_id must be a canonical UUID"
                ) from error
            if str(parsed_run_id) != self.ingested_run_id.lower():
                raise ValueError("QuoteSnapshot.ingested_run_id must be a canonical UUID")

    def to_dict(self) -> dict[str, Any]:
        """Serialize the quote and any source-bound metric evidence."""

        return {
            "asset_code": self.asset_code,
            "snapshot_at": self.snapshot_at.isoformat(),
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "current_price": self.current_price,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "prev_close": self.prev_close,
            "volume": self.volume,
            "amount": self.amount,
            "bid": self.bid,
            "ask": self.ask,
            "change_pct": format(self.change_pct, "f") if self.change_pct is not None else None,
            "change_pct_source_contract": (
                self.change_pct_evidence.to_dict() if self.change_pct_evidence is not None else None
            ),
            "contract_version": self.contract_version,
            "schema_version": self.schema_version,
            "source": self.source,
            "extra": self.extra,
            "ingested_run_id": self.ingested_run_id,
        }
