"""ORM model for explicit canonical publication rollback evidence."""

from __future__ import annotations

import uuid

from django.db import models

from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationRollback,
    PublicationState,
)


class CanonicalPublicationModel(models.Model):
    """Versioned selection of canonical facts for a dataset scope."""

    STATE_CHOICES = [(item.value, item.value) for item in PublicationState]

    publication_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset_key = models.CharField(max_length=160, db_index=True)
    publication_key = models.CharField(max_length=300)
    policy_version = models.CharField(max_length=80)
    state = models.CharField(
        max_length=20, choices=STATE_CHOICES, default=PublicationState.CANDIDATE.value
    )
    selected_source = models.CharField(max_length=100, blank=True, db_index=True)
    publication_hash = models.CharField(max_length=128, db_index=True)
    member_count = models.PositiveIntegerField(default=0)
    conflict_count = models.PositiveIntegerField(default=0)
    coverage_requested_count = models.PositiveIntegerField(default=0)
    coverage_eligible_count = models.PositiveIntegerField(default=0)
    coverage_selected_count = models.PositiveIntegerField(default=0)
    coverage_missing_count = models.PositiveIntegerField(default=0)
    coverage_conflict_count = models.PositiveIntegerField(default=0)
    as_of = models.DateTimeField(null=True, blank=True, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    reinstated_at = models.DateTimeField(null=True, blank=True)
    must_not_use_for_decision = models.BooleanField(default=False)
    blocked_reason = models.TextField(blank=True)
    created_by = models.CharField(max_length=150, default="system")
    run_id = models.UUIDField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_canonical_publication"
        ordering = ["-published_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_key", "publication_key", "publication_hash"],
                name="dc_publication_scope_hash_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    coverage_selected_count__lte=models.F("coverage_eligible_count")
                ),
                name="dc_publication_coverage_selected_lte_eligible",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    coverage_eligible_count__lte=models.F("coverage_requested_count")
                ),
                name="dc_publication_coverage_eligible_lte_requested",
            ),
        ]
        indexes = [
            models.Index(fields=["dataset_key", "publication_key", "state"]),
            models.Index(fields=["dataset_key", "as_of", "state"]),
        ]

    def to_domain(self) -> CanonicalPublication:
        """Convert the persisted publication and embedded coverage snapshot."""

        return CanonicalPublication(
            publication_id=str(self.publication_id),
            dataset_key=self.dataset_key,
            publication_key=self.publication_key,
            policy_version=self.policy_version,
            state=PublicationState(self.state),
            selected_source=self.selected_source,
            publication_hash=self.publication_hash,
            coverage=CoverageSnapshot(
                coverage_id=str(self.publication_id),
                publication_id=str(self.publication_id),
                requested_count=self.coverage_requested_count,
                eligible_count=self.coverage_eligible_count,
                selected_count=self.coverage_selected_count,
                missing_count=self.coverage_missing_count,
                conflict_count=self.coverage_conflict_count,
                generated_at=self.published_at or self.created_at,
            ),
            member_count=self.member_count,
            conflict_count=self.conflict_count,
            as_of=self.as_of,
            published_at=self.published_at,
            superseded_at=self.superseded_at,
            reinstated_at=self.reinstated_at,
            must_not_use_for_decision=self.must_not_use_for_decision,
            blocked_reason=self.blocked_reason,
            created_by=self.created_by,
            run_id=str(self.run_id) if self.run_id else "",
        )


class PublicationMemberModel(models.Model):
    """Selected fact reference belonging to a canonical publication."""

    member_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    publication_id = models.UUIDField(db_index=True)
    dataset_key = models.CharField(max_length=160, db_index=True)
    natural_key = models.CharField(max_length=300)
    source = models.CharField(max_length=100, db_index=True)
    source_record_id = models.CharField(max_length=300)
    fact_table = models.CharField(max_length=160)
    fact_pk = models.CharField(max_length=160)
    observed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    raw_payload_hash = models.CharField(max_length=128, blank=True)
    quality_status = models.CharField(max_length=40, default="accepted")
    revision_number = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "data_center_publication_member"
        ordering = ["natural_key", "source"]
        constraints = [
            models.UniqueConstraint(
                fields=["publication_id", "natural_key"],
                name="dc_publication_member_natural_key_unique",
            ),
        ]
        indexes = [models.Index(fields=["dataset_key", "natural_key", "observed_at"])]

    def to_domain(self) -> PublicationMember:
        """Convert the persisted member reference to a domain value object."""

        return PublicationMember(
            member_id=str(self.member_id),
            publication_id=str(self.publication_id),
            dataset_key=self.dataset_key,
            natural_key=self.natural_key,
            source=self.source,
            source_record_id=self.source_record_id,
            fact_table=self.fact_table,
            fact_pk=self.fact_pk,
            observed_at=self.observed_at,
            raw_payload_hash=self.raw_payload_hash,
            quality_status=self.quality_status,
            revision_number=self.revision_number,
        )


class CoverageSnapshotModel(models.Model):
    """Immutable coverage evidence for a publication."""

    coverage_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    publication_id = models.UUIDField(unique=True, db_index=True)
    requested_count = models.PositiveIntegerField(default=0)
    eligible_count = models.PositiveIntegerField(default=0)
    selected_count = models.PositiveIntegerField(default=0)
    missing_count = models.PositiveIntegerField(default=0)
    conflict_count = models.PositiveIntegerField(default=0)
    generated_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "data_center_coverage_snapshot"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(selected_count__lte=models.F("eligible_count")),
                name="dc_coverage_selected_lte_eligible",
            ),
            models.CheckConstraint(
                condition=models.Q(eligible_count__lte=models.F("requested_count")),
                name="dc_coverage_eligible_lte_requested",
            ),
        ]

    def to_domain(self) -> CoverageSnapshot:
        """Convert the persisted coverage value object."""

        return CoverageSnapshot(
            coverage_id=str(self.coverage_id),
            publication_id=str(self.publication_id),
            requested_count=self.requested_count,
            eligible_count=self.eligible_count,
            selected_count=self.selected_count,
            missing_count=self.missing_count,
            conflict_count=self.conflict_count,
            generated_at=self.generated_at,
        )


class PublicationRollbackModel(models.Model):
    """Durable evidence for an explicit canonical publication rollback."""

    rollback_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    target_publication_id = models.UUIDField(db_index=True)
    previous_publication_id = models.UUIDField(db_index=True)
    dataset_key = models.CharField(max_length=160, db_index=True)
    publication_key = models.CharField(max_length=300)
    reason = models.TextField()
    operator = models.CharField(max_length=150)
    observed_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_publication_rollback"
        ordering = ["-observed_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["target_publication_id", "observed_at"],
                name="dc_publication_rollback_target_time_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["dataset_key", "publication_key", "observed_at"]),
        ]

    def to_domain(self) -> PublicationRollback:
        """Convert durable rollback evidence to its domain value object."""

        return PublicationRollback(
            target_publication_id=str(self.target_publication_id),
            reason=self.reason,
            operator=self.operator,
            observed_at=self.observed_at,
            previous_publication_id=str(self.previous_publication_id),
            rollback_id=str(self.rollback_id),
        )


__all__ = [
    "CanonicalPublicationModel",
    "CoverageSnapshotModel",
    "PublicationMemberModel",
    "PublicationRollbackModel",
]
