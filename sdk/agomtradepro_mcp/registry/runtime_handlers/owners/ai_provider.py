"""ai_provider runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_list_ai_providers() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    providers = client.ai_provider.list_providers()
    return {
        "providers": providers,
        "total_count": len(providers),
    }


def _fallback_get_ai_provider(provider_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    try:
        return client.ai_provider.get_provider(provider_id)
    except Exception as exc:
        return {
            "success": False,
            "provider_id": provider_id,
            "error": str(exc),
        }


def _fallback_list_ai_usage_logs(
    provider_id: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    logs = client.ai_provider.list_usage_logs(provider_id=provider_id, status=status)
    return {
        "logs": logs,
        "total_count": len(logs),
    }


def _fallback_update_ai_provider(
    provider_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.ai_provider.update_provider(provider_id, payload)


def _fallback_toggle_ai_provider(
    provider_id: int,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.ai_provider.toggle_provider(provider_id)


def _fallback_create_ai_provider(
    payload: dict[str, Any],
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.ai_provider.create_provider(payload)


def _internal_handler_ai_provider_update_provider(
    provider_id: int,
    name: str | None = None,
    provider_type: str | None = None,
    is_active: bool | None = None,
    priority: int | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    default_model: str | None = None,
    api_mode: str | None = None,
    fallback_enabled: bool | None = None,
    daily_budget_limit: float | None = None,
    monthly_budget_limit: float | None = None,
    extra_config: dict[str, Any] | None = None,
    description: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    updates = {
        key: value
        for key, value in {
            "name": name,
            "provider_type": provider_type,
            "is_active": is_active,
            "priority": priority,
            "base_url": base_url,
            "api_key": api_key,
            "default_model": default_model,
            "api_mode": api_mode,
            "fallback_enabled": fallback_enabled,
            "daily_budget_limit": daily_budget_limit,
            "monthly_budget_limit": monthly_budget_limit,
            "extra_config": extra_config,
            "description": description,
        }.items()
        if value is not None
    }
    if not updates:
        raise ValueError("At least one AI provider update must be provided.")

    if preview_only:
        provider = client.ai_provider.get_provider(provider_id)
        current_extra = provider.get("extra_config") or {}
        return {
            "success": True,
            "preview_only": True,
            "provider_id": provider_id,
            "provider_summary": {
                "id": provider.get("id"),
                "name": provider.get("name"),
                "provider_type": provider.get("provider_type"),
                "scope": provider.get("scope"),
                "is_active": provider.get("is_active"),
                "priority": provider.get("priority"),
                "base_url": provider.get("base_url"),
                "default_model": provider.get("default_model"),
                "api_mode": provider.get("api_mode"),
                "fallback_enabled": provider.get("fallback_enabled"),
                "daily_budget_limit": provider.get("daily_budget_limit"),
                "monthly_budget_limit": provider.get("monthly_budget_limit"),
                "description": provider.get("description"),
                "extra_config_keys": sorted(current_extra.keys()),
            },
            "update_summary": {
                "field_count": len(updates),
                "fields": sorted(updates),
            },
            "message": "Preview generated. Confirm to update the selected AI provider config.",
        }

    return _call_registered_tool(
        "update_ai_provider",
        {
            "provider_id": provider_id,
            "payload": updates,
        },
    )


def _normalize_ai_provider_create_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if "model_name" in normalized and "default_model" not in normalized:
        normalized["default_model"] = normalized.pop("model_name")
    provider_type = str(normalized.get("provider_type", "")).strip().lower()
    if not normalized.get("base_url"):
        default_base_urls = {
            "openai": "https://api.openai.com/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "anthropic": "https://api.anthropic.com",
        }
        normalized["base_url"] = default_base_urls.get(provider_type, "https://api.openai.com/v1")
    return normalized


def _internal_handler_ai_provider_create_provider(
    name: str,
    provider_type: str,
    is_active: bool | None = None,
    priority: int | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    default_model: str | None = None,
    api_mode: str | None = None,
    fallback_enabled: bool | None = None,
    daily_budget_limit: float | None = None,
    monthly_budget_limit: float | None = None,
    extra_config: dict[str, Any] | None = None,
    description: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in {
            "name": name,
            "provider_type": provider_type,
            "is_active": is_active,
            "priority": priority,
            "base_url": base_url,
            "api_key": api_key,
            "default_model": default_model,
            "api_mode": api_mode,
            "fallback_enabled": fallback_enabled,
            "daily_budget_limit": daily_budget_limit,
            "monthly_budget_limit": monthly_budget_limit,
            "extra_config": extra_config,
            "description": description,
        }.items()
        if value is not None
    }
    normalized = _normalize_ai_provider_create_payload(payload)

    if preview_only:
        extra_config_value = normalized.get("extra_config") or {}
        return {
            "success": True,
            "preview_only": True,
            "create_summary": {
                "field_count": len(normalized),
                "fields": sorted(normalized),
                "name": normalized.get("name"),
                "provider_type": normalized.get("provider_type"),
                "base_url": normalized.get("base_url"),
                "default_model": normalized.get("default_model"),
                "api_mode": normalized.get("api_mode"),
                "is_active": normalized.get("is_active"),
                "priority": normalized.get("priority"),
                "fallback_enabled": normalized.get("fallback_enabled"),
                "daily_budget_limit": normalized.get("daily_budget_limit"),
                "monthly_budget_limit": normalized.get("monthly_budget_limit"),
                "description_present": bool(normalized.get("description")),
                "extra_config_keys": sorted(extra_config_value.keys()),
                "has_api_key": "api_key" in normalized and bool(normalized.get("api_key")),
            },
            "message": "Preview generated. Confirm to create the AI provider config.",
        }

    return _call_registered_tool(
        "create_ai_provider",
        {
            "payload": normalized,
        },
    )


def _internal_handler_ai_provider_toggle_provider(
    provider_id: int,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        provider = client.ai_provider.get_provider(provider_id)
        current_extra = provider.get("extra_config") or {}
        current_is_active = bool(provider.get("is_active"))
        return {
            "success": True,
            "preview_only": True,
            "provider_id": provider_id,
            "provider_summary": {
                "id": provider.get("id"),
                "name": provider.get("name"),
                "provider_type": provider.get("provider_type"),
                "scope": provider.get("scope"),
                "is_active": current_is_active,
                "priority": provider.get("priority"),
                "base_url": provider.get("base_url"),
                "default_model": provider.get("default_model"),
                "api_mode": provider.get("api_mode"),
                "fallback_enabled": provider.get("fallback_enabled"),
                "daily_budget_limit": provider.get("daily_budget_limit"),
                "monthly_budget_limit": provider.get("monthly_budget_limit"),
                "description": provider.get("description"),
                "extra_config_keys": sorted(current_extra.keys()),
            },
            "target_is_active": not current_is_active,
            "message": "Preview generated. Confirm to toggle the selected AI provider state.",
        }

    return _call_registered_tool(
        "toggle_ai_provider",
        {
            "provider_id": provider_id,
        },
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "list_ai_providers": _fallback_list_ai_providers,
    "get_ai_provider": _fallback_get_ai_provider,
    "list_ai_usage_logs": _fallback_list_ai_usage_logs,
    "create_ai_provider": _fallback_create_ai_provider,
    "update_ai_provider": _fallback_update_ai_provider,
    "toggle_ai_provider": _fallback_toggle_ai_provider,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "ai_provider_create_provider": _internal_handler_ai_provider_create_provider,
    "ai_provider_update_provider": _internal_handler_ai_provider_update_provider,
    "ai_provider_toggle_provider": _internal_handler_ai_provider_toggle_provider,
}
