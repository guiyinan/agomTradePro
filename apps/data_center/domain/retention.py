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


class ArchiveRestoreOutcome(str, Enum):
    """Trusted staging-restore state for an exported archive."""

    NOT_TESTED = "not_tested"
    SUCCESS = "success"
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
    archive_retention_days: int | None = None
    priority: str = "normal"
    active: bool = False

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.dataset_key.strip() or self.version < 1:
            raise ValueError("RetentionPolicy identifiers/version are required")
        if self.retention_days <= 0:
            raise ValueError("RetentionPolicy.retention_days must be positive")
        if self.archive_after_days is not None:
            if self.archive_after_days <= 0:
                raise ValueError("archive_after_days must be positive")
            if self.archive_after_days > self.retention_days:
                raise ValueError("archive_after_days cannot follow retention_days")
        if self.archive_retention_days is not None:
            if self.archive_retention_days <= self.retention_days:
                raise ValueError("archive_retention_days must outlive hot retention")


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
    contract_version: str = ""
    schema_version: str = ""
    format_version: str = "raw-payload-fernet-jsonl-gzip-v1"
    encryption_algorithm: str = ""
    encryption_key_ref: str = ""
    encryption_key_version: str = ""
    coverage_started_at: datetime | None = None
    coverage_ended_at: datetime | None = None
    restore_outcome: ArchiveRestoreOutcome = ArchiveRestoreOutcome.NOT_TESTED
    last_restored_at: datetime | None = None

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
        for name, value in (
            ("coverage_started_at", self.coverage_started_at),
            ("coverage_ended_at", self.coverage_ended_at),
            ("last_restored_at", self.last_restored_at),
        ):
            if value is not None:
                _aware(value, f"ArchiveManifest.{name}")
        if (
            self.coverage_started_at is not None
            and self.coverage_ended_at is not None
            and self.coverage_ended_at < self.coverage_started_at
        ):
            raise ValueError("ArchiveManifest coverage range is invalid")
        if self.state is ArchiveState.VERIFIED and self.verified_at is None:
            raise ValueError("Verified archive requires verified_at")
        if self.restore_outcome is ArchiveRestoreOutcome.SUCCESS and self.last_restored_at is None:
            raise ValueError("Successful archive restore requires last_restored_at")


@dataclass(frozen=True)
class ArchiveMember:
    """Exact immutable RawPayload coverage recorded for one archive."""

    payload_id: str
    payload_hash: str
    record_digest: str
    schema_fingerprint: str
    fetched_at: datetime
    size_bytes: int

    def __post_init__(self) -> None:
        if (
            not self.payload_id.strip()
            or not self.payload_hash.strip()
            or not self.record_digest.strip()
            or not self.schema_fingerprint.strip()
        ):
            raise ValueError("ArchiveMember identifiers are required")
        _aware(self.fetched_at, "ArchiveMember.fetched_at")
        if self.size_bytes < 0:
            raise ValueError("ArchiveMember.size_bytes cannot be negative")


