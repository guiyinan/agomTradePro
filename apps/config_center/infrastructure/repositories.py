"""Infrastructure repositories for config center."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from threading import RLock
from typing import Any

from django.apps import apps as django_apps
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.config_center.application.public import config_secret_present, persist_config_secret
from apps.config_center.application.runtime_public import (
    activate_runtime_profile_patch,
    get_active_account_runtime_config,
    get_active_backup_delivery_config,
    get_active_domain_runtime_config,
    get_active_qlib_runtime_config,
)
from apps.config_center.domain.backup_delivery import (
    BACKUP_ARCHIVE_PASSWORD_SECRET_REF,
    BACKUP_SMTP_PASSWORD_SECRET_REF,
    BackupDeliveryState,
)
from apps.config_center.domain.entities import (
    AlphaUniverseConfig,
    DecisionRuntimeState,
    DecisionRuntimeStatus,
)
from apps.config_center.infrastructure.backup_delivery_models import BackupDeliveryStateModel
from apps.config_center.infrastructure.decision_runtime_models import DecisionRuntimeStateModel
from apps.config_center.infrastructure.models import (
    AlphaUniverseConfigModel,
    QlibTrainingProfileModel,
    QlibTrainingRunLockModel,
    QlibTrainingRunModel,
    SystemSettingsModel,
)
from apps.data_center.application.public import get_provider_settings_payload

_QLIB_TRAINING_RUN_PROCESS_LOCK = RLock()


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
    BACKUP_RUNTIME_FIELD_MAP = {
        "backup_enabled": "backup.enabled",
        "backup_email": "backup.recipient_email",
        "backup_app_base_url": "backup.app_base_url",
        "backup_mail_from_email": "backup.mail_from_email",
        "backup_smtp_host": "backup.smtp_host",
        "backup_smtp_port": "backup.smtp_port",
        "backup_smtp_username": "backup.smtp_username",
        "backup_smtp_use_tls": "backup.smtp_use_tls",
        "backup_smtp_use_ssl": "backup.smtp_use_ssl",
        "backup_interval_days": "backup.interval_days",
        "backup_link_ttl_days": "backup.link_ttl_days",
        "backup_password_hint": "backup.password_hint",
    }
    BACKUP_SECRET_REF_MAP = {
        "backup_archive_password_ref": "backup.archive_password",
        "backup_smtp_password_ref": "backup.smtp_password",
    }
    LEGACY_BACKUP_SECRET_REF_MAP = {
        "backup.archive_password": "system_settings.backup_password_encrypted",
        "backup.smtp_password": "system_settings.backup_smtp_password_encrypted",
    }

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
            "data_center.provider.default_source": str(provider.get("default_source") or "akshare"),
            "data_center.provider.failover_tolerance": provider.get("failover_tolerance"),
            "data_center.provider.enable_failover": provider.get("enable_failover"),
            "account.require_user_approval": bool(settings_obj.require_user_approval),
            "account.auto_approve_first_admin": bool(settings_obj.auto_approve_first_admin),
            "account.default_mcp_enabled": bool(settings_obj.default_mcp_enabled),
            "account.allow_token_plaintext_view": bool(settings_obj.allow_token_plaintext_view),
            "account.user_agreement_content": str(settings_obj.user_agreement_content or ""),
            "account.risk_warning_content": str(settings_obj.risk_warning_content or ""),
            "account.notes": str(settings_obj.notes or ""),
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
            "backup.enabled": bool(settings_obj.backup_enabled),
            "backup.recipient_email": str(settings_obj.backup_email or ""),
            "backup.app_base_url": str(settings_obj.backup_app_base_url or ""),
            "backup.mail_from_email": str(settings_obj.backup_mail_from_email or ""),
            "backup.smtp_host": str(settings_obj.backup_smtp_host or ""),
            "backup.smtp_port": int(settings_obj.backup_smtp_port or 587),
            "backup.smtp_username": str(settings_obj.backup_smtp_username or ""),
            "backup.smtp_use_tls": bool(settings_obj.backup_smtp_use_tls),
            "backup.smtp_use_ssl": bool(settings_obj.backup_smtp_use_ssl),
            "backup.interval_days": int(settings_obj.backup_interval_days or 7),
            "backup.link_ttl_days": int(settings_obj.backup_link_ttl_days or 3),
            "backup.password_hint": str(settings_obj.backup_password_hint or ""),
        }

    @staticmethod
    def _legacy_runtime_secret_refs() -> dict[str, str]:
        """Return new secret refs when migrated, else explicit legacy refs."""

        return {
            definition_key: (
                new_ref
                if ConfigCenterSettingsRepository._config_secret_present(new_ref)
                else ConfigCenterSettingsRepository.LEGACY_BACKUP_SECRET_REF_MAP[definition_key]
            )
            for definition_key, new_ref in (
                ("backup.archive_password", BACKUP_ARCHIVE_PASSWORD_SECRET_REF),
                ("backup.smtp_password", BACKUP_SMTP_PASSWORD_SECRET_REF),
            )
        }

    @staticmethod
    def _config_secret_present(secret_ref: str) -> bool:
        """Read secret presence while preserving explicit bootstrap compatibility."""

        try:
            return config_secret_present(secret_ref)
        except (RuntimeError, ValueError):
            return False

    def build_backup_delivery_payload(self) -> dict[str, Any]:
        """Return typed backup policy plus isolated delivery state.

        During migration, the two secret refs resolve to the encrypted legacy
        columns inside the account-owned compatibility row.  No plaintext is
        placed in the runtime profile or in this payload.
        """

        settings_obj = self.get_system_settings_for_read()
        try:
            typed = get_active_backup_delivery_config(self._runtime_environment())
        except RuntimeError:
            typed = None
        payload: dict[str, Any] = {
            field_name: getattr(settings_obj, field_name)
            for field_name in self.BACKUP_RUNTIME_FIELD_MAP
        }
        legacy_refs = self._legacy_runtime_secret_refs()
        payload.update(
            {
                "backup_archive_password_ref": legacy_refs["backup.archive_password"],
                "backup_smtp_password_ref": legacy_refs["backup.smtp_password"],
            }
        )
        source = "system_settings_compatibility"
        if typed is not None:
            payload.update(
                {field_name: typed[field_name] for field_name in self.BACKUP_RUNTIME_FIELD_MAP}
            )
            payload.update(
                {field_name: typed[field_name] for field_name in self.BACKUP_SECRET_REF_MAP}
            )
            source = "config_center_runtime_profile"

        state = self.get_backup_delivery_state()
        payload.update(
            {
                "backup_last_sent_at": state.last_sent_at,
                "backup_download_token_digest": state.download_token_digest,
                "backup_download_token_expires_at": state.download_token_expires_at,
                "backup_download_consumed_at": state.download_token_consumed_at,
                "policy_source": source,
                "state_source": (
                    "config_center_backup_delivery_state"
                    if BackupDeliveryStateModel._default_manager.filter(pk=1).exists()
                    else "system_settings_compatibility"
                ),
            }
        )
        return payload

    def get_system_settings_for_read(self) -> SystemSettingsModel:
        settings_obj = SystemSettingsModel._default_manager.filter(pk=1).first()
        if settings_obj is not None:
            return settings_obj
        return SystemSettingsModel(pk=1)

    def get_decision_runtime_state(self) -> DecisionRuntimeState:
        """Return the persisted global decision gate and fail closed if absent."""

        state_model = DecisionRuntimeStateModel._default_manager.filter(pk=1).first()
        if state_model is not None:
            return self._decision_runtime_state_from_values(
                status=state_model.status,
                reason=state_model.reason,
                changed_at=state_model.changed_at,
                changed_by=state_model.changed_by,
                release_ref=state_model.release_ref,
                expected_resume_at=state_model.expected_resume_at,
            )

        return DecisionRuntimeState(
            status=DecisionRuntimeStatus.BLOCKED,
            reason="决策运行状态尚未初始化。",
            changed_by="config-center",
        )

    @staticmethod
    def _decision_runtime_state_from_values(
        *,
        status: object,
        reason: object,
        changed_at: Any,
        changed_by: object,
        release_ref: object,
        expected_resume_at: Any,
    ) -> DecisionRuntimeState:
        """Normalize a new or legacy state row into the domain state."""

        raw_status = str(status or "active")
        try:
            status = DecisionRuntimeStatus(raw_status)
        except ValueError:
            status = DecisionRuntimeStatus.BLOCKED
        normalized_reason = str(reason or "")
        if status is DecisionRuntimeStatus.BLOCKED and not normalized_reason:
            normalized_reason = "配置中心包含未知决策运行状态。"
        return DecisionRuntimeState(
            status=status,
            reason=normalized_reason,
            changed_at=changed_at,
            changed_by=str(changed_by or ""),
            release_ref=str(release_ref or ""),
            expected_resume_at=expected_resume_at,
        )

    def set_decision_runtime_state(
        self,
        state: DecisionRuntimeState,
    ) -> DecisionRuntimeState:
        """Persist the global decision gate under a row lock."""

        with transaction.atomic():
            (
                state_model,
                _created,
            ) = DecisionRuntimeStateModel._default_manager.select_for_update().get_or_create(
                pk=1,
                defaults={
                    "status": state.status.value,
                    "reason": state.reason,
                    "changed_at": state.changed_at,
                    "changed_by": state.changed_by,
                    "release_ref": state.release_ref,
                    "expected_resume_at": state.expected_resume_at,
                },
            )
            state_model.status = state.status.value
            state_model.reason = state.reason
            state_model.changed_at = state.changed_at
            state_model.changed_by = state.changed_by
            state_model.release_ref = state.release_ref
            state_model.expected_resume_at = state.expected_resume_at
            state_model.save()
        return self.get_decision_runtime_state()

    def get_backup_delivery_state(self) -> BackupDeliveryState:
        """Read new backup delivery state, falling back to legacy columns once."""

        state_model = BackupDeliveryStateModel._default_manager.filter(pk=1).first()
        if state_model is not None:
            return BackupDeliveryState(
                last_sent_at=state_model.last_sent_at,
                download_token_digest=state_model.download_token_digest,
                download_token_expires_at=state_model.download_token_expires_at,
                download_token_consumed_at=state_model.download_token_consumed_at,
            )
        settings_obj = self.get_system_settings_for_read()
        return BackupDeliveryState(
            last_sent_at=settings_obj.backup_last_sent_at,
            download_token_digest=settings_obj.backup_download_token_digest,
            download_token_expires_at=settings_obj.backup_download_token_expires_at,
            download_token_consumed_at=settings_obj.backup_download_consumed_at,
        )

    @staticmethod
    def _backup_state_defaults(state: BackupDeliveryState) -> dict[str, object]:
        return {
            "last_sent_at": state.last_sent_at,
            "download_token_digest": state.download_token_digest,
            "download_token_expires_at": state.download_token_expires_at,
            "download_token_consumed_at": state.download_token_consumed_at,
        }

    def _ensure_backup_delivery_state_locked(self) -> BackupDeliveryStateModel:
        """Create the new state row from legacy state while holding a DB lock."""

        state_model = (
            BackupDeliveryStateModel._default_manager.select_for_update().filter(pk=1).first()
        )
        if state_model is not None:
            return state_model
        legacy = self.get_system_settings_for_read()
        state_model = BackupDeliveryStateModel._default_manager.create(
            pk=1,
            last_sent_at=legacy.backup_last_sent_at,
            download_token_digest=legacy.backup_download_token_digest,
            download_token_expires_at=legacy.backup_download_token_expires_at,
            download_token_consumed_at=legacy.backup_download_consumed_at,
        )
        return state_model

    def set_backup_delivery_state(self, state: BackupDeliveryState) -> BackupDeliveryState:
        """Persist backup delivery state only in the new owner table."""

        with transaction.atomic():
            state_model = self._ensure_backup_delivery_state_locked()
            for field_name, value in self._backup_state_defaults(state).items():
                setattr(state_model, field_name, value)
            state_model.save(
                update_fields=[
                    "last_sent_at",
                    "download_token_digest",
                    "download_token_expires_at",
                    "download_token_consumed_at",
                    "updated_at",
                ]
            )
        return self.get_backup_delivery_state()

    def record_backup_download_token(
        self,
        *,
        digest: str,
        expires_at: Any,
    ) -> BackupDeliveryState:
        """Replace the active download token under the state row lock."""

        with transaction.atomic():
            state_model = self._ensure_backup_delivery_state_locked()
            state_model.download_token_digest = str(digest)
            state_model.download_token_expires_at = expires_at
            state_model.download_token_consumed_at = None
            state_model.save(
                update_fields=[
                    "download_token_digest",
                    "download_token_expires_at",
                    "download_token_consumed_at",
                    "updated_at",
                ]
            )
        return self.get_backup_delivery_state()

    def mark_backup_delivery_sent(self, sent_at: Any) -> BackupDeliveryState:
        """Record one successfully sent backup notification."""

        with transaction.atomic():
            state_model = self._ensure_backup_delivery_state_locked()
            state_model.last_sent_at = sent_at
            state_model.save(update_fields=["last_sent_at", "updated_at"])
        return self.get_backup_delivery_state()

    def consume_backup_download_token(self, *, digest: str, consumed_at: Any) -> bool:
        """Atomically consume the current token and reject replay/expiry."""

        with transaction.atomic():
            state_model = self._ensure_backup_delivery_state_locked()
            if (
                not str(digest)
                or state_model.download_token_digest != str(digest)
                or state_model.download_token_expires_at is None
                or state_model.download_token_expires_at <= consumed_at
                or state_model.download_token_consumed_at is not None
            ):
                return False
            state_model.download_token_consumed_at = consumed_at
            state_model.save(update_fields=["download_token_consumed_at", "updated_at"])
        return True

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
                bootstrap_secret_refs=self._legacy_runtime_secret_refs(),
                actor=str(actor or "config-center"),
                reason="Qlib/Alpha runtime configuration updated",
            )
        return self.build_runtime_config_payload()

    def build_system_governance_payload(self) -> dict[str, Any]:
        """Return the administrator-facing global settings contract."""

        settings_obj = self.get_system_settings_for_read()
        typed = get_active_domain_runtime_config(self._runtime_environment())
        typed_account = get_active_account_runtime_config(self._runtime_environment())
        payload = {
            field_name: getattr(settings_obj, field_name)
            for field_name in self.SYSTEM_GOVERNANCE_FIELDS
        }
        if typed_account is not None:
            payload.update(typed_account)
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
            "require_user_approval": "account.require_user_approval",
            "auto_approve_first_admin": "account.auto_approve_first_admin",
            "default_mcp_enabled": "account.default_mcp_enabled",
            "allow_token_plaintext_view": "account.allow_token_plaintext_view",
            "user_agreement_content": "account.user_agreement_content",
            "risk_warning_content": "account.risk_warning_content",
            "notes": "account.notes",
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
                bootstrap_secret_refs=self._legacy_runtime_secret_refs(),
                actor=str(actor or "config-center"),
                reason="Global runtime governance configuration updated",
            )
        return self.build_system_governance_payload()

    def update_backup_delivery(
        self,
        data: Mapping[str, Any],
        *,
        actor: str = "config-center",
    ) -> dict[str, Any]:
        """Activate a complete typed backup policy revision.

        Secret material is encrypted in the Config Center secret owner; the
        profile stores only its stable ``secret_ref`` values.
        """

        settings_obj = self.get_system_settings_for_read()
        patch: dict[str, object] = {}
        secret_ref_patch: dict[str, str] = {}
        for field_name, definition_key in self.BACKUP_RUNTIME_FIELD_MAP.items():
            if field_name in data:
                patch[definition_key] = data[field_name]
        secret_inputs = {
            "backup_archive_password": (
                "backup.archive_password",
                BACKUP_ARCHIVE_PASSWORD_SECRET_REF,
            ),
            "backup_smtp_password": (
                "backup.smtp_password",
                BACKUP_SMTP_PASSWORD_SECRET_REF,
            ),
        }
        for field_name, (definition_key, secret_ref) in secret_inputs.items():
            if field_name in data:
                persist_config_secret(secret_ref, data[field_name])
                secret_ref_patch[definition_key] = secret_ref
            elif self._config_secret_present(secret_ref):
                secret_ref_patch[definition_key] = secret_ref
        if not patch and not secret_ref_patch:
            return self.build_backup_delivery_payload()
        activate_runtime_profile_patch(
            environment=self._runtime_environment(),
            patch=patch,
            secret_ref_patch=secret_ref_patch,
            bootstrap_values=self._legacy_runtime_values(settings_obj),
            bootstrap_secret_refs=self._legacy_runtime_secret_refs(),
            actor=str(actor or "config-center"),
            reason="Backup delivery policy updated",
        )
        return self.build_backup_delivery_payload()


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

    def create_pending_run_if_idle(
        self,
        *,
        profile: Any,
        requested_by: Any,
        model_name: str,
        model_type: str,
        resolved_train_config: dict[str, Any],
    ) -> QlibTrainingRunModel | None:
        """Create one pending run while serializing admission across workers."""

        if connection.features.has_select_for_update:
            return self._create_pending_run_under_lock(
                profile=profile,
                requested_by=requested_by,
                model_name=model_name,
                model_type=model_type,
                resolved_train_config=resolved_train_config,
            )

        # SQLite has no row-level SELECT FOR UPDATE. Local development and the
        # contract suite still need deterministic same-process admission; formal
        # production uses PostgreSQL and the persistent row lock below.
        with _QLIB_TRAINING_RUN_PROCESS_LOCK:
            return self._create_pending_run_under_lock(
                profile=profile,
                requested_by=requested_by,
                model_name=model_name,
                model_type=model_type,
                resolved_train_config=resolved_train_config,
            )

    @transaction.atomic
    def _create_pending_run_under_lock(
        self,
        *,
        profile: Any,
        requested_by: Any,
        model_name: str,
        model_type: str,
        resolved_train_config: dict[str, Any],
    ) -> QlibTrainingRunModel | None:
        lock_row, _ = QlibTrainingRunLockModel._default_manager.get_or_create(
            lock_key=QlibTrainingRunLockModel.GLOBAL_LOCK_KEY
        )
        if connection.features.has_select_for_update:
            QlibTrainingRunLockModel._default_manager.select_for_update().get(
                lock_key=lock_row.lock_key
            )
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
