from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from django.apps import AppConfig

from core.integration.config_center_egress import (
    ConfigCenterEgressPort,
    EgressEndpoint,
    EgressEndpointSummary,
    configure_config_center_egress_port,
)


class _ConfigCenterEgressAdapter:
    """Adapt Config Center application ports to the app-neutral bridge."""

    def list_endpoints(self, *, include_disabled: bool = True) -> tuple[EgressEndpointSummary, ...]:
        """List endpoint metadata without resolving credentials."""

        from apps.config_center.application.egress_ports import list_egress_endpoints

        return list_egress_endpoints(include_disabled=include_disabled)

    def get_endpoint(self, endpoint_id: int) -> EgressEndpoint | None:
        """Resolve one endpoint for an infrastructure transport."""

        from apps.config_center.application.egress_ports import get_egress_endpoint

        return get_egress_endpoint(endpoint_id)

    def get_endpoint_summary(self, endpoint_id: int) -> EgressEndpointSummary | None:
        """Read one endpoint without resolving credentials."""

        from apps.config_center.application.egress_ports import get_egress_endpoint_summary

        return get_egress_endpoint_summary(endpoint_id)

    def create_endpoint(self, payload: Mapping[str, object]) -> EgressEndpointSummary:
        """Create one endpoint and return its redacted projection."""

        from apps.config_center.application.egress_ports import create_egress_endpoint

        return create_egress_endpoint(payload)

    def update_endpoint(
        self, endpoint_id: int, payload: Mapping[str, object]
    ) -> EgressEndpointSummary | None:
        """Update one endpoint and return its redacted projection."""

        from apps.config_center.application.egress_ports import update_egress_endpoint

        return update_egress_endpoint(endpoint_id, payload)

    def delete_endpoint(self, endpoint_id: int) -> bool:
        """Delete one endpoint and its encrypted credential references."""

        from apps.config_center.application.egress_ports import delete_egress_endpoint

        return delete_egress_endpoint(endpoint_id)


class ConfigCenterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.config_center"
    verbose_name = "配置中心"

    def ready(self) -> None:
        from apps.config_center.application import runtime_public
        from apps.config_center.application.config_summary_service import (
            configure_config_center_summary_repository,
            get_config_center_summary_service,
        )
        from apps.config_center.application.egress_ports import (
            configure_egress_endpoint_repository,
        )
        from apps.config_center.application.repository_provider import (
            ConfigCenterSecretRepository,
            configure_config_center_repositories,
        )
        from apps.config_center.application.runtime_repository_provider import (
            configure_runtime_config_services,
        )
        from apps.config_center.infrastructure.capacity_observer import (
            StorageCapacityObserver,
        )
        from apps.config_center.infrastructure.capacity_repositories import (
            StorageCapacityObservationRepository,
        )
        from apps.config_center.infrastructure.config_summary_repository import (
            DjangoConfigCenterSummaryRepository,
        )
        from apps.config_center.infrastructure.egress_repositories import EgressEndpointRepository
        from apps.config_center.infrastructure.repositories import (
            AlphaUniverseConfigRepository,
            ConfigCenterSettingsRepository,
            QlibTrainingProfileRepository,
            QlibTrainingRunRepository,
        )
        from apps.config_center.infrastructure.runtime_config_repositories import (
            RuntimeConfigDefinitionRepository,
            RuntimeConfigProfileRepository,
            RuntimeConfigRevisionRepository,
            RuntimeConfigSnapshotRepository,
            RuntimeConfigValueRepository,
            StorageBudgetPolicyRepository,
        )
        from apps.config_center.infrastructure.secret_store import ConfigCenterSecretStore
        from core.integration.config_center_runtime import (
            configure_config_center_runtime_port,
        )
        from core.integration.config_secret_store import (
            ConfigSecretStorePort,
            configure_config_secret_store,
        )
        from core.integration.runtime_settings import configure_runtime_settings_provider

        configure_config_center_repositories(
            settings_repository=ConfigCenterSettingsRepository(),
            profile_repository=QlibTrainingProfileRepository(),
            run_repository=QlibTrainingRunRepository(),
            alpha_universe_repository=AlphaUniverseConfigRepository(),
            secret_repository=cast(ConfigCenterSecretRepository, ConfigCenterSecretStore()),
        )
        configure_egress_endpoint_repository(EgressEndpointRepository())
        configure_config_center_egress_port(
            cast(ConfigCenterEgressPort, _ConfigCenterEgressAdapter())
        )
        configure_config_center_summary_repository(DjangoConfigCenterSummaryRepository())
        configure_runtime_settings_provider(get_config_center_summary_service())
        configure_config_center_runtime_port(runtime_public)
        from apps.config_center.application import public as config_center_public

        configure_config_secret_store(cast(ConfigSecretStorePort, config_center_public))
        configure_runtime_config_services(
            definitions=RuntimeConfigDefinitionRepository(),
            profiles=RuntimeConfigProfileRepository(),
            values=RuntimeConfigValueRepository(),
            revisions=RuntimeConfigRevisionRepository(),
            snapshots=RuntimeConfigSnapshotRepository(),
            storage_budget=StorageBudgetPolicyRepository(),
            capacity_observations=StorageCapacityObservationRepository(),
            capacity_observer=StorageCapacityObserver(),
        )
