"""Repositories for storage capacity observation evidence."""

from __future__ import annotations

import uuid

from apps.config_center.domain.runtime_config import StorageCapacityObservation

from .capacity_models import StorageCapacityObservationModel


def _observation_uuid(value: str) -> uuid.UUID:
    """Convert a domain observation identifier to a database UUID."""

    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("storage observation_id must be a UUID") from exc


class StorageCapacityObservationRepository:
    """Persist and query bounded capacity evidence history."""

    def save(self, observation: StorageCapacityObservation) -> StorageCapacityObservation:
        """Upsert one observation by its immutable identifier."""

        row, _created = StorageCapacityObservationModel._default_manager.update_or_create(
            observation_id=_observation_uuid(observation.observation_id),
            defaults={
                "environment": observation.environment,
                "observed_at": observation.observed_at,
                "filesystem_total_bytes": observation.filesystem_total_bytes,
                "filesystem_used_bytes": observation.filesystem_used_bytes,
                "filesystem_free_bytes": observation.filesystem_free_bytes,
                "database_size_bytes": observation.database_size_bytes,
                "relation_sizes": observation.relation_sizes,
                "policy_key": observation.policy_key,
                "configured_capacity_bytes": observation.configured_capacity_bytes,
                "effective_capacity_bytes": observation.effective_capacity_bytes,
                "usage_ratio": observation.usage_ratio,
                "pressure_state": observation.pressure_state,
                "source": observation.source,
                "metadata": observation.metadata,
            },
        )
        return row.to_domain()

    def get_latest(self, environment: str) -> StorageCapacityObservation | None:
        """Return the newest observation for one environment."""

        row = (
            StorageCapacityObservationModel._default_manager.filter(environment=environment.strip())
            .order_by("-observed_at", "-created_at")
            .first()
        )
        return row.to_domain() if row is not None else None

    def list_recent(
        self,
        environment: str,
        *,
        limit: int = 30,
    ) -> list[StorageCapacityObservation]:
        """Return a bounded newest-first observation history."""

        if isinstance(limit, bool) or limit <= 0:
            raise ValueError("limit must be positive")
        rows = StorageCapacityObservationModel._default_manager.filter(
            environment=environment.strip()
        ).order_by("-observed_at", "-created_at")[:limit]
        return [row.to_domain() for row in rows]


__all__ = ["StorageCapacityObservationRepository"]
