"""Canonical owner identities for R5 post-promotion monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class R5MonitoringOwnerRole(StrEnum):
    """Closed owner-role vocabulary for the R5 monitoring graph."""

    CALENDAR = "calendar"
    BENCHMARK = "benchmark"
    COST_POLICY = "cost_policy"
    LIQUIDITY_POLICY = "liquidity_policy"
    LABEL_BASELINE = "label_baseline"
    DATA_SCHEMA = "data_schema"
    PORTFOLIO_MONITORING_SOURCE = "portfolio_monitoring_source"


_ROLE_OWNER: dict[R5MonitoringOwnerRole, str] = {
    R5MonitoringOwnerRole.CALENDAR: "research",
    R5MonitoringOwnerRole.BENCHMARK: "research",
    R5MonitoringOwnerRole.COST_POLICY: "portfolio",
    R5MonitoringOwnerRole.LIQUIDITY_POLICY: "portfolio",
    R5MonitoringOwnerRole.LABEL_BASELINE: "research",
    R5MonitoringOwnerRole.DATA_SCHEMA: "fixed_income",
    R5MonitoringOwnerRole.PORTFOLIO_MONITORING_SOURCE: "portfolio",
}


def _require_token(value: object, label: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be an exact bounded token")


def _require_hash(value: object, label: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _require_aware(value: object, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")


@dataclass(frozen=True)
class R5MonitoringOwnerRef:
    """Exact owner projection, role, and point-in-time knowledge clocks."""

    role: R5MonitoringOwnerRole
    owner: str
    owner_id: str
    owner_version: str
    content_hash: str
    known_at: datetime
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if type(self.role) is not R5MonitoringOwnerRole:
            raise TypeError("owner ref role must be canonical")
        _require_token(self.owner, "owner ref owner")
        if self.owner != _ROLE_OWNER[self.role]:
            raise ValueError("owner ref role has a non-canonical owner")
        _require_token(self.owner_id, "owner ref id")
        _require_token(self.owner_version, "owner ref version")
        _require_hash(self.content_hash, "owner ref content_hash")
        _require_aware(self.known_at, "owner ref known_at")
        _require_aware(self.recorded_at, "owner ref recorded_at")
        _require_aware(self.valid_until, "owner ref valid_until")
        if not self.known_at <= self.recorded_at < self.valid_until:
            raise ValueError("owner ref clocks are invalid")

    def validated_copy(self) -> R5MonitoringOwnerRef:
        """Return an independently revalidated owner projection."""

        return R5MonitoringOwnerRef(
            role=self.role,
            owner=self.owner,
            owner_id=self.owner_id,
            owner_version=self.owner_version,
            content_hash=self.content_hash,
            known_at=self.known_at,
            recorded_at=self.recorded_at,
            valid_until=self.valid_until,
        )


__all__ = ["R5MonitoringOwnerRef", "R5MonitoringOwnerRole"]
