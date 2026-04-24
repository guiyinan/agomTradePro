"""Data-center summaries used by the system config center."""

from __future__ import annotations

from typing import Any, Protocol

from apps.data_center.application import registry_factory


class DataCenterConfigSummaryRepository(Protocol):
    """Read model contract for data-center config summaries."""

    def get_provider_summary(self) -> dict[str, Any]:
        """Return provider configuration summary."""

    def list_active_provider_names(self) -> list[str]:
        """Return active provider names configured in the database."""


class DataCenterConfigSummaryService:
    """Application service for config-center data-center summaries."""

    def __init__(self, repository: DataCenterConfigSummaryRepository):
        self.repository = repository

    def get_provider_summary(self) -> dict[str, Any]:
        """Return data-provider configuration summary."""

        return self.repository.get_provider_summary()

    def get_runtime_summary(self) -> dict[str, Any]:
        """Return data-provider runtime status summary."""

        configured = self.repository.list_active_provider_names()
        snapshots = [snapshot.to_dict() for snapshot in registry_factory.get_registry().get_all_statuses()]
        unique_providers = sorted({snap["provider_name"] for snap in snapshots})
        circuit_open_count = sum(1 for snap in snapshots if snap["status"] == "circuit_open")
        degraded_count = sum(1 for snap in snapshots if snap["status"] == "degraded")
        healthy_count = sum(1 for snap in snapshots if snap["status"] == "healthy")

        status = "configured" if configured else "missing"
        if circuit_open_count > 0 or degraded_count > 0:
            status = "attention"

        return {
            "status": status,
            "summary": {
                "configured_provider_count": len(configured),
                "runtime_provider_count": len(unique_providers),
                "healthy_snapshot_count": healthy_count,
                "degraded_snapshot_count": degraded_count,
                "circuit_open_snapshot_count": circuit_open_count,
                "providers": unique_providers[:5],
            },
        }


_config_summary_repository: DataCenterConfigSummaryRepository | None = None


def configure_data_center_config_summary_repository(
    repository: DataCenterConfigSummaryRepository,
) -> None:
    """Register the data-center config-summary repository."""

    global _config_summary_repository
    _config_summary_repository = repository


def get_data_center_config_summary_service() -> DataCenterConfigSummaryService:
    """Return the configured data-center config-summary service."""

    if _config_summary_repository is None:
        raise RuntimeError("Data-center config summary repository is not configured")
    return DataCenterConfigSummaryService(_config_summary_repository)
