"""Exact archive coverage and append-only staging-restore evidence models."""

from __future__ import annotations

import uuid

from django.db import models

from apps.data_center.domain.retention import (
    ArchiveMember,
    ArchiveRestoreAudit,
    ArchiveRestoreOutcome,
)


class ArchiveMemberModel(models.Model):
    """One exact RawPayload member covered by an immutable archive."""

    id = models.BigAutoField(primary_key=True)
    archive = models.ForeignKey(
        "data_center.ArchiveManifestModel",
        on_delete=models.PROTECT,
        related_name="members",
    )
    payload_id = models.UUIDField(db_index=True)
    payload_hash = models.CharField(max_length=128, db_index=True)
    record_digest = models.CharField(max_length=128, db_index=True)
    schema_fingerprint = models.CharField(max_length=128)
    fetched_at = models.DateTimeField(db_index=True)
    size_bytes = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = "data_center_archive_member"
        ordering = ["fetched_at", "payload_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["archive", "payload_id"],
                name="dc_archive_member_payload_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["payload_id", "payload_hash"]),
            models.Index(fields=["archive", "fetched_at"]),
        ]

    def to_domain(self) -> ArchiveMember:
        """Convert the exact coverage row to its immutable domain value."""

        return ArchiveMember(
            payload_id=str(self.payload_id),
            payload_hash=self.payload_hash,
            record_digest=self.record_digest,
            schema_fingerprint=self.schema_fingerprint,
            fetched_at=self.fetched_at,
            size_bytes=int(self.size_bytes),
        )


class ArchiveRestoreAuditModel(models.Model):
    """Append-only evidence from one isolated archive staging restore."""

    OUTCOME_CHOICES = [
        (ArchiveRestoreOutcome.SUCCESS.value, ArchiveRestoreOutcome.SUCCESS.value),
        (ArchiveRestoreOutcome.FAILED.value, ArchiveRestoreOutcome.FAILED.value),
    ]

    audit_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operation_key = models.CharField(max_length=240, unique=True)
    archive = models.ForeignKey(
        "data_center.ArchiveManifestModel",
        on_delete=models.PROTECT,
        related_name="restore_audits",
    )
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, db_index=True)
    observed_checksum = models.CharField(max_length=128, blank=True)
    observed_object_count = models.PositiveBigIntegerField(default=0)
    observed_size_bytes = models.PositiveBigIntegerField(default=0)
    restored_object_count = models.PositiveBigIntegerField(default=0)
    restored_bytes = models.PositiveBigIntegerField(default=0)
    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField(db_index=True)
    reason = models.TextField(blank=True)

    class Meta:
        db_table = "data_center_archive_restore_audit"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["archive", "outcome", "started_at"]),
        ]

    def to_domain(self) -> ArchiveRestoreAudit:
        """Convert the persisted audit row to immutable domain evidence."""

        return ArchiveRestoreAudit(
            audit_id=str(self.audit_id),
            operation_key=self.operation_key,
            archive_id=str(self.archive_id),
            outcome=ArchiveRestoreOutcome(self.outcome),
            observed_checksum=self.observed_checksum,
            observed_object_count=int(self.observed_object_count),
            observed_size_bytes=int(self.observed_size_bytes),
            restored_object_count=int(self.restored_object_count),
            restored_bytes=int(self.restored_bytes),
            started_at=self.started_at,
            finished_at=self.finished_at,
            reason=self.reason,
        )


__all__ = ["ArchiveMemberModel", "ArchiveRestoreAuditModel"]
