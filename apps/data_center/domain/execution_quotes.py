"""Exact publication-bound quote values for execution-facing consumers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from apps.data_center.domain.contracts import MAX_CATALOG_TTL_SECONDS

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}")
CURRENT_ACTIVE_CONTRACT_RESOLUTION: Final[str] = "current_active_not_point_in_time"


@dataclass(frozen=True, slots=True)
class ExecutionQuoteSnapshot:
    """One exact quote fact bound to its execution publication and TTL.

    A ``None`` bid or ask means that the source supplied no value. It does not
    prove that the market has no bid or offer. Contract resolution is explicitly
    the current active catalog row; ``queried_at`` does not make that lookup PIT.
    """

    asset_code: str
    last: Decimal
    bid: Decimal | None
    ask: Decimal | None
    previous_close: Decimal | None
    snapshot_at: datetime
    fetched_at: datetime
    fact_pk: str
    fact_content_hash: str
    publication_id: str
    publication_hash: str
    publication_as_of: datetime
    published_at: datetime
    freshness_deadline: datetime
    queried_at: datetime
    policy_identity: str
    source: str
    quality_status: str
    dataset_key: str
    contract_version: str
    schema_version: str
    contract_resolution: str
    execution_freshness_seconds: int

    def __post_init__(self) -> None:
        """Validate the exact values and chronology before crossing the boundary."""

        self.validate()

    def validate(self) -> None:
        """Reject malformed prices, identities, digests, and future evidence."""

        self.validate_structure()

        if self.snapshot_at > self.fetched_at:
            raise ValueError("Execution quote observation cannot follow its fetch time")
        if self.snapshot_at > self.publication_as_of:
            raise ValueError("Execution quote observation exceeds the publication boundary")
        if self.publication_as_of > self.published_at:
            raise ValueError("Execution quote publication boundary follows publication time")
        if self.fetched_at > self.published_at:
            raise ValueError("Execution quote fetch time follows publication time")
        if any(
            value > self.queried_at
            for value in (
                self.snapshot_at,
                self.fetched_at,
                self.publication_as_of,
                self.published_at,
            )
        ):
            raise ValueError("Execution quote evidence is after the requested knowledge cutoff")
        if self.freshness_deadline <= self.snapshot_at:
            raise ValueError("Execution quote freshness deadline must follow the observation")
        try:
            expected_deadline = self.snapshot_at + timedelta(
                seconds=self.execution_freshness_seconds
            )
        except OverflowError:
            raise ValueError("Execution quote freshness deadline overflows") from None
        if self.freshness_deadline != expected_deadline:
            raise ValueError("Execution quote deadline does not match its catalog TTL")
        if self.queried_at >= self.freshness_deadline:
            raise ValueError("Execution quote has expired its source freshness window")

    def validate_structure(self) -> None:
        """Validate field types and values before callers compare timestamps."""

        for field_name in (
            "asset_code",
            "fact_pk",
            "publication_id",
            "policy_identity",
            "source",
            "quality_status",
            "dataset_key",
            "contract_version",
            "schema_version",
            "contract_resolution",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"ExecutionQuoteSnapshot.{field_name} is required")
        if type(self.execution_freshness_seconds) is not int or (
            self.execution_freshness_seconds <= 0
            or self.execution_freshness_seconds > MAX_CATALOG_TTL_SECONDS
        ):
            raise ValueError(
                "Execution quote execution_freshness_seconds must fit a positive 64-bit integer"
            )
        if self.contract_resolution != CURRENT_ACTIVE_CONTRACT_RESOLUTION:
            raise ValueError("Execution quote contract resolution must identify current catalog")
        for field_name, value in (
            ("fact_content_hash", self.fact_content_hash),
            ("publication_hash", self.publication_hash),
        ):
            if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
                raise ValueError(f"ExecutionQuoteSnapshot.{field_name} must be lowercase SHA-256")

        _require_price(self.last, "last", required=True)
        _require_price(self.bid, "bid", required=False)
        _require_price(self.ask, "ask", required=False)
        _require_price(self.previous_close, "previous_close", required=False)

        for field_name in (
            "snapshot_at",
            "fetched_at",
            "publication_as_of",
            "published_at",
            "freshness_deadline",
            "queried_at",
        ):
            _require_aware(getattr(self, field_name), field_name)


def _require_price(value: Decimal | None, field_name: str, *, required: bool) -> None:
    """Require an exact positive finite Decimal where the source supplied one."""

    if value is None:
        if required:
            raise ValueError(f"ExecutionQuoteSnapshot.{field_name} is required")
        return
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"ExecutionQuoteSnapshot.{field_name} must be a positive finite Decimal")


def _require_aware(value: datetime, field_name: str) -> None:
    """Require one timezone-aware source or knowledge timestamp."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"ExecutionQuoteSnapshot.{field_name} must be timezone-aware")


__all__ = ["CURRENT_ACTIVE_CONTRACT_RESOLUTION", "ExecutionQuoteSnapshot"]
