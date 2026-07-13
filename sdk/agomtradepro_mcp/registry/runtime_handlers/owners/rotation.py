"""rotation runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_rotation_compute_asset_comparison(
    asset_codes: list[str],
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.rotation.compare_assets(asset_codes)
    if not isinstance(result, dict):
        raise ValueError("rotation.compute.asset_comparison returned an invalid payload")
    assets = result.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("rotation.compute.asset_comparison returned invalid assets")
    return {
        "calc_date": str(result.get("calc_date") or ""),
        "assets": assets,
    }


def _fallback_list_rotation_regimes() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    regimes = client.rotation.list_regimes()
    return {
        "regimes": regimes,
        "total_count": len(regimes),
    }


def _fallback_list_rotation_templates() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    templates = client.rotation.list_templates()
    return {
        "templates": templates,
        "total_count": len(templates),
    }


def _fallback_rotation_read_config_detail(config_name: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    configs = client.rotation.get_all_configs()
    available_configs = [
        str(config.get("name"))
        for config in configs
        if isinstance(config, dict) and config.get("name")
    ]
    for config in configs:
        if isinstance(config, dict) and config.get("name") == config_name:
            return {
                "success": True,
                "config": config,
                "available_configs": available_configs,
                "error": None,
            }
    return {
        "success": False,
        "config": None,
        "available_configs": available_configs,
        "error": f"Rotation config not found: {config_name}",
    }


def _fallback_list_account_rotation_configs() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    configs = client.rotation.list_account_configs()
    return {
        "configs": configs,
        "total_count": len(configs),
    }


def _fallback_get_account_rotation_config(
    config_id: int | None = None,
    account_id: int | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    if (config_id is None) == (account_id is None):
        raise ValueError("Exactly one of config_id or account_id must be provided.")

    client = AgomTradeProClient()
    if config_id is not None:
        return client.rotation.get_account_config(config_id)
    return client.rotation.get_account_config_by_account(int(account_id))


def _fallback_list_rotation_asset_master() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    assets = client.rotation.list_assets()
    return {
        "assets": assets,
        "total_count": len(assets),
    }


def _fallback_get_rotation_asset(asset_code: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.rotation.get_asset(asset_code)


def _fallback_get_latest_rotation_signals() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    signals = client.rotation.get_latest_signals()
    return {
        "signals": signals,
        "total_count": len(signals),
    }


def _fallback_create_account_rotation_config(
    account_id: int,
    risk_tolerance: str = "moderate",
    is_enabled: bool = False,
    regime_allocations: dict[str, dict[str, float]] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    payload = {
        "account": account_id,
        "risk_tolerance": risk_tolerance,
        "is_enabled": is_enabled,
        "regime_allocations": regime_allocations or {},
    }
    return client.rotation.create_account_config(payload)


def _fallback_delete_account_rotation_config(
    config_id: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.rotation.delete_account_config(config_id)


def _fallback_update_account_rotation_config(
    config_id: int,
    payload: dict[str, Any],
    partial: bool = True,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.rotation.update_account_config(config_id, payload, partial=partial)


def _fallback_apply_rotation_template_to_account_config(
    config_id: int,
    template_key: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.rotation.apply_template_to_account_config(config_id, template_key)


def _internal_handler_rotation_create_asset(
    code: str,
    name: str,
    category: str,
    description: str = "",
    underlying_index: str = "",
    currency: str = "CNY",
    is_active: bool = True,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient, NotFoundError

    normalized_code = str(code or "").strip()
    if not normalized_code or len(normalized_code) > 20:
        raise ValueError("code must be between 1 and 20 characters")

    normalized_name = str(name or "").strip()
    if not normalized_name or len(normalized_name) > 100:
        raise ValueError("name must be between 1 and 100 characters")

    normalized_category = str(category or "").strip().lower()
    allowed_categories = {
        "equity",
        "bond",
        "commodity",
        "currency",
        "alternative",
    }
    if normalized_category not in allowed_categories:
        raise ValueError("category must be equity, bond, commodity, currency, or alternative")

    normalized_description = str(description or "").strip()
    if len(normalized_description) > 2000:
        raise ValueError("description must be at most 2000 characters")

    normalized_underlying_index = str(underlying_index or "").strip()
    if len(normalized_underlying_index) > 50:
        raise ValueError("underlying_index must be at most 50 characters")

    normalized_currency = str(currency or "").strip().upper()
    if not normalized_currency or len(normalized_currency) > 10:
        raise ValueError("currency must be between 1 and 10 characters")
    if not isinstance(is_active, bool):
        raise ValueError("is_active must be a boolean")

    payload = {
        "code": normalized_code,
        "name": normalized_name,
        "category": normalized_category,
        "description": normalized_description,
        "underlying_index": normalized_underlying_index,
        "currency": normalized_currency,
        "is_active": is_active,
    }
    client = AgomTradeProClient()
    if preview_only:
        try:
            existing = client.rotation.get_asset(normalized_code)
        except NotFoundError:
            existing = None
        if existing is not None:
            existing_state = "active" if bool(existing.get("is_active", True)) else "inactive"
            raise ValueError(
                f"rotation asset code already exists ({existing_state}): {normalized_code}"
            )
        return {
            "success": True,
            "preview_only": True,
            "operation": "create",
            "summary": {
                **payload,
                "global_catalog": True,
                "existing_code_count": 0,
                "will_create_asset": True,
                "will_execute_trade": False,
            },
            "message": (
                "Preview generated. Confirm to create this global Rotation asset catalog "
                "entry; this operation does not fetch prices, generate signals, or execute trades."
            ),
        }

    return client.rotation.create_asset(payload)


def _internal_handler_rotation_update_asset(
    asset_code: str,
    name: str | None = None,
    category: str | None = None,
    description: str | None = None,
    underlying_index: str | None = None,
    currency: str | None = None,
    is_active: bool | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    normalized_code = str(asset_code or "").strip()
    if not normalized_code or len(normalized_code) > 20:
        raise ValueError("asset_code must be between 1 and 20 characters")

    updates: dict[str, Any] = {}
    if name is not None:
        normalized_name = str(name).strip()
        if not normalized_name or len(normalized_name) > 100:
            raise ValueError("name must be between 1 and 100 characters")
        updates["name"] = normalized_name

    if category is not None:
        normalized_category = str(category).strip().lower()
        if normalized_category not in {
            "equity",
            "bond",
            "commodity",
            "currency",
            "alternative",
        }:
            raise ValueError("category must be equity, bond, commodity, currency, or alternative")
        updates["category"] = normalized_category

    if description is not None:
        normalized_description = str(description).strip()
        if len(normalized_description) > 2000:
            raise ValueError("description must be at most 2000 characters")
        updates["description"] = normalized_description

    if underlying_index is not None:
        normalized_underlying_index = str(underlying_index).strip()
        if len(normalized_underlying_index) > 50:
            raise ValueError("underlying_index must be at most 50 characters")
        updates["underlying_index"] = normalized_underlying_index

    if currency is not None:
        normalized_currency = str(currency).strip().upper()
        if not normalized_currency or len(normalized_currency) > 10:
            raise ValueError("currency must be between 1 and 10 characters")
        updates["currency"] = normalized_currency

    if is_active is not None:
        if not isinstance(is_active, bool):
            raise ValueError("is_active must be a boolean")
        updates["is_active"] = is_active

    if not updates:
        raise ValueError("at least one asset field must be provided for update")

    client = AgomTradeProClient()
    if preview_only:
        current = client.rotation.get_asset(normalized_code)
        if not isinstance(current, dict):
            raise ValueError("rotation asset detail response must be an object")
        changed_fields = sorted(
            field_name
            for field_name, target_value in updates.items()
            if current.get(field_name) != target_value
        )
        if not changed_fields:
            raise ValueError("rotation asset update has no effective changes")
        current_is_active = bool(current.get("is_active", True))
        target_is_active = bool(updates.get("is_active", current_is_active))
        return {
            "success": True,
            "preview_only": True,
            "operation": "update",
            "asset_code": normalized_code,
            "current_asset": current,
            "requested_updates": updates,
            "summary": {
                "asset_code": normalized_code,
                "global_catalog": True,
                "changed_field_count": len(changed_fields),
                "changed_fields": changed_fields,
                "current_is_active": current_is_active,
                "target_is_active": target_is_active,
                "will_reactivate": not current_is_active and target_is_active,
                "will_deactivate": current_is_active and not target_is_active,
                "will_execute_trade": False,
            },
            "message": (
                "Preview generated. Confirm to update this global Rotation asset catalog "
                "entry; this operation does not fetch prices, generate signals, or execute trades."
            ),
        }

    return client.rotation.update_asset(normalized_code, updates, partial=True)


def _internal_handler_rotation_delete_asset(
    asset_code: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    normalized_code = str(asset_code or "").strip()
    if not normalized_code or len(normalized_code) > 20:
        raise ValueError("asset_code must be between 1 and 20 characters")

    client = AgomTradeProClient()
    if preview_only:
        current = client.rotation.get_asset(normalized_code)
        if not isinstance(current, dict):
            raise ValueError("rotation asset detail response must be an object")
        if not bool(current.get("is_active", True)):
            raise ValueError(f"rotation asset is already inactive: {normalized_code}")
        return {
            "success": True,
            "preview_only": True,
            "operation": "soft_delete",
            "asset_code": normalized_code,
            "current_asset": current,
            "summary": {
                "asset_code": normalized_code,
                "asset_name": current.get("name"),
                "category": current.get("category"),
                "global_catalog": True,
                "current_is_active": True,
                "target_is_active": False,
                "will_soft_delete": True,
                "will_physically_delete": False,
                "will_fetch_prices": False,
                "will_generate_signal": False,
                "will_execute_trade": False,
            },
            "message": (
                "Preview generated. Confirm to deactivate this global Rotation asset. "
                "The record will remain stored; physical deletion is not exposed."
            ),
        }

    return client.rotation.delete_asset(normalized_code)


def _internal_handler_rotation_import_default_assets(
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    if preview_only:
        plan = client.rotation.preview_default_asset_import()
        if not isinstance(plan, dict):
            raise ValueError("default asset import preview response must be an object")
        required_counts = (
            "created",
            "reactivated",
            "updated",
            "unchanged",
            "existing",
            "total_defaults",
        )
        for field_name in required_counts:
            value = plan.get(field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"default asset import preview {field_name} must be a non-negative integer"
                )
        items = plan.get("items")
        if not isinstance(items, list):
            raise ValueError("default asset import preview must contain an items array")
        return {
            "success": True,
            "preview_only": True,
            "operation": "import_defaults",
            "plan": plan,
            "summary": {
                "global_catalog": True,
                "created": plan["created"],
                "reactivated": plan["reactivated"],
                "updated": plan["updated"],
                "unchanged": plan["unchanged"],
                "existing": plan["existing"],
                "total_defaults": plan["total_defaults"],
                "will_physically_delete": False,
                "will_fetch_prices": False,
                "will_generate_signal": False,
                "will_execute_trade": False,
            },
            "message": (
                "Preview generated from the server-owned default asset registry. Confirm to "
                "create missing rows, reactivate inactive defaults and update stale fields."
            ),
        }

    return client.rotation.import_default_assets()


def _internal_handler_rotation_create_account_config(
    account_id: int,
    risk_tolerance: str = "moderate",
    is_enabled: bool = False,
    regime_allocations: dict[str, dict[str, float]] | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    normalized_allocations = dict(regime_allocations or {})

    if preview_only:
        account = client.account.get_account(account_id)
        return {
            "success": True,
            "preview_only": True,
            "account_id": account_id,
            "account_summary": {
                "account_name": account.get("account_name") or account.get("name"),
                "account_type": account.get("account_type"),
                "status": account.get("status"),
            },
            "rotation_config_summary": {
                "risk_tolerance": risk_tolerance,
                "is_enabled": is_enabled,
                "regime_count": len(normalized_allocations),
                "regime_keys": sorted(normalized_allocations),
            },
            "message": (
                "Preview generated. Confirm to create the account rotation config for "
                "the selected account."
            ),
        }

    return _call_registered_tool(
        "create_account_rotation_config",
        {
            "account_id": account_id,
            "risk_tolerance": risk_tolerance,
            "is_enabled": is_enabled,
            "regime_allocations": normalized_allocations,
        },
    )


def _internal_handler_rotation_delete_account_config(
    config_id: int,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        config = client.rotation.get_account_config(config_id)
        return {
            "success": True,
            "preview_only": True,
            "config_id": config_id,
            "account_rotation_config_summary": {
                "account_id": config.get("account"),
                "account_name": config.get("account_name"),
                "account_type": config.get("account_type"),
                "risk_tolerance": config.get("risk_tolerance"),
                "is_enabled": config.get("is_enabled"),
                "regime_count": len(dict(config.get("regime_allocations") or {})),
            },
            "message": (
                "Preview generated. Confirm to delete the selected account rotation config."
            ),
        }

    return _call_registered_tool(
        "delete_account_rotation_config",
        {
            "config_id": config_id,
        },
    )


def _internal_handler_rotation_update_account_config(
    config_id: int,
    payload: dict[str, Any],
    partial: bool = True,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    normalized_payload = dict(payload or {})

    if preview_only:
        config = client.rotation.get_account_config(config_id)
        return {
            "success": True,
            "preview_only": True,
            "config_id": config_id,
            "account_rotation_config_summary": {
                "account_id": config.get("account"),
                "account_name": config.get("account_name"),
                "account_type": config.get("account_type"),
                "risk_tolerance": config.get("risk_tolerance"),
                "is_enabled": config.get("is_enabled"),
                "regime_count": len(dict(config.get("regime_allocations") or {})),
            },
            "update_summary": {
                "partial": partial,
                "field_count": len(normalized_payload),
                "fields": sorted(normalized_payload),
            },
            "message": (
                "Preview generated. Confirm to update the selected account rotation config."
            ),
        }

    return _call_registered_tool(
        "update_account_rotation_config",
        {
            "config_id": config_id,
            "payload": normalized_payload,
            "partial": partial,
        },
    )


def _internal_handler_rotation_apply_template_account_config(
    config_id: int,
    template_key: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        config = client.rotation.get_account_config(config_id)
        templates = client.rotation.list_templates()
        template = next(
            (item for item in templates if str(item.get("key")) == str(template_key)),
            None,
        )
        return {
            "success": True,
            "preview_only": True,
            "config_id": config_id,
            "account_rotation_config_summary": {
                "account_id": config.get("account"),
                "account_name": config.get("account_name"),
                "account_type": config.get("account_type"),
                "risk_tolerance": config.get("risk_tolerance"),
                "is_enabled": config.get("is_enabled"),
                "regime_count": len(dict(config.get("regime_allocations") or {})),
            },
            "template_summary": {
                "template_key": template_key,
                "template_found": template is not None,
                "template_label": None if template is None else template.get("label"),
                "template_risk_tolerance": (
                    None if template is None else template.get("risk_tolerance")
                ),
            },
            "message": (
                "Preview generated. Confirm to apply the selected template to the account "
                "rotation config."
            ),
        }

    return _call_registered_tool(
        "apply_rotation_template_to_account_config",
        {
            "config_id": config_id,
            "template_key": template_key,
        },
    )


def _internal_handler_rotation_generate_signal(
    config_name: str,
    signal_date: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    if preview_only:
        configs = AgomTradeProClient().rotation.get_all_configs()
        config = next(
            (
                item
                for item in configs
                if isinstance(item, dict) and str(item.get("name")) == config_name
            ),
            None,
        )
        if config is None:
            raise ValueError(f"Unknown rotation config: {config_name}")
        return {
            "success": True,
            "preview_only": True,
            "config_name": config_name,
            "signal_date": signal_date,
            "config_found": True,
            "config_id": config.get("id"),
            "will_persist_signal": True,
        }
    return _call_registered_tool(
        "generate_rotation_signal",
        {"config_name": config_name, "signal_date": signal_date},
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "list_rotation_regimes": _fallback_list_rotation_regimes,
    "list_rotation_templates": _fallback_list_rotation_templates,
    "rotation_read_config_detail": _fallback_rotation_read_config_detail,
    "list_account_rotation_configs": _fallback_list_account_rotation_configs,
    "get_account_rotation_config": _fallback_get_account_rotation_config,
    "list_rotation_asset_master": _fallback_list_rotation_asset_master,
    "get_rotation_asset": _fallback_get_rotation_asset,
    "get_latest_rotation_signals": _fallback_get_latest_rotation_signals,
    "rotation_compute_asset_comparison": _fallback_rotation_compute_asset_comparison,
    "create_account_rotation_config": _fallback_create_account_rotation_config,
    "delete_account_rotation_config": _fallback_delete_account_rotation_config,
    "update_account_rotation_config": _fallback_update_account_rotation_config,
    "apply_rotation_template_to_account_config": _fallback_apply_rotation_template_to_account_config,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "rotation_create_asset": _internal_handler_rotation_create_asset,
    "rotation_update_asset": _internal_handler_rotation_update_asset,
    "rotation_delete_asset": _internal_handler_rotation_delete_asset,
    "rotation_import_default_assets": _internal_handler_rotation_import_default_assets,
    "rotation_create_account_config": _internal_handler_rotation_create_account_config,
    "rotation_delete_account_config": _internal_handler_rotation_delete_account_config,
    "rotation_update_account_config": _internal_handler_rotation_update_account_config,
    "rotation_apply_template_account_config": _internal_handler_rotation_apply_template_account_config,
    "rotation_generate_signal": _internal_handler_rotation_generate_signal,
}
