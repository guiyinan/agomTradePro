"""Append-only ORM storage for point-in-time facts and manifests."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models


class ImmutableModelMixin:
    """Reject updates so evidence records can only be appended."""

    def save(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        """Insert a new row and reject mutation of an existing row."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("Point-in-time evidence records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        """Reject deletion of immutable evidence."""

        raise ValidationError("Point-in-time evidence records cannot be deleted.")


class PITFactVersionModel(ImmutableModelMixin, models.Model):
    """Canonical bitemporal overlay for versioned research facts."""

    QUALITY_CHOICES = [
        ("verified", "Verified"),
        ("estimated", "Estimated"),
        ("unknown", "Unknown"),
    ]

    dataset = models.CharField(max_length=64, db_index=True)
    business_key = models.CharField(max_length=255, db_index=True)
    effective_at = models.DateTimeField(db_index=True)
    effective_to = models.DateTimeField(null=True, blank=True, db_index=True)
    available_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ingested_at = models.DateTimeField(db_index=True)
    superseded_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revision_number = models.PositiveIntegerField(default=0)
    source_record_id = models.CharField(max_length=255)
    content_hash = models.CharField(max_length=64)
    pit_quality = models.CharField(max_length=16, choices=QUALITY_CHOICES, default="unknown")
    payload = models.JSONField(default=dict)

    class Meta:
        db_table = "data_center_pit_fact_version"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "business_key", "revision_number", "content_hash"],
                name="dc_pit_fact_version_identity_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["dataset", "business_key", "effective_at"]),
            models.Index(fields=["dataset", "available_at"]),
            models.Index(fields=["dataset", "ingested_at"]),
        ]


class PITDatasetManifestModel(ImmutableModelMixin, models.Model):
    """Frozen record of fact versions selected for one research run."""

    SCOPE_CHOICES = [("public", "Public"), ("system", "System")]

    manifest_id = models.CharField(max_length=64, primary_key=True)
    as_of_time = models.DateTimeField(db_index=True)
    knowledge_scope = models.CharField(max_length=10, choices=SCOPE_CHOICES)
    calendar_version = models.CharField(max_length=64)
    query_spec = models.JSONField(default=dict)
    selected_versions = models.JSONField(default=list)
    coverage = models.JSONField(default=dict)
    missing = models.JSONField(default=list)
    estimated = models.JSONField(default=list)
    unknown = models.JSONField(default=list)
    manifest_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_pit_dataset_manifest"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["knowledge_scope", "as_of_time"])]

