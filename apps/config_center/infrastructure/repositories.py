"""Infrastructure repositories for config center."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from django.apps import apps as django_apps
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.config_center.domain.entities import AlphaUniverseConfig
from apps.config_center.infrastructure.models import (
    AlphaUniverseConfigModel,
    QlibTrainingProfileModel,
    QlibTrainingRunModel,
    SystemSettingsModel,
)


def normalize_alpha_universe_code(raw_code: str) -> str:
    """Normalize user supplied stock code into canonical A-share code."""

    value = str(raw_code or "").strip().upper()
    if not value:
        return ""
    value = value.replace("_", ".")
    if "." in value:
        code, suffix = value.split(".", 1)
        suffix = suffix[:2]
        if code.isdigit() and suffix in {"SH", "SZ", "BJ"}:
            return f"{code.zfill(6)}.{suffix}"
        return value
    if not value.isdigit():
        return value
    code = value.zfill(6)
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return f"{code}.SH"
    if code.startswith(("8", "4", "9")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def normalize_alpha_universe_codes(raw_codes: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    """Normalize and deduplicate a stock code sequence."""

    normalized: list[str] = []
    for raw_code in raw_codes:
        code = normalize_alpha_universe_code(raw_code)
        if code and code not in normalized:
            normalized.append(code)
    return normalized


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
    SYSTEM_GOVERNANCE_FIELDS = (
        "require_user_approval",
        "auto_approve_first_admin",
        "default_mcp_enabled",
        "allow_token_plaintext_view",
        "market_color_convention",
        "alpha_pool_mode",
        "user_agreement_content",
        "risk_warning_content",
        "notes",
        "benchmark_code_map",
        "asset_proxy_code_map",
    )

    def get_system_settings(self) -> SystemSettingsModel:
        return SystemSettingsModel.get_settings()

    def get_system_settings_for_read(self) -> SystemSettingsModel:
        settings_obj = SystemSettingsModel._default_manager.filter(pk=1).first()
        if settings_obj is not None:
            return settings_obj
        return SystemSettingsModel(pk=1)

    def acquire_system_settings_lock(self) -> SystemSettingsModel:
        settings_obj = SystemSettingsModel.get_settings()
        return SystemSettingsModel._default_manager.select_for_update().get(pk=settings_obj.pk)

    def build_runtime_config_payload(self) -> dict[str, Any]:
        settings_obj = self.get_system_settings_for_read()
        runtime = dict(settings_obj.get_runtime_qlib_config_payload())
        qlib_model_registry_model = django_apps.get_model("alpha", "QlibModelRegistryModel")
        active_model = qlib_model_registry_model._default_manager.filter(is_active=True).first()
        training_task_running = QlibTrainingRunModel._default_manager.filter(
            status__in=[
                QlibTrainingRunModel.STATUS_PENDING,
                QlibTrainingRunModel.STATUS_RUNNING,
            ]
        ).exists()
        latest_run = QlibTrainingRunModel._default_manager.order_by("-requested_at", "-id").first()

        validation_errors: list[str] = []
        provider_path = Path(str(runtime.get("provider_uri") or "")).expanduser()
        model_root = Path(str(runtime.get("model_path") or "")).expanduser()
        if runtime.get("enabled") and not provider_path.exists():
            validation_errors.append("Qlib provider_uri 路径不存在")
        if not str(runtime.get("model_path") or "").strip():
            validation_errors.append("Qlib model_root 未配置")
        elif model_root.exists() and not model_root.is_dir():
            validation_errors.append("Qlib model_root 不是目录")

        active_model_updated_at = None
        if active_model is not None:
            active_model_updated_at = getattr(active_model, "activated_at", None) or getattr(
                active_model, "created_at", None
            )

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
                    "updated_at": (
                        active_model_updated_at.isoformat()
                        if active_model_updated_at is not None
                        else None
                    ),
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

    def build_system_governance_payload(self) -> dict[str, Any]:
        """Return the administrator-facing global settings contract."""

        settings_obj = self.get_system_settings_for_read()
        return {
            field_name: getattr(settings_obj, field_name)
            for field_name in self.SYSTEM_GOVERNANCE_FIELDS
        } | {
            "market_color_label": settings_obj.get_market_visual_tokens()["label"],
            "updated_at": settings_obj.updated_at,
        }

    def update_system_governance(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Persist the explicit global-settings allowlist and return refreshed state."""

        settings_obj = self.get_system_settings()
        update_fields: list[str] = []
        for field_name in self.SYSTEM_GOVERNANCE_FIELDS:
            if field_name not in data:
                continue
            setattr(settings_obj, field_name, data[field_name])
            update_fields.append(field_name)
        if update_fields:
            settings_obj.full_clean()
            update_fields.append("updated_at")
            settings_obj.save(update_fields=update_fields)
        return self.build_system_governance_payload()


class QlibTrainingProfileRepository:
    """Training profile persistence."""

    def list_profiles(self) -> list[QlibTrainingProfileModel]:
        return list(QlibTrainingProfileModel._default_manager.order_by("name", "profile_key"))

    def get_profile(
        self, *, profile_id: int | None = None, profile_key: str | None = None
    ) -> QlibTrainingProfileModel | None:
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


