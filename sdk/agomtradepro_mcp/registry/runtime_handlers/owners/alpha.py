"""alpha runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_get_alpha_provider_status() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.alpha.get_provider_status()


def _fallback_get_alpha_available_universes() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.alpha.get_available_universes()
    universes = result.get("universes", []) if isinstance(result, dict) else []
    return {"universes": universes}


def _fallback_check_alpha_health() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.alpha.check_health()


def _fallback_alpha_read_inference_ops_overview() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.alpha.get_ops_inference_overview()
    if (
        isinstance(result, dict)
        and result.get("success") is True
        and isinstance(result.get("data"), dict)
    ):
        return result["data"]
    return result


def _fallback_alpha_read_qlib_data_ops_overview() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.alpha.get_ops_qlib_data_overview()
    if (
        isinstance(result, dict)
        and result.get("success") is True
        and isinstance(result.get("data"), dict)
    ):
        return result["data"]
    return result


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_alpha_provider_status": _fallback_get_alpha_provider_status,
    "get_alpha_available_universes": _fallback_get_alpha_available_universes,
    "check_alpha_health": _fallback_check_alpha_health,
    "alpha_read_inference_ops_overview": _fallback_alpha_read_inference_ops_overview,
    "alpha_read_qlib_data_ops_overview": _fallback_alpha_read_qlib_data_ops_overview,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
