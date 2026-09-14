"""Explicit Config Center resolution for financial response retention."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from apps.config_center.application.public import (
    get_runtime_config_value,
    resolve_config_secret,
)
from apps.config_center.application.runtime_public import get_active_runtime_secret_ref
from apps.config_center.domain.runtime_config import (
    RuntimeConfigCriticality,
    RuntimeConfigDefinition,
    RuntimeConfigReloadMode,
    RuntimeValueType,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure.financial_response_artifact_repository import (
    FinancialResponseArtifactRepository,
)
from apps.data_center.infrastructure.financial_response_body_store import (
    FinancialResponseArtifactConfigurationError,
    FinancialResponseBodyStore,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository

ARTIFACT_ENABLED_KEY = "data_center.financial_response_artifact.enabled"
ARTIFACT_ROOT_KEY = "data_center.financial_response_artifact.root"
ARTIFACT_ENCRYPTION_KEY = "data_center.financial_response_artifact.encryption_key"
ARTIFACT_KEY_VERSION_KEY = "data_center.financial_response_artifact.encryption_key_version"
ARTIFACT_MAX_BODY_BYTES_KEY = "data_center.financial_response_artifact.max_body_bytes"


@dataclass(frozen=True, slots=True)
class FinancialResponseArtifactRuntimeConfig:
    """Validated settings required to construct an encrypted body store."""

    root: Path
    encryption_key: bytes
    encryption_key_ref: str
    encryption_key_version: str
    max_body_bytes: int


def financial_response_artifact_definitions() -> tuple[RuntimeConfigDefinition, ...]:
    """Return registry definitions without supplying operational defaults."""

    return (
        RuntimeConfigDefinition(
            key=ARTIFACT_ENABLED_KEY,
            namespace="data_center.financial_response_artifact",
            owner_app="data_center",
            value_type=RuntimeValueType.BOOL,
            criticality=RuntimeConfigCriticality.CRITICAL,
            reload_mode=RuntimeConfigReloadMode.RESTART_REQUIRED,
            description="Explicitly enable encrypted financial response retention.",
        ),
        RuntimeConfigDefinition(
            key=ARTIFACT_ROOT_KEY,
            namespace="data_center.financial_response_artifact",
            owner_app="data_center",
            value_type=RuntimeValueType.STRING,
            criticality=RuntimeConfigCriticality.CRITICAL,
            reload_mode=RuntimeConfigReloadMode.RESTART_REQUIRED,
            description="Explicit mounted root for encrypted financial response artifacts.",
        ),
        RuntimeConfigDefinition(
            key=ARTIFACT_ENCRYPTION_KEY,
            namespace="data_center.financial_response_artifact",
            owner_app="data_center",
            value_type=RuntimeValueType.STRING,
            criticality=RuntimeConfigCriticality.CRITICAL,
            reload_mode=RuntimeConfigReloadMode.RESTART_REQUIRED,
            secret=True,
            description="Config Center secret reference for the Fernet key.",
        ),
        RuntimeConfigDefinition(
            key=ARTIFACT_KEY_VERSION_KEY,
            namespace="data_center.financial_response_artifact",
            owner_app="data_center",
            value_type=RuntimeValueType.STRING,
            criticality=RuntimeConfigCriticality.CRITICAL,
            reload_mode=RuntimeConfigReloadMode.RESTART_REQUIRED,
            description="Operator supplied encryption key version.",
        ),
        RuntimeConfigDefinition(
            key=ARTIFACT_MAX_BODY_BYTES_KEY,
            namespace="data_center.financial_response_artifact",
            owner_app="data_center",
            value_type=RuntimeValueType.BYTES,
            criticality=RuntimeConfigCriticality.CRITICAL,
            reload_mode=RuntimeConfigReloadMode.RESTART_REQUIRED,
            constraints={"minimum": 1},
            description="Explicit maximum captured response body size in bytes.",
        ),
    )


def resolve_financial_response_artifact_config(
    *, environment: str | None = None
) -> FinancialResponseArtifactRuntimeConfig | None:
    """Resolve the complete enabled artifact configuration through Config Center.

    A missing or explicitly disabled switch preserves the legacy provider path.
    Once enabled, every setting and the secret value must be present and valid;
    this function never falls back to process environment variables or a local
    plaintext key.
    """

    resolved_environment = _environment(environment)
    enabled = get_runtime_config_value(ARTIFACT_ENABLED_KEY, environment=resolved_environment)
    if enabled is None:
        return None
    if not isinstance(enabled, bool):
        raise FinancialResponseArtifactConfigurationError(
            "金融响应原件开关配置无效。", code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID"
        )
    if not enabled:
        return None
    root = _required_runtime_text(ARTIFACT_ROOT_KEY, resolved_environment)
    key_version = _required_runtime_text(ARTIFACT_KEY_VERSION_KEY, resolved_environment)
    max_body_bytes = _required_positive_int(
        get_runtime_config_value(
            ARTIFACT_MAX_BODY_BYTES_KEY,
            environment=resolved_environment,
        ),
        ARTIFACT_MAX_BODY_BYTES_KEY,
    )
    key_ref = get_active_runtime_secret_ref(
        environment=resolved_environment,
        definition_key=ARTIFACT_ENCRYPTION_KEY,
    )
    if key_ref is None or not key_ref.strip():
        raise FinancialResponseArtifactConfigurationError(
            "金融响应原件加密密钥引用未配置。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        )
    try:
        key_text = resolve_config_secret(key_ref)
        encryption_key = key_text.encode("ascii")
    except (LookupError, OSError, RuntimeError, UnicodeError, ValueError) as exc:
        raise FinancialResponseArtifactConfigurationError(
            "金融响应原件加密密钥不可用。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        ) from exc
    return FinancialResponseArtifactRuntimeConfig(
        root=Path(root),
        encryption_key=encryption_key,
        encryption_key_ref=key_ref.strip(),
        encryption_key_version=key_version,
        max_body_bytes=max_body_bytes,
    )


def build_financial_response_artifact_repository(
    provider: ProviderConfig,
    *,
    environment: str | None = None,
) -> FinancialResponseArtifactRepository | None:
    """Build retention infrastructure for an explicitly enabled Tushare row."""

    if provider.source_type.casefold() != "tushare":
        return None
    runtime = resolve_financial_response_artifact_config(environment=environment)
    if runtime is None:
        return None
    if provider.id is None or isinstance(provider.id, bool) or provider.id <= 0:
        raise FinancialResponseArtifactConfigurationError(
            "金融响应原件 provider 标识无效。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        )
    _require_https_url(provider.http_url)
    store = FinancialResponseBodyStore(
        runtime.root,
        encryption_key=runtime.encryption_key,
        encryption_key_ref=runtime.encryption_key_ref,
        encryption_key_version=runtime.encryption_key_version,
        max_body_bytes=runtime.max_body_bytes,
    )
    return FinancialResponseArtifactRepository(store, RawAuditRepository())


def _environment(environment: str | None) -> str:
    """Resolve the existing Config Center environment convention."""

    candidate = str(environment or "").strip()
    if candidate:
        return candidate
    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    return "production" if settings_module.endswith(".production") else "development"


def _required_runtime_text(key: str, environment: str) -> str:
    """Read one required non-empty runtime string."""

    value = get_runtime_config_value(key, environment=environment)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise FinancialResponseArtifactConfigurationError(
            "金融响应原件文本配置无效。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        )
    if any(ord(character) < 32 for character in value):
        raise FinancialResponseArtifactConfigurationError(
            "金融响应原件文本配置无效。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        )
    if key == ARTIFACT_ROOT_KEY and not Path(value).is_absolute():
        raise FinancialResponseArtifactConfigurationError(
            "金融响应原件存储根目录必须是绝对路径。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        )
    return value


def _required_positive_int(value: object | None, key: str) -> int:
    """Narrow one explicit positive byte limit."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FinancialResponseArtifactConfigurationError(
            "金融响应原件大小配置无效。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
            details={"definition_key": key},
        )
    return value


def _require_https_url(value: object) -> str:
    """Require an HTTPS origin without credentials or hidden query settings."""

    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise FinancialResponseArtifactConfigurationError(
            "金融响应 provider URL 配置无效。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        )
    parsed = urlsplit(value)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.geturl() != value
    ):
        raise FinancialResponseArtifactConfigurationError(
            "金融响应 provider 必须使用不含凭据的 HTTPS URL。",
            code="FINANCIAL_RESPONSE_ARTIFACT_CONFIG_INVALID",
        )
    return value


__all__ = [
    "ARTIFACT_ENABLED_KEY",
    "ARTIFACT_ENCRYPTION_KEY",
    "ARTIFACT_KEY_VERSION_KEY",
    "ARTIFACT_MAX_BODY_BYTES_KEY",
    "ARTIFACT_ROOT_KEY",
    "FinancialResponseArtifactRuntimeConfig",
    "build_financial_response_artifact_repository",
    "financial_response_artifact_definitions",
    "resolve_financial_response_artifact_config",
]
