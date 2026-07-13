"""data_center runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_get_data_center_provider_status() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    providers = client.data_center.get_provider_status()
    return {
        "providers": providers,
        "total_count": len(providers),
    }


def _fallback_list_data_center_providers() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    providers = client.data_center.list_providers()
    return {
        "providers": providers,
        "total_count": len(providers),
    }


def _fallback_test_data_center_provider_connection(provider_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.test_provider_connection(provider_id)


def _fallback_data_center_get_macro_series(
    indicator_code: str,
    start: str | None = None,
    end: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.get_macro_series(
        indicator_code,
        start=start,
        end=end,
        limit=limit,
    )


def _fallback_data_center_list_indicators(active_only: bool = False) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    indicators = client.data_center.list_indicators(active_only=active_only)
    return {
        "indicators": indicators,
        "total_count": len(indicators),
    }


def _fallback_data_center_get_price_history(
    asset_code: str,
    start: str | None = None,
    end: str | None = None,
    freq: str | None = None,
    adjustment: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.get_price_history(
        asset_code,
        start=start,
        end=end,
        freq=freq,
        adjustment=adjustment,
        limit=limit,
    )


def _fallback_data_center_get_quotes(
    asset_code: str,
    strict_freshness: bool | None = None,
    max_age_hours: float | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.get_latest_quotes(
        asset_code,
        strict_freshness=strict_freshness,
        max_age_hours=max_age_hours,
    )


def _fallback_data_center_get_news(
    asset_code: str,
    limit: int = 20,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.get_news(asset_code, limit=limit)


def _fallback_data_center_get_capital_flows(
    asset_code: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.get_capital_flows(
        asset_code,
        start=start,
        end=end,
        limit=limit,
    )


def _fallback_data_center_get_publisher(publisher_code: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.get_publisher(publisher_code)


def _fallback_data_center_list_publishers(
    active_only: bool = False,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    publishers = client.data_center.list_publishers(active_only=active_only)
    return {
        "publishers": publishers,
        "total_count": len(publishers),
    }


def _fallback_data_center_get_indicator(indicator_code: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.get_indicator(indicator_code)


def _fallback_data_center_list_indicator_unit_rules(
    indicator_code: str,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    rules = client.data_center.list_indicator_unit_rules(indicator_code)
    return {
        "indicator_code": indicator_code,
        "rules": rules,
        "total_count": len(rules),
    }


def _fallback_data_center_get_indicator_unit_rule(
    indicator_code: str,
    rule_id: int,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.get_indicator_unit_rule(indicator_code, rule_id)


def _fallback_data_center_update_publisher(
    publisher_code: str,
    canonical_name: str | None = None,
    publisher_class: str | None = None,
    aliases: list[str] | None = None,
    canonical_name_en: str | None = None,
    country_code: str | None = None,
    website: str | None = None,
    is_active: bool | None = None,
    description: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    payload: dict[str, Any] = {}
    if canonical_name is not None:
        payload["canonical_name"] = canonical_name
    if publisher_class is not None:
        payload["publisher_class"] = publisher_class
    if aliases is not None:
        payload["aliases"] = aliases
    if canonical_name_en is not None:
        payload["canonical_name_en"] = canonical_name_en
    if country_code is not None:
        payload["country_code"] = country_code
    if website is not None:
        payload["website"] = website
    if is_active is not None:
        payload["is_active"] = is_active
    if description is not None:
        payload["description"] = description
    return client.data_center.update_publisher(publisher_code, payload)


def _fallback_data_center_create_publisher(
    code: str,
    canonical_name: str,
    publisher_class: str,
    aliases: list[str] | None = None,
    canonical_name_en: str = "",
    country_code: str = "CN",
    website: str = "",
    is_active: bool = True,
    description: str = "",
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.create_publisher(
        {
            "code": code,
            "canonical_name": canonical_name,
            "publisher_class": publisher_class,
            "aliases": aliases or [],
            "canonical_name_en": canonical_name_en,
            "country_code": country_code,
            "website": website,
            "is_active": is_active,
            "description": description,
        }
    )


def _fallback_data_center_delete_publisher(
    publisher_code: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    client.data_center.delete_publisher(publisher_code)
    return {
        "success": True,
        "publisher_code": publisher_code,
    }


def _fallback_data_center_create_indicator(
    code: str,
    name_cn: str,
    default_period_type: str = "M",
    name_en: str = "",
    description: str = "",
    category: str = "",
    is_active: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.create_indicator(
        {
            "code": code,
            "name_cn": name_cn,
            "name_en": name_en,
            "description": description,
            "category": category,
            "default_period_type": default_period_type,
            "is_active": is_active,
            "extra": extra or {},
        }
    )


def _fallback_data_center_delete_indicator(
    indicator_code: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    client.data_center.delete_indicator(indicator_code)
    return {
        "success": True,
        "indicator_code": indicator_code,
    }


def _fallback_data_center_create_indicator_unit_rule(
    indicator_code: str,
    dimension_key: str,
    storage_unit: str,
    display_unit: str,
    multiplier_to_storage: float,
    source_type: str = "",
    original_unit: str = "",
    is_active: bool = True,
    priority: int = 0,
    description: str = "",
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.create_indicator_unit_rule(
        indicator_code,
        {
            "source_type": source_type,
            "dimension_key": dimension_key,
            "original_unit": original_unit,
            "storage_unit": storage_unit,
            "display_unit": display_unit,
            "multiplier_to_storage": multiplier_to_storage,
            "is_active": is_active,
            "priority": priority,
            "description": description,
        },
    )


def _fallback_data_center_delete_indicator_unit_rule(
    indicator_code: str,
    rule_id: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    client.data_center.delete_indicator_unit_rule(indicator_code, rule_id)
    return {
        "success": True,
        "indicator_code": indicator_code,
        "rule_id": rule_id,
    }


def _fallback_data_center_update_indicator_unit_rule(
    indicator_code: str,
    rule_id: int,
    source_type: str | None = None,
    dimension_key: str | None = None,
    original_unit: str | None = None,
    storage_unit: str | None = None,
    display_unit: str | None = None,
    multiplier_to_storage: float | None = None,
    is_active: bool | None = None,
    priority: int | None = None,
    description: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    payload: dict[str, Any] = {}
    if source_type is not None:
        payload["source_type"] = source_type
    if dimension_key is not None:
        payload["dimension_key"] = dimension_key
    if original_unit is not None:
        payload["original_unit"] = original_unit
    if storage_unit is not None:
        payload["storage_unit"] = storage_unit
    if display_unit is not None:
        payload["display_unit"] = display_unit
    if multiplier_to_storage is not None:
        payload["multiplier_to_storage"] = multiplier_to_storage
    if is_active is not None:
        payload["is_active"] = is_active
    if priority is not None:
        payload["priority"] = priority
    if description is not None:
        payload["description"] = description
    return client.data_center.update_indicator_unit_rule(indicator_code, rule_id, payload)


def _fallback_data_center_sync_macro(
    provider_id: int,
    indicator_code: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.sync_macro(
        {
            "provider_id": provider_id,
            "indicator_code": indicator_code,
            "start": start,
            "end": end,
        }
    )


def _fallback_data_center_sync_capital_flows(
    provider_id: int,
    asset_code: str,
    period: str = "5d",
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.sync_capital_flows(
        {
            "provider_id": provider_id,
            "asset_code": asset_code,
            "period": period,
        }
    )


def _fallback_data_center_sync_news(
    provider_id: int,
    asset_code: str,
    limit: int = 20,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.data_center.sync_news(
        {
            "provider_id": provider_id,
            "asset_code": asset_code,
            "limit": limit,
        }
    )


def _fallback_data_center_update_indicator(
    indicator_code: str,
    name_cn: str | None = None,
    name_en: str | None = None,
    description: str | None = None,
    category: str | None = None,
    default_period_type: str | None = None,
    is_active: bool | None = None,
    extra: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    payload: dict[str, Any] = {}
    if name_cn is not None:
        payload["name_cn"] = name_cn
    if name_en is not None:
        payload["name_en"] = name_en
    if description is not None:
        payload["description"] = description
    if category is not None:
        payload["category"] = category
    if default_period_type is not None:
        payload["default_period_type"] = default_period_type
    if is_active is not None:
        payload["is_active"] = is_active
    if extra is not None:
        payload["extra"] = extra
    return client.data_center.update_indicator(indicator_code, payload)


def _internal_handler_data_center_create_publisher(
    code: str,
    canonical_name: str,
    publisher_class: str,
    aliases: list[str] | None = None,
    canonical_name_en: str = "",
    country_code: str = "CN",
    website: str = "",
    is_active: bool = True,
    description: str = "",
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    create_arguments = {
        "code": code,
        "canonical_name": canonical_name,
        "publisher_class": publisher_class,
        "aliases": aliases or [],
        "canonical_name_en": canonical_name_en,
        "country_code": country_code,
        "website": website,
        "is_active": is_active,
        "description": description,
    }

    if preview_only:
        aliases_value = create_arguments["aliases"] or []
        return {
            "success": True,
            "preview_only": True,
            "create_summary": {
                "field_count": len(create_arguments),
                "fields": sorted(create_arguments),
                "code": create_arguments["code"],
                "canonical_name": create_arguments["canonical_name"],
                "publisher_class": create_arguments["publisher_class"],
                "alias_count": len(aliases_value),
                "aliases": aliases_value,
                "country_code": create_arguments["country_code"],
                "website": create_arguments["website"],
                "is_active": create_arguments["is_active"],
                "description_present": bool(create_arguments["description"]),
                "has_canonical_name_en": bool(create_arguments["canonical_name_en"]),
            },
            "message": (
                "Preview generated. Confirm to create the selected publisher catalog entry."
            ),
        }

    return _call_registered_tool(
        "data_center_create_publisher",
        create_arguments,
    )


def _internal_handler_data_center_delete_publisher(
    publisher_code: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        publisher = client.data_center.get_publisher(publisher_code)
        current_aliases = publisher.get("aliases") or []
        return {
            "success": True,
            "preview_only": True,
            "publisher_code": publisher_code,
            "publisher_summary": {
                "code": publisher.get("code"),
                "canonical_name": publisher.get("canonical_name"),
                "publisher_class": publisher.get("publisher_class"),
                "alias_count": len(current_aliases),
                "aliases": current_aliases,
                "country_code": publisher.get("country_code"),
                "website": publisher.get("website"),
                "is_active": publisher.get("is_active"),
                "description": publisher.get("description"),
            },
            "target_status": "deleted",
            "message": "Preview generated. Confirm to delete the selected publisher catalog entry.",
        }

    return _call_registered_tool(
        "data_center_delete_publisher",
        {
            "publisher_code": publisher_code,
        },
    )


def _internal_handler_data_center_create_indicator(
    code: str,
    name_cn: str,
    default_period_type: str = "M",
    name_en: str = "",
    description: str = "",
    category: str = "",
    is_active: bool = True,
    extra: dict[str, Any] | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    create_arguments = {
        "code": code,
        "name_cn": name_cn,
        "name_en": name_en,
        "description": description,
        "category": category,
        "default_period_type": default_period_type,
        "is_active": is_active,
        "extra": extra or {},
    }

    if preview_only:
        extra_value = create_arguments["extra"] or {}
        return {
            "success": True,
            "preview_only": True,
            "create_summary": {
                "field_count": len(create_arguments),
                "fields": sorted(create_arguments),
                "code": create_arguments["code"],
                "name_cn": create_arguments["name_cn"],
                "name_en": create_arguments["name_en"],
                "category": create_arguments["category"],
                "default_period_type": create_arguments["default_period_type"],
                "is_active": create_arguments["is_active"],
                "description_present": bool(create_arguments["description"]),
                "extra_keys": sorted(extra_value.keys()),
            },
            "message": "Preview generated. Confirm to create the selected indicator catalog entry.",
        }

    return _call_registered_tool(
        "data_center_create_indicator",
        create_arguments,
    )


def _internal_handler_data_center_delete_indicator(
    indicator_code: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        indicator = client.data_center.get_indicator(indicator_code)
        extra_value = indicator.get("extra") or {}
        return {
            "success": True,
            "preview_only": True,
            "indicator_code": indicator_code,
            "indicator_summary": {
                "code": indicator.get("code"),
                "name_cn": indicator.get("name_cn"),
                "name_en": indicator.get("name_en"),
                "description": indicator.get("description"),
                "category": indicator.get("category"),
                "default_period_type": indicator.get("default_period_type"),
                "is_active": indicator.get("is_active"),
                "extra_keys": sorted(extra_value.keys()),
            },
            "target_status": "deleted",
            "message": "Preview generated. Confirm to delete the selected indicator catalog entry.",
        }

    return _call_registered_tool(
        "data_center_delete_indicator",
        {
            "indicator_code": indicator_code,
        },
    )


def _internal_handler_data_center_create_indicator_unit_rule(
    indicator_code: str,
    dimension_key: str,
    storage_unit: str,
    display_unit: str,
    multiplier_to_storage: float,
    source_type: str = "",
    original_unit: str = "",
    is_active: bool = True,
    priority: int = 0,
    description: str = "",
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    create_arguments = {
        "indicator_code": indicator_code,
        "source_type": source_type,
        "dimension_key": dimension_key,
        "original_unit": original_unit,
        "storage_unit": storage_unit,
        "display_unit": display_unit,
        "multiplier_to_storage": multiplier_to_storage,
        "is_active": is_active,
        "priority": priority,
        "description": description,
    }

    if preview_only:
        indicator = client.data_center.get_indicator(indicator_code)
        existing_rules = client.data_center.list_indicator_unit_rules(indicator_code)
        matching_rules = [
            rule
            for rule in existing_rules
            if (rule.get("source_type") or "") == source_type
            and (rule.get("original_unit") or "") == original_unit
        ]
        return {
            "success": True,
            "preview_only": True,
            "indicator_code": indicator_code,
            "indicator_summary": {
                "code": indicator.get("code"),
                "name_cn": indicator.get("name_cn"),
                "category": indicator.get("category"),
                "default_period_type": indicator.get("default_period_type"),
                "is_active": indicator.get("is_active"),
            },
            "create_summary": {
                "field_count": len(create_arguments),
                "fields": sorted(create_arguments),
                "indicator_code": indicator_code,
                "source_type": source_type,
                "dimension_key": dimension_key,
                "original_unit": original_unit,
                "storage_unit": storage_unit,
                "display_unit": display_unit,
                "multiplier_to_storage": multiplier_to_storage,
                "is_active": is_active,
                "priority": priority,
                "description_present": bool(description),
            },
            "existing_rule_summary": {
                "existing_rule_count": len(existing_rules),
                "matching_rule_count": len(matching_rules),
            },
            "message": "Preview generated. Confirm to create the selected indicator unit rule.",
        }

    return _call_registered_tool(
        "data_center_create_indicator_unit_rule",
        create_arguments,
    )


def _internal_handler_data_center_delete_indicator_unit_rule(
    indicator_code: str,
    rule_id: int,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        indicator = client.data_center.get_indicator(indicator_code)
        rule = client.data_center.get_indicator_unit_rule(indicator_code, rule_id)
        return {
            "success": True,
            "preview_only": True,
            "indicator_code": indicator_code,
            "rule_id": rule_id,
            "indicator_summary": {
                "code": indicator.get("code"),
                "name_cn": indicator.get("name_cn"),
                "category": indicator.get("category"),
                "default_period_type": indicator.get("default_period_type"),
                "is_active": indicator.get("is_active"),
            },
            "rule_summary": {
                "id": rule.get("id"),
                "source_type": rule.get("source_type"),
                "dimension_key": rule.get("dimension_key"),
                "original_unit": rule.get("original_unit"),
                "storage_unit": rule.get("storage_unit"),
                "display_unit": rule.get("display_unit"),
                "multiplier_to_storage": rule.get("multiplier_to_storage"),
                "is_active": rule.get("is_active"),
                "priority": rule.get("priority"),
                "description": rule.get("description"),
            },
            "target_status": "deleted",
            "message": "Preview generated. Confirm to delete the selected indicator unit rule.",
        }

    return _call_registered_tool(
        "data_center_delete_indicator_unit_rule",
        {
            "indicator_code": indicator_code,
            "rule_id": rule_id,
        },
    )


def _internal_handler_data_center_update_indicator_unit_rule(
    indicator_code: str,
    rule_id: int,
    source_type: str | None = None,
    dimension_key: str | None = None,
    original_unit: str | None = None,
    storage_unit: str | None = None,
    display_unit: str | None = None,
    multiplier_to_storage: float | None = None,
    is_active: bool | None = None,
    priority: int | None = None,
    description: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    updates = {
        key: value
        for key, value in {
            "source_type": source_type,
            "dimension_key": dimension_key,
            "original_unit": original_unit,
            "storage_unit": storage_unit,
            "display_unit": display_unit,
            "multiplier_to_storage": multiplier_to_storage,
            "is_active": is_active,
            "priority": priority,
            "description": description,
        }.items()
        if value is not None
    }
    if not updates:
        raise ValueError("At least one indicator unit rule update must be provided.")

    if preview_only:
        indicator = client.data_center.get_indicator(indicator_code)
        rule = client.data_center.get_indicator_unit_rule(indicator_code, rule_id)
        return {
            "success": True,
            "preview_only": True,
            "indicator_code": indicator_code,
            "rule_id": rule_id,
            "indicator_summary": {
                "code": indicator.get("code"),
                "name_cn": indicator.get("name_cn"),
                "category": indicator.get("category"),
                "default_period_type": indicator.get("default_period_type"),
                "is_active": indicator.get("is_active"),
            },
            "rule_summary": {
                "id": rule.get("id"),
                "source_type": rule.get("source_type"),
                "dimension_key": rule.get("dimension_key"),
                "original_unit": rule.get("original_unit"),
                "storage_unit": rule.get("storage_unit"),
                "display_unit": rule.get("display_unit"),
                "multiplier_to_storage": rule.get("multiplier_to_storage"),
                "is_active": rule.get("is_active"),
                "priority": rule.get("priority"),
                "description": rule.get("description"),
            },
            "update_summary": {
                "field_count": len(updates),
                "fields": sorted(updates),
            },
            "message": "Preview generated. Confirm to update the selected indicator unit rule.",
        }

    return _call_registered_tool(
        "data_center_update_indicator_unit_rule",
        {
            "indicator_code": indicator_code,
            "rule_id": rule_id,
            **updates,
        },
    )


def _internal_handler_data_center_start_sync_job(
    job_kind: str,
    provider_id: int,
    indicator_code: str | None = None,
    start: str | None = None,
    end: str | None = None,
    asset_code: str | None = None,
    period: str = "5d",
    limit: int = 20,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient
    from agomtradepro.exceptions import AgomTradeProAPIError

    client = AgomTradeProClient()

    if job_kind == "sync_macro":
        if not indicator_code:
            raise ValueError("indicator_code is required for sync_macro jobs.")
        if not start:
            raise ValueError("start is required for sync_macro jobs.")
        if not end:
            raise ValueError("end is required for sync_macro jobs.")

        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
        if end_date < start_date:
            raise ValueError("end must be on or after start for sync_macro jobs.")

        if preview_only:
            provider = client.data_center.get_provider(provider_id)
            indicator = client.data_center.get_indicator(indicator_code)
            return {
                "success": True,
                "preview_only": True,
                "provider_id": provider_id,
                "indicator_code": indicator_code,
                "provider_summary": {
                    "id": provider.get("id"),
                    "name": provider.get("name"),
                    "source_type": provider.get("source_type"),
                    "is_active": provider.get("is_active"),
                    "priority": provider.get("priority"),
                },
                "indicator_summary": {
                    "code": indicator.get("code"),
                    "name_cn": indicator.get("name_cn"),
                    "category": indicator.get("category"),
                    "default_period_type": indicator.get("default_period_type"),
                    "is_active": indicator.get("is_active"),
                },
                "sync_job_summary": {
                    "job_kind": job_kind,
                    "domain": "macro",
                    "start": start,
                    "end": end,
                    "window_days": (end_date - start_date).days + 1,
                    "write_target": "data_center_macro_fact",
                },
                "message": "Preview generated. Confirm to start the selected data-center sync job.",
            }

        return _call_registered_tool(
            "data_center_sync_macro",
            {
                "provider_id": provider_id,
                "indicator_code": indicator_code,
                "start": start,
                "end": end,
            },
        )

    if job_kind == "sync_capital_flows":
        if not asset_code:
            raise ValueError("asset_code is required for sync_capital_flows jobs.")

        if preview_only:
            provider = client.data_center.get_provider(provider_id)
            asset_summary: dict[str, Any] = {"code": asset_code}
            try:
                asset = client.data_center.resolve_asset(
                    asset_code,
                    source_type=provider.get("source_type"),
                )
            except AgomTradeProAPIError:
                asset = None
            if isinstance(asset, dict):
                asset_summary = {
                    "code": asset.get("code", asset_code),
                    "name": asset.get("name"),
                    "name_cn": asset.get("name_cn"),
                    "asset_type": asset.get("asset_type"),
                    "exchange": asset.get("exchange"),
                }
            return {
                "success": True,
                "preview_only": True,
                "provider_id": provider_id,
                "asset_code": asset_code,
                "provider_summary": {
                    "id": provider.get("id"),
                    "name": provider.get("name"),
                    "source_type": provider.get("source_type"),
                    "is_active": provider.get("is_active"),
                    "priority": provider.get("priority"),
                },
                "asset_summary": asset_summary,
                "sync_job_summary": {
                    "job_kind": job_kind,
                    "domain": "capital_flow",
                    "period": period,
                    "write_target": "data_center_capital_flow_fact",
                },
                "message": "Preview generated. Confirm to start the selected data-center sync job.",
            }

        return _call_registered_tool(
            "data_center_sync_capital_flows",
            {
                "provider_id": provider_id,
                "asset_code": asset_code,
                "period": period,
            },
        )

    if job_kind == "sync_news":
        if not asset_code:
            raise ValueError("asset_code is required for sync_news jobs.")

        if preview_only:
            provider = client.data_center.get_provider(provider_id)
            asset_summary: dict[str, Any] = {"code": asset_code}
            try:
                asset = client.data_center.resolve_asset(
                    asset_code,
                    source_type=provider.get("source_type"),
                )
            except AgomTradeProAPIError:
                asset = None
            if isinstance(asset, dict):
                asset_summary = {
                    "code": asset.get("code", asset_code),
                    "name": asset.get("name"),
                    "name_cn": asset.get("name_cn"),
                    "asset_type": asset.get("asset_type"),
                    "exchange": asset.get("exchange"),
                }
            return {
                "success": True,
                "preview_only": True,
                "provider_id": provider_id,
                "asset_code": asset_code,
                "provider_summary": {
                    "id": provider.get("id"),
                    "name": provider.get("name"),
                    "source_type": provider.get("source_type"),
                    "is_active": provider.get("is_active"),
                    "priority": provider.get("priority"),
                },
                "asset_summary": asset_summary,
                "sync_job_summary": {
                    "job_kind": job_kind,
                    "domain": "news",
                    "limit": limit,
                    "write_target": "data_center_news_fact",
                },
                "message": "Preview generated. Confirm to start the selected data-center sync job.",
            }

        return _call_registered_tool(
            "data_center_sync_news",
            {
                "provider_id": provider_id,
                "asset_code": asset_code,
                "limit": limit,
            },
        )

    raise ValueError(f"Unsupported data_center sync job kind: {job_kind}")


def _internal_handler_data_center_update_publisher(
    publisher_code: str,
    canonical_name: str | None = None,
    publisher_class: str | None = None,
    aliases: list[str] | None = None,
    canonical_name_en: str | None = None,
    country_code: str | None = None,
    website: str | None = None,
    is_active: bool | None = None,
    description: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    updates = {
        key: value
        for key, value in {
            "canonical_name": canonical_name,
            "publisher_class": publisher_class,
            "aliases": aliases,
            "canonical_name_en": canonical_name_en,
            "country_code": country_code,
            "website": website,
            "is_active": is_active,
            "description": description,
        }.items()
        if value is not None
    }
    if not updates:
        raise ValueError("At least one publisher update must be provided.")

    if preview_only:
        publisher = client.data_center.get_publisher(publisher_code)
        current_aliases = publisher.get("aliases") or []
        return {
            "success": True,
            "preview_only": True,
            "publisher_code": publisher_code,
            "publisher_summary": {
                "code": publisher.get("code"),
                "canonical_name": publisher.get("canonical_name"),
                "publisher_class": publisher.get("publisher_class"),
                "alias_count": len(current_aliases),
                "aliases": current_aliases,
                "country_code": publisher.get("country_code"),
                "website": publisher.get("website"),
                "is_active": publisher.get("is_active"),
                "description": publisher.get("description"),
            },
            "update_summary": {
                "field_count": len(updates),
                "fields": sorted(updates),
            },
            "message": "Preview generated. Confirm to update the selected publisher catalog entry.",
        }

    return _call_registered_tool(
        "data_center_update_publisher",
        {
            "publisher_code": publisher_code,
            **updates,
        },
    )


def _internal_handler_data_center_update_indicator(
    indicator_code: str,
    name_cn: str | None = None,
    name_en: str | None = None,
    description: str | None = None,
    category: str | None = None,
    default_period_type: str | None = None,
    is_active: bool | None = None,
    extra: dict[str, Any] | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    updates = {
        key: value
        for key, value in {
            "name_cn": name_cn,
            "name_en": name_en,
            "description": description,
            "category": category,
            "default_period_type": default_period_type,
            "is_active": is_active,
            "extra": extra,
        }.items()
        if value is not None
    }
    if not updates:
        raise ValueError("At least one indicator update must be provided.")

    if preview_only:
        indicator = client.data_center.get_indicator(indicator_code)
        current_extra = indicator.get("extra") or {}
        return {
            "success": True,
            "preview_only": True,
            "indicator_code": indicator_code,
            "indicator_summary": {
                "code": indicator.get("code"),
                "name_cn": indicator.get("name_cn"),
                "name_en": indicator.get("name_en"),
                "category": indicator.get("category"),
                "default_period_type": indicator.get("default_period_type"),
                "is_active": indicator.get("is_active"),
                "description": indicator.get("description"),
                "extra_keys": sorted(current_extra.keys()),
            },
            "update_summary": {
                "field_count": len(updates),
                "fields": sorted(updates),
            },
            "message": "Preview generated. Confirm to update the selected indicator catalog entry.",
        }

    return _call_registered_tool(
        "data_center_update_indicator",
        {
            "indicator_code": indicator_code,
            **updates,
        },
    )


def _sanitize_provider_probe_payload(value: Any) -> Any:
    sensitive_keys = {"api_key", "api_secret", "token", "secret", "password"}
    if isinstance(value, dict):
        return {
            key: _sanitize_provider_probe_payload(item)
            for key, item in value.items()
            if str(key).lower() not in sensitive_keys
        }
    if isinstance(value, list):
        return [_sanitize_provider_probe_payload(item) for item in value]
    return value


def _internal_handler_data_center_run_provider_connection_test(
    provider_id: int,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    if not isinstance(provider_id, int) or isinstance(provider_id, bool) or provider_id <= 0:
        raise ValueError("provider_id must be a positive integer")

    if preview_only:
        provider = AgomTradeProClient().data_center.get_provider(provider_id)
        return {
            "success": True,
            "preview_only": True,
            "provider_summary": {
                "id": provider.get("id"),
                "name": provider.get("name"),
                "source_type": provider.get("source_type"),
                "is_active": provider.get("is_active"),
                "priority": provider.get("priority"),
                "has_api_key": bool(provider.get("has_api_key")),
                "has_api_secret": bool(provider.get("has_api_secret")),
            },
            "side_effects": {
                "external_provider_call": True,
                "parser_path_execution": True,
                "provider_health_metadata_write": True,
                "market_fact_sync": False,
            },
            "message": (
                "Preview generated without running the probe or writing health metadata. "
                "Confirm to execute the real external provider connection test."
            ),
        }

    result = _call_registered_tool(
        "test_data_center_provider_connection",
        {"provider_id": provider_id},
    )
    return _sanitize_provider_probe_payload(result)


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_data_center_provider_status": _fallback_get_data_center_provider_status,
    "list_data_center_providers": _fallback_list_data_center_providers,
    "test_data_center_provider_connection": _fallback_test_data_center_provider_connection,
    "data_center_get_macro_series": _fallback_data_center_get_macro_series,
    "data_center_list_indicators": _fallback_data_center_list_indicators,
    "data_center_get_price_history": _fallback_data_center_get_price_history,
    "data_center_get_capital_flows": _fallback_data_center_get_capital_flows,
    "data_center_get_quotes": _fallback_data_center_get_quotes,
    "data_center_get_news": _fallback_data_center_get_news,
    "data_center_get_publisher": _fallback_data_center_get_publisher,
    "data_center_list_publishers": _fallback_data_center_list_publishers,
    "data_center_get_indicator": _fallback_data_center_get_indicator,
    "data_center_list_indicator_unit_rules": _fallback_data_center_list_indicator_unit_rules,
    "data_center_get_indicator_unit_rule": _fallback_data_center_get_indicator_unit_rule,
    "data_center_create_publisher": _fallback_data_center_create_publisher,
    "data_center_delete_publisher": _fallback_data_center_delete_publisher,
    "data_center_create_indicator": _fallback_data_center_create_indicator,
    "data_center_delete_indicator": _fallback_data_center_delete_indicator,
    "data_center_create_indicator_unit_rule": _fallback_data_center_create_indicator_unit_rule,
    "data_center_delete_indicator_unit_rule": _fallback_data_center_delete_indicator_unit_rule,
    "data_center_update_indicator_unit_rule": _fallback_data_center_update_indicator_unit_rule,
    "data_center_sync_macro": _fallback_data_center_sync_macro,
    "data_center_sync_capital_flows": _fallback_data_center_sync_capital_flows,
    "data_center_sync_news": _fallback_data_center_sync_news,
    "data_center_update_publisher": _fallback_data_center_update_publisher,
    "data_center_update_indicator": _fallback_data_center_update_indicator,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "data_center_create_publisher": _internal_handler_data_center_create_publisher,
    "data_center_delete_publisher": _internal_handler_data_center_delete_publisher,
    "data_center_create_indicator": _internal_handler_data_center_create_indicator,
    "data_center_delete_indicator": _internal_handler_data_center_delete_indicator,
    "data_center_create_indicator_unit_rule": _internal_handler_data_center_create_indicator_unit_rule,
    "data_center_delete_indicator_unit_rule": _internal_handler_data_center_delete_indicator_unit_rule,
    "data_center_update_indicator_unit_rule": _internal_handler_data_center_update_indicator_unit_rule,
    "data_center_start_sync_job": _internal_handler_data_center_start_sync_job,
    "data_center_update_publisher": _internal_handler_data_center_update_publisher,
    "data_center_update_indicator": _internal_handler_data_center_update_indicator,
    "data_center_run_provider_connection_test": _internal_handler_data_center_run_provider_connection_test,
}
