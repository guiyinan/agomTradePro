"""Encryption readiness checks shared by deployment commands."""

from __future__ import annotations

from typing import Any

from apps.account.infrastructure.backup_delivery_projection import (
    get_backup_delivery_payload,
    get_backup_delivery_settings,
)
from apps.account.infrastructure.models import UserAccessTokenModel
from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.ai_provider.infrastructure.repositories import AIProviderRepository
from apps.config_center.application.public import config_secret_present
from apps.config_center.domain.backup_delivery import (
    BACKUP_ARCHIVE_PASSWORD_SECRET_REF,
    BACKUP_SMTP_PASSWORD_SECRET_REF,
)


def collect_encryption_readiness() -> dict[str, Any]:
    """Return bounded counts describing encrypted-value recoverability."""

    active_tokens = list(
        UserAccessTokenModel._default_manager.filter(is_active=True).exclude(key_encrypted="")
    )
    provider_repo = AIProviderRepository()
    encrypted_providers = list(AIProviderConfig._default_manager.exclude(api_key_encrypted=""))
    settings_obj = get_backup_delivery_settings()
    backup_payload = get_backup_delivery_payload()
    result: dict[str, Any] = {
        "status": "ready",
        "active_encrypted_token_count": len(active_tokens),
        "recoverable_token_count": sum(bool(token.reveal_key()) for token in active_tokens),
        "encrypted_provider_count": len(encrypted_providers),
        "usable_provider_count": sum(
            provider_repo.has_usable_api_key(provider) for provider in encrypted_providers
        ),
        "backup_password_present": config_secret_present(BACKUP_ARCHIVE_PASSWORD_SECRET_REF),
        "backup_password_recoverable": bool(settings_obj.archive_password),
        "smtp_password_present": config_secret_present(BACKUP_SMTP_PASSWORD_SECRET_REF),
        "smtp_password_recoverable": bool(settings_obj.smtp_password),
        "backup_policy_source": backup_payload.get("policy_source", "unknown"),
        "backup_state_source": backup_payload.get("state_source", "unknown"),
        "failures": [],
    }
    failures: list[str] = result["failures"]
    if result["active_encrypted_token_count"] and not result["recoverable_token_count"]:
        failures.append("active MCP token ciphertext cannot be decrypted")
    if result["encrypted_provider_count"] and not result["usable_provider_count"]:
        failures.append("AI provider ciphertext cannot be decrypted")
    if result["backup_password_present"] and not result["backup_password_recoverable"]:
        failures.append("backup password ciphertext cannot be decrypted")
    if result["smtp_password_present"] and not result["smtp_password_recoverable"]:
        failures.append("SMTP password ciphertext cannot be decrypted")
    if failures:
        result["status"] = "blocked"
    return result
