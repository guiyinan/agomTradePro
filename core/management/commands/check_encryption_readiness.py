"""Validate that persisted encrypted values are readable in this environment."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.account.infrastructure.models import UserAccessTokenModel
from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.ai_provider.infrastructure.repositories import AIProviderRepository
from apps.config_center.infrastructure.models import SystemSettingsModel


def collect_encryption_readiness() -> dict[str, Any]:
    """Return bounded counts describing encrypted-value recoverability."""

    active_tokens = list(
        UserAccessTokenModel._default_manager.filter(is_active=True).exclude(key_encrypted="")
    )
    provider_repo = AIProviderRepository()
    encrypted_providers = list(AIProviderConfig._default_manager.exclude(api_key_encrypted=""))
    settings_obj = SystemSettingsModel.get_settings()
    result: dict[str, Any] = {
        "status": "ready",
        "active_encrypted_token_count": len(active_tokens),
        "recoverable_token_count": sum(bool(token.reveal_key()) for token in active_tokens),
        "encrypted_provider_count": len(encrypted_providers),
        "usable_provider_count": sum(
            provider_repo.has_usable_api_key(provider) for provider in encrypted_providers
        ),
        "backup_password_present": bool(settings_obj.backup_password_encrypted),
        "backup_password_recoverable": bool(settings_obj.get_backup_password()),
        "smtp_password_present": bool(settings_obj.backup_smtp_password_encrypted),
        "smtp_password_recoverable": bool(settings_obj.get_backup_smtp_password()),
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


class Command(BaseCommand):
    """Check that the configured encryption key matches persisted data."""

    help = "Check encrypted MCP, AI provider, and backup credentials for key mismatch."

    def add_arguments(self, parser) -> None:
        """Register output options."""

        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args: Any, **options: Any) -> None:
        """Print readiness and fail when encrypted data is unreadable."""

        result = collect_encryption_readiness()
        if options["as_json"]:
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            self.stdout.write(
                self.style.SUCCESS("Encryption readiness: ready")
                if result["status"] == "ready"
                else self.style.ERROR("Encryption readiness: blocked")
            )
            for failure in result["failures"]:
                self.stdout.write(f"- {failure}")
        if result["status"] != "ready":
            raise CommandError("Encryption key does not match persisted encrypted data.")