class AlphaUniverseConfigRepository:
    """Alpha/Qlib universe config persistence and resolution."""

    def list_configs(self, *, include_inactive: bool = False) -> list[AlphaUniverseConfigModel]:
        queryset = AlphaUniverseConfigModel._default_manager.order_by("universe_id")
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        return list(queryset)

    def get_by_universe_id(self, universe_id: str) -> AlphaUniverseConfigModel | None:
        normalized = str(universe_id or "").strip().lower()
        if not normalized:
            return None
        return AlphaUniverseConfigModel._default_manager.filter(universe_id=normalized).first()

    def save_config(self, config: AlphaUniverseConfig) -> AlphaUniverseConfigModel:
        model, _created = AlphaUniverseConfigModel._default_manager.get_or_create(
            universe_id=config.universe_id.strip().lower(),
            defaults={"name": config.name},
        )
        model.name = config.name
        model.source_type = config.source_type
        model.stock_codes = normalize_alpha_universe_codes(config.stock_codes)
        model.filters = dict(config.filters or {})
        model.is_active = bool(config.is_active)
        model.description = config.description
        model.full_clean()
        model.save()
        return model

    def resolve_member_codes(self, universe_id: str) -> list[str]:
        model = self.get_by_universe_id(universe_id)
        if model is None or not model.is_active:
            return []
        if model.source_type in {
            AlphaUniverseConfigModel.SOURCE_MANUAL,
            AlphaUniverseConfigModel.SOURCE_CSV,
        }:
            return normalize_alpha_universe_codes(list(model.stock_codes or []))
        return self._resolve_data_center_filter_codes(dict(model.filters or {}))

    def _resolve_data_center_filter_codes(self, filters: dict[str, Any]) -> list[str]:
        asset_type = str(filters.get("asset_type") or "stock").strip() or "stock"
        exchanges = [
            str(item).strip().upper()
            for item in filters.get("exchanges", ["SSE", "SZSE", "BSE"])
            if str(item).strip()
        ]
        include_inactive = bool(filters.get("include_inactive", False))
        asset_master_model = django_apps.get_model("data_center", "AssetMasterModel")
        queryset = asset_master_model._default_manager.filter(asset_type=asset_type)
        if exchanges:
            queryset = queryset.filter(exchange__in=exchanges)
        if not include_inactive:
            queryset = queryset.filter(Q(is_active=True) | Q(is_active__isnull=True))
        codes = normalize_alpha_universe_codes(
            list(queryset.values_list("code", flat=True).order_by("code"))
        )
        boards = {
            str(item).strip().lower() for item in filters.get("boards", []) if str(item).strip()
        }
        if not boards:
            return codes
        return [code for code in codes if self._code_matches_any_board(code, boards)]

    @staticmethod
    def _code_matches_any_board(code: str, boards: set[str]) -> bool:
        if "star_market" in boards and code.startswith(("688", "689")) and code.endswith(".SH"):
            return True
        if "chinext" in boards and code.startswith(("300", "301")) and code.endswith(".SZ"):
            return True
        if "bse" in boards and code.endswith(".BJ"):
            return True
        if "sh_main" in boards and code.startswith(("600", "601", "603", "605")):
            return True
        if "sz_main" in boards and code.startswith(("000", "001", "002")):
            return True
        return False


class QlibTrainingRunRepository:
    """Training run persistence and status transitions."""

    def list_runs(self, *, limit: int = 50) -> list[QlibTrainingRunModel]:
        return list(QlibTrainingRunModel._default_manager.order_by("-requested_at", "-id")[:limit])

    def get_run(self, run_id: str) -> QlibTrainingRunModel | None:
        return (
            QlibTrainingRunModel._default_manager.filter(run_id=run_id)
            .select_related(
                "profile",
                "requested_by",
            )
            .first()
        )

    def has_active_run(self) -> bool:
        return QlibTrainingRunModel._default_manager.filter(
            status__in=[
                QlibTrainingRunModel.STATUS_PENDING,
                QlibTrainingRunModel.STATUS_RUNNING,
            ]
        ).exists()

    @transaction.atomic
    def create_pending_run_if_idle(
        self,
        *,
        settings_repo: Any,
        profile: Any,
        requested_by: Any,
        model_name: str,
        model_type: str,
        resolved_train_config: dict[str, Any],
    ) -> QlibTrainingRunModel | None:
        settings_repo.acquire_system_settings_lock()
        if self.has_active_run():
            return None
        return self.create_run(
            profile=profile,
            requested_by=requested_by,
            model_name=model_name,
            model_type=model_type,
            resolved_train_config=resolved_train_config,
        )

    @transaction.atomic
    def create_run(
        self,
        *,
        profile: QlibTrainingProfileModel | None,
        requested_by: Any,
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
        run.save(
            update_fields=["status", "started_at", "celery_task_id", "error_message", "updated_at"]
        )
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
