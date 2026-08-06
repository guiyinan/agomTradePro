"""Repository provider contracts for config center application layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from apps.config_center.domain.backup_delivery import BackupDeliveryState
from apps.config_center.domain.entities import AlphaUniverseConfig, DecisionRuntimeState


class ConfigCenterSettingsRepository(Protocol):
    def build_runtime_config_payload(self) -> dict[str, Any]: ...
    def update_runtime_config(
        self,
        data: dict[str, Any],
        *,
        actor: str = "config-center",
    ) -> dict[str, Any]: ...
    def build_system_governance_payload(self) -> dict[str, Any]: ...
    def update_system_governance(
        self,
        data: dict[str, Any],
        *,
        actor: str = "config-center",
    ) -> dict[str, Any]: ...
    def acquire_system_settings_lock(self) -> Any: ...
    def get_decision_runtime_state(self) -> DecisionRuntimeState: ...
    def set_decision_runtime_state(
        self,
        state: DecisionRuntimeState,
    ) -> DecisionRuntimeState: ...
    def build_backup_delivery_payload(self) -> dict[str, Any]: ...
    def get_backup_delivery_state(self) -> BackupDeliveryState: ...
    def record_backup_download_token(
        self,
        *,
        digest: str,
        expires_at: datetime,
    ) -> BackupDeliveryState: ...
    def mark_backup_delivery_sent(self, sent_at: datetime) -> BackupDeliveryState: ...
    def consume_backup_download_token(self, *, digest: str, consumed_at: datetime) -> bool: ...
    def update_backup_delivery(
        self,
        data: dict[str, Any],
        *,
        actor: str = "config-center",
    ) -> dict[str, Any]: ...


class QlibTrainingProfileRepository(Protocol):
    def list_profiles(self) -> list[Any]: ...
    def get_profile(
        self, *, profile_id: int | None = None, profile_key: str | None = None
    ) -> Any: ...
    def save_profile(self, data: dict[str, Any]) -> Any: ...


class QlibTrainingRunRepository(Protocol):
    def list_runs(self, *, limit: int = 50) -> list[Any]: ...
    def get_run(self, run_id: str) -> Any: ...
    def has_active_run(self) -> bool: ...
    def create_pending_run_if_idle(
        self,
        *,
        settings_repo: ConfigCenterSettingsRepository,
        profile: Any,
        requested_by: Any,
        model_name: str,
        model_type: str,
        resolved_train_config: dict[str, Any],
    ) -> Any: ...
    def attach_task(self, *, run_id: str, celery_task_id: str) -> Any: ...
    def mark_running(self, *, run_id: str, celery_task_id: str = "") -> Any: ...
    def mark_succeeded(
        self,
        *,
        run_id: str,
        result_model_name: str,
        result_artifact_hash: str,
        result_metrics: dict[str, Any],
        registry_result: dict[str, Any],
    ) -> Any: ...
    def mark_failed(self, *, run_id: str, error_message: str) -> Any: ...


class AlphaUniverseConfigRepository(Protocol):
    def list_configs(self, *, include_inactive: bool = False) -> list[Any]: ...
    def get_by_universe_id(self, universe_id: str) -> Any: ...
    def get_domain_by_universe_id(
        self,
        universe_id: str,
    ) -> AlphaUniverseConfig | None: ...
    def save_config(self, config: Any) -> Any: ...
    def resolve_member_codes(self, universe_id: str) -> list[str]: ...


_settings_repository: ConfigCenterSettingsRepository | None = None
_profile_repository: QlibTrainingProfileRepository | None = None
_run_repository: QlibTrainingRunRepository | None = None
_alpha_universe_repository: AlphaUniverseConfigRepository | None = None


def configure_config_center_repositories(
    *,
    settings_repository: ConfigCenterSettingsRepository,
    profile_repository: QlibTrainingProfileRepository,
    run_repository: QlibTrainingRunRepository,
    alpha_universe_repository: AlphaUniverseConfigRepository | None = None,
) -> None:
    """Register concrete config-center repositories at the composition root."""

    global _settings_repository, _profile_repository, _run_repository, _alpha_universe_repository
    _settings_repository = settings_repository
    _profile_repository = profile_repository
    _run_repository = run_repository
    _alpha_universe_repository = alpha_universe_repository


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


def get_alpha_universe_config_repository() -> AlphaUniverseConfigRepository:
    if _alpha_universe_repository is None:
        raise RuntimeError("Alpha universe config repository is not configured")
    return _alpha_universe_repository
