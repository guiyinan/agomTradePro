"""Config center application use cases."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from django.db import transaction

from apps.alpha.application.tasks import qlib_train_model
from apps.config_center.application.repository_provider import (
    get_config_center_settings_repository,
    get_qlib_training_profile_repository,
    get_qlib_training_run_repository,
)


class ConflictError(RuntimeError):
    """Raised when concurrent training is rejected."""


class ValidationFailureError(ValueError):
    """Raised when request/runtime validation fails."""


class GetQlibRuntimeConfigUseCase:
    def execute(self) -> dict[str, Any]:
        return get_config_center_settings_repository().build_runtime_config_payload()


class UpdateQlibRuntimeConfigUseCase:
    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        return get_config_center_settings_repository().update_runtime_config(payload)


class ListQlibTrainingProfilesUseCase:
    def execute(self) -> list[Any]:
        return get_qlib_training_profile_repository().list_profiles()


class CreateOrUpdateQlibTrainingProfileUseCase:
    def execute(self, payload: dict[str, Any]):
        return get_qlib_training_profile_repository().save_profile(payload)


class ListQlibTrainingRunsUseCase:
    def execute(self, *, limit: int = 50):
        return get_qlib_training_run_repository().list_runs(limit=limit)


class GetQlibTrainingRunDetailUseCase:
    def execute(self, run_id: str):
        return get_qlib_training_run_repository().get_run(run_id)


class TriggerQlibTrainingUseCase:
    CODE_DEFAULTS = {
        "default_universe": "csi300",
        "default_feature_set_id": "v1",
        "default_label_id": "return_5d",
        "train_queue_name": "qlib_train",
        "allow_auto_activate": False,
    }

    def execute(self, *, actor, payload: dict[str, Any]) -> dict[str, Any]:
        settings_repo = get_config_center_settings_repository()
        profile_repo = get_qlib_training_profile_repository()
        run_repo = get_qlib_training_run_repository()
        runtime_payload = settings_repo.build_runtime_config_payload()

        profile = None
        profile_key = str(payload.get("profile_key") or "").strip()
        if profile_key:
            profile = profile_repo.get_profile(profile_key=profile_key)
            if profile is None:
                raise ValidationFailureError("训练模板不存在")
            if not profile.is_active:
                raise ValidationFailureError("训练模板已停用")

        if not runtime_payload["enabled"]:
            raise ValidationFailureError("Qlib 未启用")

        provider_uri = Path(str(runtime_payload["provider_uri"] or "")).expanduser()
        if not provider_uri.exists():
            raise ValidationFailureError("Qlib provider_uri 路径不存在")

        model_root_raw = str(runtime_payload["model_root"] or "").strip()
        if not model_root_raw:
            raise ValidationFailureError("Qlib model_root 未配置")
        model_root = Path(model_root_raw).expanduser()
        try:
            model_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValidationFailureError(f"Qlib model_root 无法创建: {exc}") from exc

        runtime_defaults = {
            key: runtime_payload.get(key, value)
            for key, value in self.CODE_DEFAULTS.items()
        }
        profile_defaults = self._profile_defaults(profile)
        request_values = self._request_overrides(payload)
        merged = {
            **runtime_defaults,
            **profile_defaults,
            **request_values,
        }
        resolved_train_config = self._build_train_config(
            runtime_payload=runtime_payload,
            merged=merged,
        )

        start_date_value = resolved_train_config.get("start_date")
        end_date_value = resolved_train_config.get("end_date")
        if start_date_value and end_date_value and start_date_value > end_date_value:
            raise ValidationFailureError("训练开始日期不能晚于结束日期")

        model_name = str(merged.get("model_name") or "").strip()
        model_type = str(merged.get("model_type") or "").strip()
        if not model_name:
            raise ValidationFailureError("model_name 不能为空")
        if not model_type:
            raise ValidationFailureError("model_type 不能为空")

        with transaction.atomic():
            settings_repo.acquire_system_settings_lock()
            if run_repo.has_active_run():
                raise ConflictError("当前已有训练任务处于 PENDING/RUNNING")
            run = run_repo.create_run(
                profile=profile,
                requested_by=actor if getattr(actor, "is_authenticated", False) else None,
                model_name=model_name,
                model_type=model_type,
                resolved_train_config=resolved_train_config,
            )
        resolved_train_config["training_run_id"] = str(run.run_id)

        task = qlib_train_model.apply_async(
            kwargs={
                "model_name": model_name,
                "model_type": model_type,
                "train_config": resolved_train_config,
            },
            queue=str(runtime_payload.get("train_queue_name") or "qlib_train"),
        )
        run_repo.attach_task(run_id=str(run.run_id), celery_task_id=task.id)
        return {
            "run_id": str(run.run_id),
            "status": run.status,
            "task_id": task.id,
            "configured": bool(runtime_payload["configured"]),
            "enabled": bool(runtime_payload["enabled"]),
            "active_model": runtime_payload["active_model"],
            "training_task_running": True,
            "latest_run_status": run.status,
            "validation_errors": runtime_payload["validation_errors"],
            "resolved_train_config": resolved_train_config,
        }

    @staticmethod
    def _profile_defaults(profile) -> dict[str, Any]:
        if profile is None:
            return {}
        return {
            "model_name": profile.model_name,
            "model_type": profile.model_type,
            "universe": profile.universe,
            "start_date": profile.start_date,
            "end_date": profile.end_date,
            "feature_set_id": profile.feature_set_id,
            "label_id": profile.label_id,
            "learning_rate": profile.learning_rate,
            "epochs": profile.epochs,
            "model_params": dict(profile.model_params or {}),
            "extra_train_config": dict(profile.extra_train_config or {}),
            "activate": bool(profile.activate_after_train),
        }

    @staticmethod
    def _request_overrides(payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
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
            "activate",
        }
        return {key: payload[key] for key in allowed if key in payload}

    @staticmethod
    def _build_train_config(*, runtime_payload: dict[str, Any], merged: dict[str, Any]) -> dict[str, Any]:
        extra_train_config = dict(merged.get("extra_train_config") or {})
        start_date_value = merged.get("start_date")
        end_date_value = merged.get("end_date")
        resolved = {
            **extra_train_config,
            "universe": merged.get("universe") or runtime_payload["default_universe"],
            "start_date": (
                start_date_value.isoformat() if isinstance(start_date_value, date) else start_date_value
            ),
            "end_date": (
                end_date_value.isoformat() if isinstance(end_date_value, date) else end_date_value
            ),
            "feature_set_id": merged.get("feature_set_id") or runtime_payload["default_feature_set_id"],
            "label_id": merged.get("label_id") or runtime_payload["default_label_id"],
            "learning_rate": merged.get("learning_rate"),
            "epochs": merged.get("epochs"),
            "model_params": dict(merged.get("model_params") or {}),
            "model_path": runtime_payload["model_root"],
            "activate": bool(
                merged["activate"]
                if "activate" in merged and merged["activate"] is not None
                else runtime_payload["allow_auto_activate"]
            ),
            "source": extra_train_config.get("source", "config_center_trigger"),
        }
        return resolved
