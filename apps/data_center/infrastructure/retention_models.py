"""ORM model for append-only Data Center retention run evidence."""

from __future__ import annotations

import uuid

from django.db import models

from apps.data_center.domain.retention import RetentionRun


class RetentionRunModel(models.Model):
    """Append-only evidence for one bounded retention pass."""

    OUTCOME_CHOICES = [(item, item) for item in ("success", "partial", "noop", "blocked", "failed")]

    run_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset_key = models.CharField(max_length=160, db_index=True)
    policy_version = models.PositiveIntegerField(null=True, blank=True)
    dry_run = models.BooleanField(default=True)
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES, db_index=True)
    requested = models.PositiveIntegerField(default=0)
    candidates = models.PositiveIntegerField(default=0)
    planned = models.PositiveIntegerField(default=0)
    deleted = models.PositiveIntegerField(default=0)
    held = models.PositiveIntegerField(default=0)
    blocked = models.PositiveIntegerField(default=0)
    bytes_planned = models.PositiveBigIntegerField(default=0)
    bytes_deleted = models.PositiveBigIntegerField(default=0)
    cutoff = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField()
    reason = models.TextField(blank=True)

    class Meta:
        db_table = "data_center_retention_run"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["dataset_key", "started_at"]),
            models.Index(fields=["outcome", "started_at"]),
        ]

    def to_domain(self) -> RetentionRun:
        """Convert persisted retention evidence to its domain value object."""

        return RetentionRun(
            run_id=str(self.run_id),
            dataset_key=self.dataset_key,
            policy_version=self.policy_version,
            dry_run=self.dry_run,
            outcome=self.outcome,
            requested=int(self.requested),
            candidates=int(self.candidates),
            planned=int(self.planned),
            deleted=int(self.deleted),
            held=int(self.held),
            blocked=int(self.blocked),
            bytes_planned=int(self.bytes_planned),
            bytes_deleted=int(self.bytes_deleted),
            cutoff=self.cutoff,
            started_at=self.started_at,
            finished_at=self.finished_at,
            reason=self.reason,
        )


__all__ = ["RetentionRunModel"]
