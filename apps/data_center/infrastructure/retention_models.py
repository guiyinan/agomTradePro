"""ORM model for append-only Data Center retention run evidence."""

from __future__ import annotations

import uuid

from django.db import models

from apps.data_center.domain.retention import (
    RetentionMemberExecution,
    RetentionPlan,
    RetentionPlanDecision,
    RetentionPlanMember,
    RetentionPlanStatus,
    RetentionRun,
)


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


class RetentionPlanModel(models.Model):
    """Exact bounded retention snapshot and its single enforcement claim."""

    plan_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operation_id = models.CharField(max_length=160, unique=True)
    dataset_key = models.CharField(max_length=160, db_index=True)
    policy_id = models.UUIDField()
    policy_version = models.PositiveIntegerField()
    requested = models.PositiveIntegerField()
    candidates = models.PositiveIntegerField(default=0)
    planned = models.PositiveIntegerField(default=0)
    held = models.PositiveIntegerField(default=0)
    blocked = models.PositiveIntegerField(default=0)
    bytes_planned = models.PositiveBigIntegerField(default=0)
    cutoff = models.DateTimeField()
    created_at = models.DateTimeField(db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    snapshot_digest = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=[(item.value, item.value) for item in RetentionPlanStatus],
        db_index=True,
    )
    enforce_operation_id = models.CharField(max_length=160, null=True, blank=True, unique=True)
    outcome = models.CharField(max_length=16, blank=True)
    deleted = models.PositiveIntegerField(default=0)
    execution_blocked = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    bytes_deleted = models.PositiveBigIntegerField(default=0)
    finished_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True)

    class Meta:
        db_table = "data_center_retention_plan"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["dataset_key", "status", "expires_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(requested__gte=1, requested__lte=10_000),
                name="dc_retention_plan_requested_range",
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("created_at")),
                name="dc_retention_plan_expiry_after_create",
            ),
        ]

    def to_domain(self) -> RetentionPlan:
        """Convert the persisted plan and execution summary to its domain value."""

        return RetentionPlan(
            plan_id=str(self.plan_id),
            operation_id=self.operation_id,
            dataset_key=self.dataset_key,
            policy_id=str(self.policy_id),
            policy_version=int(self.policy_version),
            requested=int(self.requested),
            candidates=int(self.candidates),
            planned=int(self.planned),
            held=int(self.held),
            blocked=int(self.blocked),
            bytes_planned=int(self.bytes_planned),
            cutoff=self.cutoff,
            created_at=self.created_at,
            expires_at=self.expires_at,
            snapshot_digest=self.snapshot_digest,
            status=RetentionPlanStatus(self.status),
            enforce_operation_id=self.enforce_operation_id or "",
            outcome=self.outcome,
            deleted=int(self.deleted),
            execution_blocked=int(self.execution_blocked),
            failed=int(self.failed),
            bytes_deleted=int(self.bytes_deleted),
            finished_at=self.finished_at,
            reason=self.reason,
        )


class RetentionPlanMemberModel(models.Model):
    """Immutable plan evidence plus monotonic execution state for one payload."""

    id = models.BigAutoField(primary_key=True)
    plan = models.ForeignKey(
        RetentionPlanModel,
        on_delete=models.PROTECT,
        related_name="members",
    )
    ordinal = models.PositiveIntegerField()
    payload_id = models.UUIDField()
    payload_hash = models.CharField(max_length=128)
    record_digest = models.CharField(max_length=128)
    schema_fingerprint = models.CharField(max_length=128)
    fetched_at = models.DateTimeField()
    retention_until = models.DateTimeField(null=True, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    decision = models.CharField(
        max_length=24,
        choices=[(item.value, item.value) for item in RetentionPlanDecision],
    )
    archive = models.ForeignKey(
        "data_center.ArchiveManifestModel",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="retention_plan_members",
    )
    execution = models.CharField(
        max_length=16,
        choices=[(item.value, item.value) for item in RetentionMemberExecution],
        default=RetentionMemberExecution.PENDING.value,
    )
    execution_reason = models.TextField(blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "data_center_retention_plan_member"
        ordering = ["plan_id", "ordinal"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "payload_id"], name="dc_ret_plan_member_payload_uniq"
            ),
            models.UniqueConstraint(
                fields=["plan", "ordinal"], name="dc_ret_plan_member_ordinal_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["plan", "execution", "ordinal"]),
            models.Index(fields=["payload_id", "record_digest"]),
        ]

    def to_domain(self) -> RetentionPlanMember:
        """Convert exact member evidence to its domain value."""

        return RetentionPlanMember(
            ordinal=int(self.ordinal),
            payload_id=str(self.payload_id),
            payload_hash=self.payload_hash,
            record_digest=self.record_digest,
            schema_fingerprint=self.schema_fingerprint,
            fetched_at=self.fetched_at,
            retention_until=self.retention_until,
            size_bytes=int(self.size_bytes),
            decision=RetentionPlanDecision(self.decision),
            archive_id=str(self.archive_id) if self.archive_id is not None else None,
            execution=RetentionMemberExecution(self.execution),
            execution_reason=self.execution_reason,
            deleted_at=self.deleted_at,
        )


__all__ = ["RetentionPlanMemberModel", "RetentionPlanModel", "RetentionRunModel"]
