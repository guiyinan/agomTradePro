"""Infrastructure repositories for config center."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.alpha.application.repository_provider import get_qlib_model_registry_repository
from apps.config_center.infrastructure.models import (
    QlibTrainingProfileModel,
    QlibTrainingRunModel,
    SystemSettingsModel,
)


class ConfigCenterSettingsRepository:
    """Global settings persistence owned by config center."""

    RUNTIME_FIELD_MAP = {
        "enabled": "qlib_enabled",
        "provider_uri": "qlib_provider_uri",
        "region": "qlib_region",
        "model_root": "qlib_model_path",
        "default_universe": "qlib_default_universe",
        "default_feature_set_id": "qlib_default_feature_set_id",
        "default_label_id": "qlib_default_label_id",
        "train_queue_name": "qlib_train_queue_name",
        "infer_queue_name": "qlib_infer_queue_name",
        "allow_auto_activate": "qlib_allow_auto_activate",
        "alpha_fixed_provider": "alpha_fixed_provider",
        "alpha_pool_mode": "alpha_pool_mode",
    }

    def get_system_settings(self) -> SystemSettingsModel:
        return SystemSettingsModel.get_settings()

    def acquire_system_settings_lock(self) -> SystemSettingsModel:
        settings_obj = SystemSettingsModel.get_settings()
        return SystemSettingsModel._default_manager.select_for_update().get(pk=settings_obj.pk)

    def build_runtime_config_payload(self) -> dict[str, Any]:
        settings_obj = self.get_system_settings()
        runtime = dict(settings_obj.get_runtime_qlib_config_payload())
        active_model = get_qlib_model_registry_repository().get_active_model()
        training_task_running = QlibTrainingRunModel._default_manager.filter(
            status__in=[
                QlibTrainingRunModel.STATUS_PENDING,
                QlibTrainingRunModel.STATUS_RUNNING,
            ]
        ).exists()
        latest_run = (
            QlibTrainingRunModel._default_manager.order_by("-requested_at", "-id").first()
        )

        validation_errors: list[str] = []
        provider_path = Path(str(runtime.get("provider_uri") or "")).expanduser()
        model_root = Path(str(runtime.get("model_path") or "")).expanduser()
        if runtime.get("enabled") and not provider_path.exists():
            validation_errors.append("Qlib provider_uri 路径不存在")
        if not str(runtime.get("model_path") or "").strip():
            validation_errors.append("Qlib model_root 未配置")
        elif model_root.exists() and not model_root.is_dir():
            validation_errors.append("Qlib model_root 不是目录")

        return {
            "configured": bool(runtime.get("is_configured")),
            "enabled": bool(runtime.get("enabled")),
            "provider_uri": runtime.get("provider_uri", ""),
            "region": runtime.get("region", "CN"),
            "model_root": runtime.get("model_path", ""),
            "default_universe": runtime.get("default_universe", "csi300"),
            "default_feature_set_id": runtime.get("default_feature_set_id", "v1"),
            "default_label_id": runtime.get("default_label_id", "return_5d"),
            "train_queue_name": runtime.get("train_queue_name", "qlib_train"),
            "infer_queue_name": runtime.get("infer_queue_name", "qlib_infer"),
            "allow_auto_activate": bool(runtime.get("allow_auto_activate")),
            "alpha_fixed_provider": settings_obj.alpha_fixed_provider or "",
            "alpha_pool_mode": settings_obj.alpha_pool_mode,
            "active_model": (
                {
                    "model_name": active_model.model_name,
                    "artifact_hash": active_model.artifact_hash,
                    "model_type": active_model.model_type,
                    "feature_set_id": active_model.feature_set_id,
                    "label_id": active_model.label_id,
                    "updated_at": active_model.updated_at.isoformat(),
                }
                if active_model is not None
                else None
            ),
            "training_task_running": training_task_running,
            "latest_run_status": latest_run.status if latest_run is not None else None,
            "validation_errors": validation_errors,
        }

    def update_runtime_config(self, data: Mapping[str, Any]) -> dict[str, Any]:
        settings_obj = self.get_system_settings()
        update_fields: list[str] = []
        for request_key, model_field in self.RUNTIME_FIELD_MAP.items():
            if request_key not in data:
                continue
            setattr(settings_obj, model_field, data[request_key])
            update_fields.append(model_field)
        if update_fields:
            settings_obj.full_clean()
            update_fields.append("updated_at")
            settings_obj.save(update_fields=update_fields)
        return self.build_runtime_config_payload()


class QlibTrainingProfileRepository:
    """Training profile persistence."""

    def list_profiles(self) -> list[QlibTrainingProfileModel]:
        return list(QlibTrainingProfileModel._default_manager.order_by("name", "profile_key"))

    def get_profile(self, *, profile_id: int | None = None, profile_key: str | None = None):
        queryset = QlibTrainingProfileModel._default_manager
        if profile_id is not None:
            return queryset.filter(id=profile_id).first()
        if profile_key:
            return queryset.filter(profile_key=profile_key).first()
        return None

    def save_profile(self, data: Mapping[str, Any]) -> QlibTrainingProfileModel:
        instance = self.get_profile(
            profile_id=data.get("id"),
            profile_key=str(data.get("profile_key") or ""),
        )
        if instance is None:
            instance = QlibTrainingProfileModel(
                profile_key=str(data["profile_key"]),
            )
        for field in (
            "profile_key",
            "name",
            "model_name",
            "model_type",
            "universe",
            "start_date",
            "end_date",
            "feature_set_id",
            "label_id",
            "learning_rate",
            "epochs",
            "model_params",
            "extra_train_config",
            "activate_after_train",
            "is_active",
            "notes",
        ):
            if field in data:
                setattr(instance, field, data[field])
        instance.full_clean()
        instance.save()
        return instance


class QlibTrainingRunRepository:
    """Training run persistence and status transitions."""

    def list_runs(self, *, limit: int = 50) -> list[QlibTrainingRunModel]:
        return list(QlibTrainingRunModel._default_manager.order_by("-requested_at", "-id")[:limit])

    def get_run(self, run_id: str) -> QlibTrainingRunModel | None:
        return QlibTrainingRunModel._default_manager.filter(run_id=run_id).select_related(
            "profile",
            "requested_by",
        ).first()

    def has_active_run(self) -> bool:
        return QlibTrainingRunModel._default_manager.filter(
            status__in=[
                QlibTrainingRunModel.STATUS_PENDING,
                QlibTrainingRunModel.STATUS_RUNNING,
            ]
        ).exists()

    @transaction.atomic
    def create_run(
        self,
        *,
        profile: QlibTrainingProfileModel | None,
        requested_by,
        model_name: str,
        model_type: str,
        resolved_train_config: dict[str, Any],
    ) -> QlibTrainingRunModel:
        return QlibTrainingRunModel._default_manager.create(
            profile=profile,
            requested_by=requested_by,
            model_name=model_name,
            model_type=model_type,
            resolved_train_config=resolved_train_config,
            status=QlibTrainingRunModel.STATUS_PENDING,
        )

    def attach_task(self, *, run_id: str, celery_task_id: str) -> QlibTrainingRunModel:
        run = QlibTrainingRunModel._default_manager.get(run_id=run_id)
        run.celery_task_id = celery_task_id
        run.save(update_fields=["celery_task_id", "updated_at"])
        return run

    def mark_running(self, *, run_id: str, celery_task_id: str = "") -> QlibTrainingRunModel:
        run = QlibTrainingRunModel._default_manager.get(run_id=run_id)
        run.status = QlibTrainingRunModel.STATUS_RUNNING
        run.started_at = timezone.now()
        if celery_task_id:
            run.celery_task_id = celery_task_id
        run.error_message = ""
        run.save(update_fields=["status", "started_at", "celery_task_id", "error_message", "updated_at"])
        return run

    def mark_succeeded(
        self,
        *,
        run_id: str,
        result_model_name: str,
        result_artifact_hash: str,
        result_metrics: dict[str, Any],
        registry_result: dict[str, Any],
    ) -> QlibTrainingRunModel:
        run = QlibTrainingRunModel._default_manager.get(run_id=run_id)
        run.status = QlibTrainingRunModel.STATUS_SUCCEEDED
        run.finished_at = timezone.now()
        run.result_model_name = result_model_name
        run.result_artifact_hash = result_artifact_hash
        run.result_metrics = result_metrics
        run.registry_result = registry_result
        run.error_message = ""
        run.save(
            update_fields=[
                "status",
                "finished_at",
                "result_model_name",
                "result_artifact_hash",
                "result_metrics",
                "registry_result",
                "error_message",
                "updated_at",
            ]
        )
        return run

    def mark_failed(self, *, run_id: str, error_message: str) -> QlibTrainingRunModel:
        run = QlibTrainingRunModel._default_manager.get(run_id=run_id)
        run.status = QlibTrainingRunModel.STATUS_FAILED
        run.finished_at = timezone.now()
        run.error_message = error_message
        run.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
        return run


def normalize_train_dates(
    *,
    start_date_value: date | None,
    end_date_value: date | None,
) -> tuple[date | None, date | None]:
    return start_date_value, end_date_value
