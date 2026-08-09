"""Test helpers for complete canonical runtime groups."""

from __future__ import annotations

from apps.config_center.infrastructure.repositories import ConfigCenterSettingsRepository
from apps.data_center.application.interface_services import save_provider_settings_payload


def configure_account_runtime(
    *,
    allow_token_plaintext_view: bool = True,
    default_mcp_enabled: bool = True,
) -> None:
    """Publish the complete account group without relying on a legacy singleton."""

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


__all__ = ["configure_account_runtime"]