@dataclass(frozen=True)
class ArchiveArtifact:
    """Evidence obtained by writing or independently reading archive bytes."""

    archive_id: str
    dataset_key: str
    contract_version: str
    schema_version: str
    format_version: str
    encryption_algorithm: str
    encryption_key_ref: str
    encryption_key_version: str
    location: str
    checksum: str
    object_count: int
    size_bytes: int
    created_at: datetime
    coverage_started_at: datetime
    coverage_ended_at: datetime
    members: tuple[ArchiveMember, ...]

    def __post_init__(self) -> None:
        for name in (
            "archive_id",
            "dataset_key",
            "contract_version",
            "schema_version",
            "format_version",
            "encryption_algorithm",
            "encryption_key_ref",
            "encryption_key_version",
            "location",
            "checksum",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"ArchiveArtifact.{name} cannot be empty")
        if self.object_count < 1 or self.object_count != len(self.members):
            raise ValueError("ArchiveArtifact.object_count must match non-empty members")
        if self.size_bytes < 1:
            raise ValueError("ArchiveArtifact.size_bytes must be positive")
        _aware(self.created_at, "ArchiveArtifact.created_at")
        _aware(self.coverage_started_at, "ArchiveArtifact.coverage_started_at")
        _aware(self.coverage_ended_at, "ArchiveArtifact.coverage_ended_at")
        if self.coverage_ended_at < self.coverage_started_at:
            raise ValueError("ArchiveArtifact coverage range is invalid")
        if len({member.payload_id for member in self.members}) != len(self.members):
            raise ValueError("ArchiveArtifact payload IDs must be unique")
        if self.coverage_started_at != min(member.fetched_at for member in self.members):
            raise ValueError("ArchiveArtifact coverage start must equal earliest member")
        if self.coverage_ended_at != max(member.fetched_at for member in self.members):
            raise ValueError("ArchiveArtifact coverage end must equal latest member")

    def matches_manifest(
        self,
        manifest: ArchiveManifest,
        members: tuple[ArchiveMember, ...],
    ) -> bool:
        """Return whether observed bytes exactly match immutable persisted evidence."""

        return (
            self.archive_id == manifest.archive_id
            and self.dataset_key == manifest.dataset_key
            and self.contract_version == manifest.contract_version
            and self.schema_version == manifest.schema_version
            and self.format_version == manifest.format_version
            and self.encryption_algorithm == manifest.encryption_algorithm
            and self.encryption_key_ref == manifest.encryption_key_ref
            and self.encryption_key_version == manifest.encryption_key_version
            and self.location == manifest.location
            and self.checksum == manifest.checksum
            and self.object_count == manifest.object_count
            and self.size_bytes == manifest.size_bytes
            and self.created_at == manifest.created_at
            and self.coverage_started_at == manifest.coverage_started_at
            and self.coverage_ended_at == manifest.coverage_ended_at
            and self.members == members
        )


@dataclass(frozen=True)
class ArchiveRestoreAudit:
    """Append-only evidence from a trusted isolated archive restore."""

    audit_id: str
    operation_key: str
    archive_id: str
    outcome: ArchiveRestoreOutcome
    observed_checksum: str
    observed_object_count: int
    observed_size_bytes: int
    restored_object_count: int
    restored_bytes: int
    started_at: datetime
    finished_at: datetime
    reason: str = ""

    def __post_init__(self) -> None:
        if (
            not self.audit_id.strip()
            or not self.archive_id.strip()
            or not self.operation_key.strip()
        ):
            raise ValueError("ArchiveRestoreAudit identifiers are required")
        if self.outcome is ArchiveRestoreOutcome.NOT_TESTED:
            raise ValueError("ArchiveRestoreAudit outcome must be terminal")
        for name in (
            "observed_object_count",
            "observed_size_bytes",
            "restored_object_count",
            "restored_bytes",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"ArchiveRestoreAudit.{name} cannot be negative")
        _aware(self.started_at, "ArchiveRestoreAudit.started_at")
        _aware(self.finished_at, "ArchiveRestoreAudit.finished_at")
        if self.finished_at < self.started_at:
            raise ValueError("ArchiveRestoreAudit.finished_at cannot precede started_at")
        if self.outcome is ArchiveRestoreOutcome.SUCCESS:
            if not self.observed_checksum.strip():
                raise ValueError("Successful archive restore requires checksum evidence")
            if self.restored_object_count != self.observed_object_count:
                raise ValueError("Successful archive restore count mismatch")
            if self.observed_size_bytes < 1 or self.restored_bytes != self.observed_size_bytes:
                raise ValueError("Successful archive restore size mismatch")


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
    "ArchiveArtifact",
    "ArchiveManifest",
    "ArchiveMember",
    "ArchiveRestoreAudit",
    "ArchiveRestoreOutcome",
    "ArchiveState",
    "RetentionPolicy",
    "RetentionRun",
    "StorageHold",
]
