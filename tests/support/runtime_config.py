"""Test helpers for complete canonical runtime groups."""

from __future__ import annotations

import os

from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.config_center.infrastructure.repositories import ConfigCenterSettingsRepository
from apps.data_center.application.interface_services import save_provider_settings_payload

_TEST_AUDIT_AUTHORITY_SELECTOR: dict[str, object] = {
    "actor_source_id": "account-test-actor-source",
    "actor_source_version": "v1",
    "actor_content_hash": "a" * 64,
    "scope_source_id": "account-test-scope-source",
    "scope_source_version": "v1",
    "scope_content_hash": "b" * 64,
}


def configure_critical_runtime() -> None:
    """Seed explicit fail-closed audit values for an isolated test database."""

    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    environment = "production" if settings_module.endswith(".production") else "development"
    activate_runtime_profile_patch(
        environment=environment,
        patch={
            "data_center.provider.failover_tolerance": 0.01,
            "audit.system_event.mode": "off",
            "audit.system_event.outbox_enabled": False,
            "audit.system_event.authority_selector": _TEST_AUDIT_AUTHORITY_SELECTOR,
        },
        actor="test-runtime-bootstrap",
        reason="seed complete critical runtime values for account tests",
    )


def configure_account_runtime(
    *,
    allow_token_plaintext_view: bool = True,
    default_mcp_enabled: bool = True,
) -> None:
    """Publish complete critical and account groups for an isolated test database."""

    configure_critical_runtime()
    save_provider_settings_payload(
        default_source="akshare",
        enable_failover=True,
        failover_tolerance=0.01,
        actor="test-runtime-bootstrap",
    )
    ConfigCenterSettingsRepository().update_system_governance(
        {
            "require_user_approval": True,
            "auto_approve_first_admin": False,
            "default_mcp_enabled": default_mcp_enabled,
            "allow_token_plaintext_view": allow_token_plaintext_view,
            "user_agreement_content": "",
            "risk_warning_content": "",
            "notes": "test canonical account runtime",
        },
        actor="test-runtime-bootstrap",
    )


__all__ = ["configure_account_runtime", "configure_critical_runtime"]
