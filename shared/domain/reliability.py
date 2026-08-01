"""Canonical reliability metadata for data exposed as current or decision-ready."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ReliabilityStatus(str, Enum):
    """Supported reliability states for current-data surfaces."""

    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    PARTIAL = "partial"
    CONFLICT = "conflict"
    MAINTENANCE = "maintenance"
    FAILED = "failed"


@dataclass(frozen=True)
class ReliabilityContract:
    """Immutable source-time and decision-safety contract."""

    status: ReliabilityStatus
    observed_at: datetime | None
    fetched_at: datetime | None
    source: str
    must_not_use_for_decision: bool
    block_reason_code: str = ""
    block_reason: str = ""

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("ReliabilityContract.source cannot be empty")
        for field_name, value in (
            ("observed_at", self.observed_at),
            ("fetched_at", self.fetched_at),
        ):
            if value is not None and value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if (
            self.observed_at is not None
            and self.fetched_at is not None
            and self.fetched_at < self.observed_at
        ):
            raise ValueError("fetched_at cannot precede observed_at")
        if self.status is ReliabilityStatus.FRESH:
            if self.observed_at is None or self.fetched_at is None:
                raise ValueError("fresh reliability requires observed_at and fetched_at")
            if self.must_not_use_for_decision:
                raise ValueError("fresh reliability cannot block decision use")
        elif not self.must_not_use_for_decision:
            raise ValueError("non-fresh reliability must fail closed")
        if self.must_not_use_for_decision and (
            not self.block_reason_code.strip() or not self.block_reason.strip()
        ):
            raise ValueError("blocked reliability requires stable reason code and reason")

    @classmethod
    def fresh(
        cls,
        *,
        observed_at: datetime,
        fetched_at: datetime,
        source: str,
    ) -> ReliabilityContract:
        """Build a decision-usable contract from preserved source evidence."""

        return cls(
            status=ReliabilityStatus.FRESH,
            observed_at=observed_at,
            fetched_at=fetched_at,
            source=source,
            must_not_use_for_decision=False,
        )

    @classmethod
    def blocked(
        cls,
        *,
        status: ReliabilityStatus,
        source: str,
        reason_code: str,
        reason: str,
        observed_at: datetime | None = None,
        fetched_at: datetime | None = None,
    ) -> ReliabilityContract:
        """Build a fail-closed contract for unavailable or unsafe evidence."""

        if status is ReliabilityStatus.FRESH:
            raise ValueError("blocked reliability cannot use fresh status")
        return cls(
            status=status,
            observed_at=observed_at,
            fetched_at=fetched_at,
            source=source,
            must_not_use_for_decision=True,
            block_reason_code=reason_code,
            block_reason=reason,
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize the contract without replacing source timestamps."""

        return {
            "status": self.status.value,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "source": self.source,
            "freshness_status": self.status.value,
            "reliability_status": self.status.value,
            "is_reliable": not self.must_not_use_for_decision,
            "is_stale": self.status is ReliabilityStatus.STALE,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "block_reason_code": self.block_reason_code,
            "block_reason": self.block_reason,
        }
