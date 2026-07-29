"""Compatibility aggregation for AI/MCP identity and access metadata."""

from __future__ import annotations

from .tui_metadata_runtime_injection_account_self_service import (
    RUNTIME_ACCOUNT_SELF_SERVICE_ACTIONS,
    RUNTIME_ACCOUNT_SELF_SERVICE_SCREEN,
)
from .tui_metadata_runtime_injection_ai_quotas import (
    RUNTIME_AI_QUOTA_ACTIONS,
    RUNTIME_AI_USER_QUOTAS_SCREEN,
)
from .tui_metadata_runtime_injection_ai_system_providers import (
    RUNTIME_AI_SYSTEM_PROVIDER_ACTIONS,
    RUNTIME_AI_SYSTEM_PROVIDERS_SCREEN,
)
from .tui_metadata_runtime_injection_ai_user_providers import (
    RUNTIME_AI_MY_PROVIDERS_SCREEN,
    RUNTIME_AI_OPS_MODULE,
    RUNTIME_AI_USER_PROVIDER_ACTIONS,
)
from .tui_metadata_runtime_injection_mcp_access import (
    RUNTIME_MCP_ACCESS_ACTIONS,
    RUNTIME_MCP_ACCESS_MODULE,
    RUNTIME_MCP_ADMIN_ACCESS_SCREEN,
    RUNTIME_MCP_SELF_SERVICE_SCREEN,
)
from .tui_metadata_runtime_injection_user_access import (
    RUNTIME_USER_ACCESS_ACTIONS,
    RUNTIME_USER_ACCESS_GOVERNANCE_SCREEN,
)

__all__ = [
    "RUNTIME_AI_MY_PROVIDERS_SCREEN",
    "RUNTIME_AI_OPS_MODULE",
    "RUNTIME_AI_SYSTEM_PROVIDERS_SCREEN",
    "RUNTIME_AI_USER_QUOTAS_SCREEN",
    "RUNTIME_ACCOUNT_SELF_SERVICE_SCREEN",
    "RUNTIME_IDENTITY_ACCESS_ACTIONS",
    "RUNTIME_MCP_ACCESS_MODULE",
    "RUNTIME_MCP_ADMIN_ACCESS_SCREEN",
    "RUNTIME_MCP_SELF_SERVICE_SCREEN",
    "RUNTIME_USER_ACCESS_GOVERNANCE_SCREEN",
]

_RAW_IDENTITY_ACCESS_ACTIONS = (
    *RUNTIME_MCP_ACCESS_ACTIONS,
    *RUNTIME_AI_USER_PROVIDER_ACTIONS,
    *RUNTIME_AI_SYSTEM_PROVIDER_ACTIONS,
    *RUNTIME_AI_QUOTA_ACTIONS,
    *RUNTIME_USER_ACCESS_ACTIONS,
    *RUNTIME_ACCOUNT_SELF_SERVICE_ACTIONS,
)

RUNTIME_IDENTITY_ACCESS_ACTIONS = tuple(
    {
        **action,
        "module_key": (
            "mcp-access"
            if action["screen_key"] == "capability-router.self-service"
            else (
                "mcp-governance"
                if action["screen_key"] == "capability-router.admin-access"
                else action["module_key"]
            )
        ),
    }
    for action in _RAW_IDENTITY_ACCESS_ACTIONS
)
