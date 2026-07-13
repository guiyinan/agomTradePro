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


def _preview_or_call_alpha_trigger_workflow(
    *,
    tool_name: str,
    payload: dict[str, Any],
    preview_only: bool,
) -> dict[str, Any]:
    normalized = dict(payload or {})
    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "operation": tool_name,
            "payload_keys": sorted(normalized),
            "target_ids": {
                key: normalized.get(key)
                for key in ("trigger_id", "candidate_id", "asset_code")
                if normalized.get(key) is not None
            },
        }
    return _call_registered_tool(tool_name, {"payload": normalized})


def _internal_handler_alpha_trigger_create_trigger(
    payload: dict[str, Any],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _preview_or_call_alpha_trigger_workflow(
        tool_name="create_alpha_trigger", payload=payload, preview_only=preview_only
    )


def _internal_handler_alpha_trigger_execute_evaluation(
    payload: dict[str, Any],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _preview_or_call_alpha_trigger_workflow(
        tool_name="evaluate_alpha_trigger", payload=payload, preview_only=preview_only
    )


def _internal_handler_alpha_trigger_execute_invalidation_check(
    payload: dict[str, Any],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _preview_or_call_alpha_trigger_workflow(
        tool_name="check_alpha_trigger_invalidation",
        payload=payload,
        preview_only=preview_only,
    )


def _internal_handler_alpha_trigger_generate_candidate(
    payload: dict[str, Any],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _preview_or_call_alpha_trigger_workflow(
        tool_name="generate_alpha_candidate", payload=payload, preview_only=preview_only
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
    "alpha_trigger_create_trigger": _internal_handler_alpha_trigger_create_trigger,
    "alpha_trigger_execute_evaluation": _internal_handler_alpha_trigger_execute_evaluation,
    "alpha_trigger_execute_invalidation_check": _internal_handler_alpha_trigger_execute_invalidation_check,
    "alpha_trigger_generate_candidate": _internal_handler_alpha_trigger_generate_candidate,
}
