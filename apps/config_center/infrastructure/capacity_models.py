"""Persistence models for storage capacity observations."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from django.db import models

from apps.config_center.domain.runtime_config import StorageCapacityObservation


class StorageCapacityObservationModel(models.Model):
    """Filesystem/database capacity snapshot used by readiness and planning."""

    observation_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    environment = models.CharField(max_length=80, db_index=True)
    observed_at = models.DateTimeField(db_index=True)
    filesystem_total_bytes = models.PositiveBigIntegerField()
    filesystem_used_bytes = models.PositiveBigIntegerField()
    filesystem_free_bytes = models.PositiveBigIntegerField()
    database_size_bytes = models.PositiveBigIntegerField()
    relation_sizes = models.JSONField(default=dict)
    policy_key = models.CharField(max_length=100, blank=True, db_index=True)
    configured_capacity_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    effective_capacity_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    usage_ratio = models.FloatField(null=True, blank=True)
    pressure_state = models.CharField(max_length=20, blank=True, db_index=True)
    source = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "config_center_storage_capacity_observation"
        ordering = ["-observed_at", "-created_at"]
        indexes = [
            models.Index(fields=["environment", "observed_at"]),
            models.Index(fields=["environment", "pressure_state", "observed_at"]),
        ]

    def to_domain(self) -> StorageCapacityObservation:
        """Convert the persisted snapshot into a validated domain value."""

        relation_sizes = self.relation_sizes
        metadata = self.metadata
        if not isinstance(relation_sizes, Mapping):
            raise ValueError("storage capacity relation_sizes must be an object")
        if not isinstance(metadata, Mapping):
            raise ValueError("storage capacity metadata must be an object")
        return StorageCapacityObservation(
            observation_id=str(self.observation_id),
            environment=self.environment,
            observed_at=self.observed_at,
            filesystem_total_bytes=int(self.filesystem_total_bytes),
            filesystem_used_bytes=int(self.filesystem_used_bytes),
            filesystem_free_bytes=int(self.filesystem_free_bytes),
            database_size_bytes=int(self.database_size_bytes),
            relation_sizes={str(key): int(value) for key, value in relation_sizes.items()},
            policy_key=self.policy_key,
            configured_capacity_bytes=(
                int(self.configured_capacity_bytes)
                if self.configured_capacity_bytes is not None
                else None
            ),
            effective_capacity_bytes=(
                int(self.effective_capacity_bytes)
                if self.effective_capacity_bytes is not None
                else None
            ),
            usage_ratio=float(self.usage_ratio) if self.usage_ratio is not None else None,
            pressure_state=self.pressure_state,
            source=self.source,
            metadata={str(key): value for key, value in metadata.items()},
        )


__all__ = ["StorageCapacityObservationModel"]
