"""alpha_trigger runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_list_alpha_triggers() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    triggers = client.alpha_trigger.list_triggers()
    return {
        "triggers": triggers,
        "total_count": len(triggers),
    }


def _fallback_list_alpha_candidates() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    candidates = client.alpha_trigger.list_candidates()
    return {
        "candidates": candidates,
        "total_count": len(candidates),
    }


def _fallback_get_alpha_candidate(candidate_id: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.alpha_trigger.get_candidate(candidate_id)
    result = response.get("result") if isinstance(response, dict) else None
    return result if isinstance(result, dict) else response


def _fallback_alpha_trigger_read_performance(
    days: int = 30,
    trigger_id: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.alpha_trigger.performance(days=days, trigger_id=trigger_id)


def _fallback_update_alpha_candidate_status(
    candidate_id: str,
    status: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.alpha_trigger.update_candidate_status(candidate_id, status)


def _internal_handler_alpha_trigger_update_candidate_status(
    candidate_id: str,
    status: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        candidate = client.alpha_trigger.get_candidate(candidate_id)
        return {
            "success": True,
            "preview_only": True,
            "candidate_id": candidate_id,
            "candidate_summary": {
                "candidate_id": candidate.get("candidate_id"),
                "asset_code": candidate.get("asset_code"),
                "asset_class": candidate.get("asset_class"),
                "direction": candidate.get("direction"),
                "status": candidate.get("status"),
                "confidence": candidate.get("confidence"),
                "created_at": candidate.get("created_at"),
                "expires_at": candidate.get("expires_at"),
            },
            "target_status": status,
            "message": "Preview generated. Confirm to update the selected alpha candidate status.",
        }

    return _call_registered_tool(
        "update_alpha_candidate_status",
        {
            "candidate_id": candidate_id,
            "status": status,
        },
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "list_alpha_triggers": _fallback_list_alpha_triggers,
    "list_alpha_candidates": _fallback_list_alpha_candidates,
    "get_alpha_candidate": _fallback_get_alpha_candidate,
    "alpha_trigger_read_performance": _fallback_alpha_trigger_read_performance,
    "update_alpha_candidate_status": _fallback_update_alpha_candidate_status,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "alpha_trigger_update_candidate_status": _internal_handler_alpha_trigger_update_candidate_status,
}
