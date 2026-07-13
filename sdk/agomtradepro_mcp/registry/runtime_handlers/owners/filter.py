"""filter runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_list_filters() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    filters = client.filter.list_filters()
    return {
        "filters": filters,
        "total_count": len(filters),
    }


def _fallback_get_filter(
    filter_id: int | None = None,
    indicator_code: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.filter.get_filter(filter_id=filter_id, indicator_code=indicator_code)


def _fallback_get_filter_health() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.filter.health()


def _fallback_create_filter(
    payload: dict[str, Any],
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.filter.create_filter(dict(payload or {}))


def _internal_handler_filter_create_filter(
    indicator_code: str,
    filter_type: str = "HP",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 200,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    create_payload = {
        "indicator_code": indicator_code,
        "filter_type": filter_type,
        "limit": limit,
        "save_results": True,
    }
    if start_date is not None:
        create_payload["start_date"] = start_date
    if end_date is not None:
        create_payload["end_date"] = end_date

    if preview_only:
        preview_payload = dict(create_payload)
        preview_payload["save_results"] = False
        preview_response = client.filter.create_filter(preview_payload)
        if not preview_response.get("success", False):
            raise ValueError(preview_response.get("error") or "Filter preview failed.")
        preview_series = preview_response.get("series") or {}
        preview_dates = preview_series.get("dates") or []
        preview_warnings = preview_response.get("warnings") or []
        return {
            "success": True,
            "preview_only": True,
            "indicator_code": indicator_code,
            "preview_run_summary": {
                "indicator_code": preview_series.get("indicator_code", indicator_code),
                "filter_type": preview_series.get("filter_type", filter_type),
                "point_count": len(preview_dates),
                "warning_count": len(preview_warnings),
                "limit": limit,
                "save_results": False,
                "start_date": start_date,
                "end_date": end_date,
            },
            "message": "Preview generated. Confirm to create the selected filter run.",
        }

    return _call_registered_tool(
        "create_filter",
        {
            "payload": create_payload,
        },
    )


def _internal_handler_filter_update_filter(
    indicator_code: str,
    hp_enabled: bool | None = None,
    hp_lambda: float | None = None,
    kalman_enabled: bool | None = None,
    kalman_level_variance: float | None = None,
    kalman_slope_variance: float | None = None,
    kalman_observation_variance: float | None = None,
    description: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    updates = {
        key: value
        for key, value in {
            "hp_enabled": hp_enabled,
            "hp_lambda": hp_lambda,
            "kalman_enabled": kalman_enabled,
            "kalman_level_variance": kalman_level_variance,
            "kalman_slope_variance": kalman_slope_variance,
            "kalman_observation_variance": kalman_observation_variance,
            "description": description,
        }.items()
        if value is not None
    }
    if not updates:
        raise ValueError("At least one filter config update must be provided.")

    if preview_only:
        config = client.filter.get_filter(indicator_code=indicator_code)
        return {
            "success": True,
            "preview_only": True,
            "indicator_code": indicator_code,
            "filter_config_summary": {
                "indicator_code": config.get("indicator_code", indicator_code),
                "hp_enabled": config.get("hp_enabled"),
                "hp_lambda": config.get("hp_lambda"),
                "kalman_enabled": config.get("kalman_enabled"),
                "kalman_level_variance": config.get("kalman_level_variance"),
                "kalman_slope_variance": config.get("kalman_slope_variance"),
                "kalman_observation_variance": config.get("kalman_observation_variance"),
                "description": config.get("description"),
            },
            "update_summary": {
                "field_count": len(updates),
                "fields": sorted(updates),
            },
            "message": "Preview generated. Confirm to update the selected filter config.",
        }

    return client.filter.update_filter(
        indicator_code=indicator_code,
        payload=updates,
    )


def _internal_handler_filter_delete_filter(
    indicator_code: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        config = client.filter.get_filter(indicator_code=indicator_code)
        return {
            "success": True,
            "preview_only": True,
            "indicator_code": indicator_code,
            "filter_config_summary": {
                "indicator_code": config.get("indicator_code", indicator_code),
                "hp_enabled": config.get("hp_enabled"),
                "hp_lambda": config.get("hp_lambda"),
                "kalman_enabled": config.get("kalman_enabled"),
                "kalman_level_variance": config.get("kalman_level_variance"),
                "kalman_slope_variance": config.get("kalman_slope_variance"),
                "kalman_observation_variance": config.get("kalman_observation_variance"),
                "description": config.get("description"),
            },
            "message": "Preview generated. Confirm to delete the selected filter config override.",
        }

    client.filter.delete_filter(indicator_code=indicator_code)
    return {
        "success": True,
        "indicator_code": indicator_code,
    }


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "list_filters": _fallback_list_filters,
    "get_filter": _fallback_get_filter,
    "get_filter_health": _fallback_get_filter_health,
    "create_filter": _fallback_create_filter,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "filter_create_filter": _internal_handler_filter_create_filter,
    "filter_update_filter": _internal_handler_filter_update_filter,
    "filter_delete_filter": _internal_handler_filter_delete_filter,
}
