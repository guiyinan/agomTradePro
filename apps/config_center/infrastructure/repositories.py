"""Infrastructure repositories for config center."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from django.apps import apps as django_apps
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.config_center.application.runtime_public import (
    activate_runtime_profile_patch,
    get_active_domain_runtime_config,
    get_active_qlib_runtime_config,
)
from apps.config_center.domain.entities import (
    AlphaUniverseConfig,
    DecisionRuntimeState,
    DecisionRuntimeStatus,
)
from apps.config_center.infrastructure.models import (
    AlphaUniverseConfigModel,
    QlibTrainingProfileModel,
    QlibTrainingRunModel,
    SystemSettingsModel,
)
from apps.data_center.application.public import get_provider_settings_payload


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

    RUNTIME_DEFINITION_MAP = {
        "enabled": "alpha.qlib.enabled",
        "provider_uri": "alpha.qlib.provider_uri",
        "region": "alpha.qlib.region",
        "model_root": "alpha.qlib.model_path",
        "default_universe": "alpha.qlib.default_universe",
        "default_feature_set_id": "alpha.qlib.default_feature_set_id",
        "default_label_id": "alpha.qlib.default_label_id",
        "train_queue_name": "alpha.qlib.train_queue_name",
        "infer_queue_name": "alpha.qlib.infer_queue_name",
        "allow_auto_activate": "alpha.qlib.allow_auto_activate",
        "alpha_fixed_provider": "alpha.runtime.fixed_provider",
        "alpha_pool_mode": "alpha.runtime.pool_mode",
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

    @staticmethod
    def _runtime_environment() -> str:
        """Resolve the Config Center profile environment from Django settings."""

        module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
        return "production" if module.endswith(".production") else "development"

    @staticmethod
    def _legacy_runtime_values(settings_obj: SystemSettingsModel) -> dict[str, object]:
        """Build explicit one-time compatibility values for profile bootstrap."""

        provider = get_provider_settings_payload()
        return {
            "data_center.provider.default_source": str(
                provider.get("default_source") or "akshare"
            ),
            "data_center.provider.failover_tolerance": provider.get("failover_tolerance"),
            "data_center.provider.enable_failover": provider.get("enable_failover"),
            "alpha.qlib.enabled": bool(settings_obj.qlib_enabled),
            "alpha.qlib.provider_uri": str(settings_obj.qlib_provider_uri or ""),
            "alpha.qlib.region": str(settings_obj.qlib_region or "CN"),
            "alpha.qlib.model_path": str(settings_obj.qlib_model_path or ""),
            "alpha.qlib.default_universe": str(settings_obj.qlib_default_universe or "csi300"),
            "alpha.qlib.default_feature_set_id": str(
                settings_obj.qlib_default_feature_set_id or "v1"
            ),
            "alpha.qlib.default_label_id": str(settings_obj.qlib_default_label_id or "return_5d"),
            "alpha.qlib.train_queue_name": str(settings_obj.qlib_train_queue_name or "qlib_train"),
            "alpha.qlib.infer_queue_name": str(settings_obj.qlib_infer_queue_name or "qlib_infer"),
            "alpha.qlib.allow_auto_activate": bool(settings_obj.qlib_allow_auto_activate),
            "alpha.runtime.fixed_provider": str(settings_obj.alpha_fixed_provider or ""),
            "alpha.runtime.pool_mode": str(
                settings_obj.alpha_pool_mode or SystemSettingsModel.ALPHA_POOL_MODE_STRICT_VALUATION
            ),
            "config_center.market.color_convention": str(
                settings_obj.market_color_convention or "cn_a_share"
            ),
            "config_center.market.benchmark_code_map": dict(settings_obj.benchmark_code_map or {}),
            "config_center.market.asset_proxy_code_map": dict(
                settings_obj.asset_proxy_code_map or {}
            ),
        }

    def get_system_settings_for_read(self) -> SystemSettingsModel:
        settings_obj = SystemSettingsModel._default_manager.filter(pk=1).first()
        if settings_obj is not None:
            return settings_obj
        return SystemSettingsModel(pk=1)

    def acquire_system_settings_lock(self) -> SystemSettingsModel:
        settings_obj = SystemSettingsModel.get_settings()
        return SystemSettingsModel._default_manager.select_for_update().get(pk=settings_obj.pk)

    def get_decision_runtime_state(self) -> DecisionRuntimeState:
        """Return the persisted global decision gate without creating a row."""

        settings_obj = self.get_system_settings_for_read()
        raw_status = str(settings_obj.decision_runtime_status or "active")
        try:
            status = DecisionRuntimeStatus(raw_status)
        except ValueError:
            status = DecisionRuntimeStatus.BLOCKED
        reason = str(settings_obj.decision_runtime_reason or "")
        if status is DecisionRuntimeStatus.BLOCKED and not reason:
            reason = "配置中心包含未知决策运行状态。"
        return DecisionRuntimeState(
            status=status,
            reason=reason,
            changed_at=settings_obj.decision_runtime_changed_at,
            changed_by=str(settings_obj.decision_runtime_changed_by or ""),
            release_ref=str(settings_obj.decision_runtime_release_ref or ""),
            expected_resume_at=settings_obj.decision_runtime_expected_resume_at,
        )

    def set_decision_runtime_state(
        self,
        state: DecisionRuntimeState,
    ) -> DecisionRuntimeState:
        """Persist the global decision gate under a row lock."""

        with transaction.atomic():
            settings_obj = self.acquire_system_settings_lock()
            settings_obj.decision_runtime_status = state.status.value
            settings_obj.decision_runtime_reason = state.reason
            settings_obj.decision_runtime_changed_at = state.changed_at
            settings_obj.decision_runtime_changed_by = state.changed_by
            settings_obj.decision_runtime_release_ref = state.release_ref
            settings_obj.decision_runtime_expected_resume_at = state.expected_resume_at
            settings_obj.save(
                update_fields=[
                    "decision_runtime_status",
                    "decision_runtime_reason",
                    "decision_runtime_changed_at",
                    "decision_runtime_changed_by",
                    "decision_runtime_release_ref",
                    "decision_runtime_expected_resume_at",
                    "updated_at",
                ]
            )
        return self.get_decision_runtime_state()

    def build_runtime_config_payload(self) -> dict[str, Any]:
        environment = self._runtime_environment()
        typed_runtime = get_active_qlib_runtime_config(environment)
        typed_domain = get_active_domain_runtime_config(environment)
        runtime = dict(typed_runtime or {})
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
        if typed_runtime is None:
            validation_errors.append("runtime_config_snapshot_unavailable")
        provider_path = Path(str(runtime.get("provider_uri") or "")).expanduser()
        model_root = Path(str(runtime.get("model_path") or "")).expanduser()
        if typed_runtime is not None and runtime.get("enabled") and not provider_path.exists():
            validation_errors.append("Qlib provider_uri 路径不存在")
        if typed_runtime is not None and not str(runtime.get("model_path") or "").strip():
            validation_errors.append("Qlib model_root 未配置")
        elif typed_runtime is not None and model_root.exists() and not model_root.is_dir():
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
            "region": runtime.get("region", ""),
            "model_root": runtime.get("model_path", ""),
            "default_universe": runtime.get("default_universe", ""),
            "default_feature_set_id": runtime.get("default_feature_set_id", ""),
            "default_label_id": runtime.get("default_label_id", ""),
            "train_queue_name": runtime.get("train_queue_name", ""),
            "infer_queue_name": runtime.get("infer_queue_name", ""),
            "allow_auto_activate": bool(runtime.get("allow_auto_activate")),
            "alpha_fixed_provider": (
                typed_domain.get("alpha_fixed_provider", "") if typed_domain else ""
            ),
            "alpha_pool_mode": (typed_domain.get("alpha_pool_mode", "") if typed_domain else ""),
            "status": "active" if typed_runtime is not None else "blocked",
            "source": "config_center_runtime_profile",
            "must_not_use_for_decision": typed_runtime is None,
            "blocked_reason": (
                "" if typed_runtime is not None else "runtime_config_snapshot_unavailable"
            ),
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

    def update_runtime_config(
        self,
        data: Mapping[str, Any],
        *,
        actor: str = "config-center",
    ) -> dict[str, Any]:
        settings_obj = self.get_system_settings_for_read()
        patch: dict[str, object] = {}
        for request_key, definition_key in self.RUNTIME_DEFINITION_MAP.items():
            if request_key not in data:
                continue
            patch[definition_key] = data[request_key]
        if patch:
            activate_runtime_profile_patch(
                environment=self._runtime_environment(),
                patch=patch,
                bootstrap_values=self._legacy_runtime_values(settings_obj),
                actor=str(actor or "config-center"),
                reason="Qlib/Alpha runtime configuration updated",
            )
        return self.build_runtime_config_payload()

    def build_system_governance_payload(self) -> dict[str, Any]:
        """Return the administrator-facing global settings contract."""

        settings_obj = self.get_system_settings_for_read()
        typed = get_active_domain_runtime_config(self._runtime_environment())
        payload = {
            field_name: getattr(settings_obj, field_name)
            for field_name in self.SYSTEM_GOVERNANCE_FIELDS
        }
        if typed is not None:
            payload.update(
                {
                    "market_color_convention": typed["market_color_convention"],
                    "alpha_pool_mode": typed["alpha_pool_mode"],
                    "benchmark_code_map": typed["benchmark_code_map"],
                    "asset_proxy_code_map": typed["asset_proxy_code_map"],
                }
            )
        convention = str(payload.get("market_color_convention") or "cn_a_share")
        payload.update(
            {
                "market_color_label": (
                    "美股绿涨红跌" if convention == "us_market" else "A股红涨绿跌"
                ),
                "updated_at": settings_obj.updated_at,
            }
        )
        return payload

    def update_system_governance(
        self,
        data: Mapping[str, Any],
        *,
        actor: str = "config-center",
    ) -> dict[str, Any]:
        """Persist the explicit global-settings allowlist and return refreshed state."""

        settings_obj = self.get_system_settings_for_read()
        update_fields: list[str] = []
        runtime_patch: dict[str, object] = {}
        runtime_field_map = {
            "market_color_convention": "config_center.market.color_convention",
            "alpha_pool_mode": "alpha.runtime.pool_mode",
            "benchmark_code_map": "config_center.market.benchmark_code_map",
            "asset_proxy_code_map": "config_center.market.asset_proxy_code_map",
        }
        for field_name in self.SYSTEM_GOVERNANCE_FIELDS:
            if field_name not in data:
                continue
            if field_name in runtime_field_map:
                runtime_patch[runtime_field_map[field_name]] = data[field_name]
                continue
            setattr(settings_obj, field_name, data[field_name])
            update_fields.append(field_name)
        if update_fields:
            persisted_settings = self.get_system_settings()
            for field_name in update_fields:
                setattr(persisted_settings, field_name, data[field_name])
            persisted_settings.full_clean()
            update_fields.append("updated_at")
            persisted_settings.save(update_fields=update_fields)
        if runtime_patch:
            activate_runtime_profile_patch(
                environment=self._runtime_environment(),
                patch=runtime_patch,
                bootstrap_values=self._legacy_runtime_values(settings_obj),
                actor=str(actor or "config-center"),
                reason="Global runtime governance configuration updated",
            )
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

    def get_domain_by_universe_id(
        self,
        universe_id: str,
    ) -> AlphaUniverseConfig | None:
        model = self.get_by_universe_id(universe_id)
        return model.to_domain() if model is not None and model.is_active else None

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
        if model.source_type == AlphaUniverseConfigModel.SOURCE_TUSHARE_INDEX:
            return []
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
