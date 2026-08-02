"""Dataset retention, legal/operational holds and archive manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class ArchiveState(str, Enum):
    """Lifecycle of an archive manifest."""

    PLANNED = "planned"
    EXPORTED = "exported"
    VERIFIED = "verified"
    DELETED = "deleted"
    FAILED = "failed"


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class RetentionPolicy:
    """Versioned lifecycle rule for one dataset family."""

    policy_id: str
    dataset_key: str
    version: int
    retention_days: int
    archive_after_days: int | None = None
    priority: str = "normal"
    active: bool = False

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.dataset_key.strip() or self.version < 1:
            raise ValueError("RetentionPolicy identifiers/version are required")
        if self.retention_days <= 0:
            raise ValueError("RetentionPolicy.retention_days must be positive")
        if self.archive_after_days is not None and self.archive_after_days < self.retention_days:
            raise ValueError("archive_after_days cannot precede retention_days")


@dataclass(frozen=True)
class StorageHold:
    """Non-destructive hold preventing retention deletion."""

    hold_id: str
    resource_type: str
    resource_key: str
    reason: str
    created_by: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    released_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.hold_id,
                self.resource_type,
                self.resource_key,
                self.reason,
                self.created_by,
            )
        ):
            raise ValueError("StorageHold identifiers and reason are required")
        _aware(self.created_at, "StorageHold.created_at")
        for name, value in (("expires_at", self.expires_at), ("released_at", self.released_at)):
            if value is not None:
                _aware(value, f"StorageHold.{name}")
        if self.expires_at is not None and self.expires_at < self.created_at:
            raise ValueError("StorageHold.expires_at cannot precede created_at")


@dataclass(frozen=True)
class ArchiveManifest:
    """Verified archive evidence for retained raw/fact data."""

    archive_id: str
    dataset_key: str
    object_count: int
    size_bytes: int
    location: str
    checksum: str
    state: ArchiveState = ArchiveState.PLANNED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    verified_at: datetime | None = None
    retention_until: datetime | None = None

    def __post_init__(self) -> None:
        if (
            not self.archive_id.strip()
            or not self.dataset_key.strip()
            or not self.location.strip()
            or not self.checksum.strip()
        ):
            raise ValueError("ArchiveManifest identifiers/location/checksum are required")
        if self.object_count < 0 or self.size_bytes < 0:
            raise ValueError("ArchiveManifest counts cannot be negative")
        _aware(self.created_at, "ArchiveManifest.created_at")
        if self.verified_at is not None:
            _aware(self.verified_at, "ArchiveManifest.verified_at")
        if self.retention_until is not None:
            _aware(self.retention_until, "ArchiveManifest.retention_until")
        if self.state is ArchiveState.VERIFIED and self.verified_at is None:
            raise ValueError("Verified archive requires verified_at")


@dataclass(frozen=True)
class RetentionRun:
    """Auditable result of one bounded retention planning or deletion pass."""

    run_id: str
    dataset_key: str
    policy_version: int | None
    dry_run: bool
    outcome: str
    requested: int
    candidates: int
    planned: int
    deleted: int
    held: int
    blocked: int
    bytes_planned: int = 0
    bytes_deleted: int = 0
    cutoff: datetime | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.dataset_key.strip():
            raise ValueError("RetentionRun identifiers are required")
        if self.policy_version is not None and self.policy_version < 1:
            raise ValueError("RetentionRun.policy_version must be positive")
        if self.outcome not in {"success", "partial", "noop", "blocked", "failed"}:
            raise ValueError("RetentionRun.outcome is invalid")
        for name in (
            "requested",
            "candidates",
            "planned",
            "deleted",
            "held",
            "blocked",
            "bytes_planned",
            "bytes_deleted",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"RetentionRun.{name} cannot be negative")
        _aware(self.started_at, "RetentionRun.started_at")
        _aware(self.finished_at, "RetentionRun.finished_at")
        if self.finished_at < self.started_at:
            raise ValueError("RetentionRun.finished_at cannot precede started_at")
        if self.cutoff is not None:
            _aware(self.cutoff, "RetentionRun.cutoff")


__all__ = [
    "ArchiveManifest",
    "ArchiveState",
    "RetentionPolicy",
    "RetentionRun",
    "StorageHold",
]
