"""Repository provider contracts for config center application layer."""

from __future__ import annotations

from typing import Any, Protocol


class ConfigCenterSettingsRepository(Protocol):
    def build_runtime_config_payload(self) -> dict[str, Any]: ...
    def update_runtime_config(self, data) -> dict[str, Any]: ...
    def acquire_system_settings_lock(self): ...


class QlibTrainingProfileRepository(Protocol):
    def list_profiles(self) -> list[Any]: ...
    def get_profile(self, *, profile_id: int | None = None, profile_key: str | None = None): ...
    def save_profile(self, data) -> Any: ...


class QlibTrainingRunRepository(Protocol):
    def list_runs(self, *, limit: int = 50) -> list[Any]: ...
    def get_run(self, run_id: str): ...
    def has_active_run(self) -> bool: ...
    def create_pending_run_if_idle(
        self,
        *,
        settings_repo: ConfigCenterSettingsRepository,
        profile,
        requested_by,
        model_name: str,
        model_type: str,
        resolved_train_config: dict[str, Any],
    ):
        ...
    def attach_task(self, *, run_id: str, celery_task_id: str): ...
    def mark_running(self, *, run_id: str, celery_task_id: str = ""): ...
    def mark_succeeded(
        self,
        *,
        run_id: str,
        result_model_name: str,
        result_artifact_hash: str,
        result_metrics: dict[str, Any],
        registry_result: dict[str, Any],
    ):
        ...
    def mark_failed(self, *, run_id: str, error_message: str): ...


_settings_repository: ConfigCenterSettingsRepository | None = None
_profile_repository: QlibTrainingProfileRepository | None = None
_run_repository: QlibTrainingRunRepository | None = None


def configure_config_center_repositories(
    *,
    settings_repository: ConfigCenterSettingsRepository,
    profile_repository: QlibTrainingProfileRepository,
    run_repository: QlibTrainingRunRepository,
) -> None:
    """Register concrete config-center repositories at the composition root."""

    global _settings_repository, _profile_repository, _run_repository
    _settings_repository = settings_repository
    _profile_repository = profile_repository
    _run_repository = run_repository


def get_config_center_settings_repository() -> ConfigCenterSettingsRepository:
    if _settings_repository is None:
        raise RuntimeError("Config center settings repository is not configured")
    return _settings_repository


def get_qlib_training_profile_repository() -> QlibTrainingProfileRepository:
    if _profile_repository is None:
        raise RuntimeError("Qlib training profile repository is not configured")
    return _profile_repository


def get_qlib_training_run_repository() -> QlibTrainingRunRepository:
    if _run_repository is None:
        raise RuntimeError("Qlib training run repository is not configured")
    return _run_repository
