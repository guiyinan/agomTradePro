from typing import cast

from django.apps import AppConfig


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
        from apps.config_center.application.repository_provider import (
            ConfigCenterSecretRepository,
            configure_config_center_repositories,
        )
        from apps.config_center.application.runtime_repository_provider import (
            configure_runtime_config_services,
        )
        from apps.config_center.infrastructure.capacity_repositories import (
            StorageCapacityObservationRepository,
        )
        from apps.config_center.infrastructure.config_summary_repository import (
            DjangoConfigCenterSummaryRepository,
        )
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
        from core.integration.runtime_settings import configure_runtime_settings_provider

        configure_config_center_repositories(
            settings_repository=ConfigCenterSettingsRepository(),
            profile_repository=QlibTrainingProfileRepository(),
            run_repository=QlibTrainingRunRepository(),
            alpha_universe_repository=AlphaUniverseConfigRepository(),
            secret_repository=cast(ConfigCenterSecretRepository, ConfigCenterSecretStore()),
        )
        configure_config_center_summary_repository(DjangoConfigCenterSummaryRepository())
        configure_runtime_settings_provider(get_config_center_summary_service())
        configure_config_center_runtime_port(runtime_public)
        configure_runtime_config_services(
            definitions=RuntimeConfigDefinitionRepository(),
            profiles=RuntimeConfigProfileRepository(),
            values=RuntimeConfigValueRepository(),
            revisions=RuntimeConfigRevisionRepository(),
            snapshots=RuntimeConfigSnapshotRepository(),
            storage_budget=StorageBudgetPolicyRepository(),
            capacity_observations=StorageCapacityObservationRepository(),
        )
