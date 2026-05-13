"""Repository providers for config center application layer."""

from __future__ import annotations

from apps.config_center.infrastructure.repositories import (
    ConfigCenterSettingsRepository,
    QlibTrainingProfileRepository,
    QlibTrainingRunRepository,
)


def get_config_center_settings_repository() -> ConfigCenterSettingsRepository:
    return ConfigCenterSettingsRepository()


def get_qlib_training_profile_repository() -> QlibTrainingProfileRepository:
    return QlibTrainingProfileRepository()


def get_qlib_training_run_repository() -> QlibTrainingRunRepository:
    return QlibTrainingRunRepository()

