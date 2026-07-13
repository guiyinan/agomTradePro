"""config_center runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_list_config_capabilities() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    capabilities = client.config_center.list_capabilities()
    return {
        "capabilities": capabilities,
        "total_count": len(capabilities),
    }


def _fallback_get_qlib_runtime_config() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.config_center.get_qlib_runtime()


def _fallback_list_qlib_training_profiles() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    profiles = client.config_center.list_qlib_training_profiles()
    return {
        "profiles": profiles,
        "total_count": len(profiles),
    }


def _fallback_list_alpha_universes(
    include_inactive: bool = False,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    universes = client.config_center.list_alpha_universes(include_inactive=include_inactive)
    return {
        "universes": universes,
        "total_count": len(universes),
    }


def _fallback_get_alpha_universe_members(
    universe_id: str,
    limit: int = 100,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.config_center.get_alpha_universe_members(
        universe_id,
        limit=limit,
    )


def _fallback_list_qlib_training_runs(
    limit: int = 20,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    runs = client.config_center.list_qlib_training_runs(limit=limit)
    return {
        "runs": runs,
        "total_count": len(runs),
    }


def _fallback_get_qlib_training_run_detail(
    run_id: str,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.config_center.get_qlib_training_run_detail(run_id)


def _fallback_update_qlib_runtime_config(
    enabled: bool | None = None,
    provider_uri: str | None = None,
    region: str | None = None,
    model_root: str | None = None,
    default_universe: str | None = None,
    default_feature_set_id: str | None = None,
    default_label_id: str | None = None,
    train_queue_name: str | None = None,
    infer_queue_name: str | None = None,
    allow_auto_activate: bool | None = None,
    alpha_fixed_provider: str | None = None,
    alpha_pool_mode: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    payload = {
        key: value
        for key, value in {
            "enabled": enabled,
            "provider_uri": provider_uri,
            "region": region,
            "model_root": model_root,
            "default_universe": default_universe,
            "default_feature_set_id": default_feature_set_id,
            "default_label_id": default_label_id,
            "train_queue_name": train_queue_name,
            "infer_queue_name": infer_queue_name,
            "allow_auto_activate": allow_auto_activate,
            "alpha_fixed_provider": alpha_fixed_provider,
            "alpha_pool_mode": alpha_pool_mode,
        }.items()
        if value is not None
    }
    return client.config_center.update_qlib_runtime(payload)


def _fallback_create_data_center_provider(
    name: str,
    source_type: str,
    priority: int = 0,
    is_active: bool = True,
    api_key: str = "",
    http_url: str = "",
    api_endpoint: str = "",
    api_secret: str = "",
    extra_config: dict[str, Any] | None = None,
    description: str = "",
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.create_provider(
        {
            "name": name,
            "source_type": source_type,
            "priority": priority,
            "is_active": is_active,
            "api_key": api_key,
            "http_url": http_url,
            "api_endpoint": api_endpoint,
            "api_secret": api_secret,
            "extra_config": extra_config or {},
            "description": description,
        }
    )


def _fallback_update_data_center_provider(
    provider_id: int,
    name: str | None = None,
    source_type: str | None = None,
    priority: int | None = None,
    is_active: bool | None = None,
    api_key: str | None = None,
    http_url: str | None = None,
    api_endpoint: str | None = None,
    api_secret: str | None = None,
    extra_config: dict[str, Any] | None = None,
    description: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    payload = {
        key: value
        for key, value in {
            "name": name,
            "source_type": source_type,
            "priority": priority,
            "is_active": is_active,
            "api_key": api_key,
            "http_url": http_url,
            "api_endpoint": api_endpoint,
            "api_secret": api_secret,
            "extra_config": extra_config,
            "description": description,
        }.items()
        if value is not None
    }
    return client.data_center.update_provider(provider_id, payload, partial=True)


def _internal_handler_config_center_update_runtime_setting(
    enabled: bool | None = None,
    provider_uri: str | None = None,
    region: str | None = None,
    model_root: str | None = None,
    default_universe: str | None = None,
    default_feature_set_id: str | None = None,
    default_label_id: str | None = None,
    train_queue_name: str | None = None,
    infer_queue_name: str | None = None,
    allow_auto_activate: bool | None = None,
    alpha_fixed_provider: str | None = None,
    alpha_pool_mode: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    updates = {
        key: value
        for key, value in {
            "enabled": enabled,
            "provider_uri": provider_uri,
            "region": region,
            "model_root": model_root,
            "default_universe": default_universe,
            "default_feature_set_id": default_feature_set_id,
            "default_label_id": default_label_id,
            "train_queue_name": train_queue_name,
            "infer_queue_name": infer_queue_name,
            "allow_auto_activate": allow_auto_activate,
            "alpha_fixed_provider": alpha_fixed_provider,
            "alpha_pool_mode": alpha_pool_mode,
        }.items()
        if value is not None
    }
    if not updates:
        raise ValueError("At least one runtime setting update must be provided.")

    if preview_only:
        runtime = client.config_center.get_qlib_runtime()
        return {
            "success": True,
            "preview_only": True,
            "runtime_config_summary": {
                "configured": runtime.get("configured"),
                "enabled": runtime.get("enabled"),
                "provider_uri": runtime.get("provider_uri"),
                "region": runtime.get("region"),
                "model_root": runtime.get("model_root"),
                "default_universe": runtime.get("default_universe"),
                "default_feature_set_id": runtime.get("default_feature_set_id"),
                "default_label_id": runtime.get("default_label_id"),
                "train_queue_name": runtime.get("train_queue_name"),
                "infer_queue_name": runtime.get("infer_queue_name"),
                "allow_auto_activate": runtime.get("allow_auto_activate"),
                "alpha_fixed_provider": runtime.get("alpha_fixed_provider"),
                "alpha_pool_mode": runtime.get("alpha_pool_mode"),
            },
            "update_summary": {
                "field_count": len(updates),
                "fields": sorted(updates),
            },
            "message": ("Preview generated. Confirm to update the selected Qlib runtime setting."),
        }

    return _call_registered_tool("update_qlib_runtime_config", updates)


def _internal_handler_config_center_update_data_center_provider(
    provider_id: int,
    name: str | None = None,
    source_type: str | None = None,
    priority: int | None = None,
    is_active: bool | None = None,
    api_key: str | None = None,
    http_url: str | None = None,
    api_endpoint: str | None = None,
    api_secret: str | None = None,
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
            "source_type": source_type,
            "priority": priority,
            "is_active": is_active,
            "api_key": api_key,
            "http_url": http_url,
            "api_endpoint": api_endpoint,
            "api_secret": api_secret,
            "extra_config": extra_config,
            "description": description,
        }.items()
        if value is not None
    }
    if not updates:
        raise ValueError("At least one provider update must be provided.")

    if preview_only:
        provider = client.data_center.get_provider(provider_id)
        return {
            "success": True,
            "preview_only": True,
            "provider_id": provider_id,
            "provider_summary": {
                "id": provider.get("id"),
                "name": provider.get("name"),
                "source_type": provider.get("source_type"),
                "priority": provider.get("priority"),
                "is_active": provider.get("is_active"),
                "http_url": provider.get("http_url"),
                "api_endpoint": provider.get("api_endpoint"),
                "description": provider.get("description"),
                "extra_config_keys": sorted((provider.get("extra_config") or {}).keys()),
            },
            "update_summary": {
                "field_count": len(updates),
                "fields": sorted(updates),
            },
            "message": ("Preview generated. Confirm to update the selected data-center provider."),
        }

    return _call_registered_tool(
        "update_data_center_provider",
        {
            "provider_id": provider_id,
            **updates,
        },
    )


def _internal_handler_config_center_create_data_center_provider(
    name: str,
    source_type: str,
    priority: int = 0,
    is_active: bool = True,
    api_key: str = "",
    http_url: str = "",
    api_endpoint: str = "",
    api_secret: str = "",
    extra_config: dict[str, Any] | None = None,
    description: str = "",
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    create_arguments = {
        "name": name,
        "source_type": source_type,
        "priority": priority,
        "is_active": is_active,
        "api_key": api_key,
        "http_url": http_url,
        "api_endpoint": api_endpoint,
        "api_secret": api_secret,
        "extra_config": extra_config or {},
        "description": description,
    }

    if preview_only:
        extra_config_value = create_arguments["extra_config"] or {}
        return {
            "success": True,
            "preview_only": True,
            "create_summary": {
                "field_count": len(create_arguments),
                "fields": sorted(create_arguments),
                "name": create_arguments["name"],
                "source_type": create_arguments["source_type"],
                "priority": create_arguments["priority"],
                "is_active": create_arguments["is_active"],
                "http_url": create_arguments["http_url"],
                "api_endpoint": create_arguments["api_endpoint"],
                "description_present": bool(create_arguments["description"]),
                "extra_config_keys": sorted(extra_config_value.keys()),
                "has_api_key": bool(create_arguments["api_key"]),
                "has_api_secret": bool(create_arguments["api_secret"]),
            },
            "message": ("Preview generated. Confirm to create the selected data-center provider."),
        }

    return _call_registered_tool(
        "create_data_center_provider",
        create_arguments,
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "list_config_capabilities": _fallback_list_config_capabilities,
    "get_qlib_runtime_config": _fallback_get_qlib_runtime_config,
    "list_qlib_training_profiles": _fallback_list_qlib_training_profiles,
    "list_alpha_universes": _fallback_list_alpha_universes,
    "get_alpha_universe_members": _fallback_get_alpha_universe_members,
    "list_qlib_training_runs": _fallback_list_qlib_training_runs,
    "get_qlib_training_run_detail": _fallback_get_qlib_training_run_detail,
    "update_qlib_runtime_config": _fallback_update_qlib_runtime_config,
    "create_data_center_provider": _fallback_create_data_center_provider,
    "update_data_center_provider": _fallback_update_data_center_provider,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "config_center_update_runtime_setting": _internal_handler_config_center_update_runtime_setting,
    "config_center_create_data_center_provider": _internal_handler_config_center_create_data_center_provider,
    "config_center_update_data_center_provider": _internal_handler_config_center_update_data_center_provider,
}
