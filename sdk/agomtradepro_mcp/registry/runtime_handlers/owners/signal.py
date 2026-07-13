"""signal runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _serialize_signal_read_model(signal: Any) -> dict[str, Any]:
    return {
        "id": signal.id,
        "asset_code": signal.asset_code,
        "logic_desc": signal.logic_desc,
        "status": signal.status,
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
        "invalidation_logic": signal.invalidation_logic,
        "invalidation_threshold": signal.invalidation_threshold,
        "approved_at": signal.approved_at.isoformat() if signal.approved_at else None,
        "invalidated_at": signal.invalidated_at.isoformat() if signal.invalidated_at else None,
        "created_by": signal.created_by,
    }


def _fallback_list_signals(
    status: str | None = None,
    asset_code: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    signals = client.signal.list(
        status=status,
        asset_code=asset_code,
        limit=limit,
    )
    return {
        "signals": [_serialize_signal_read_model(signal) for signal in signals],
        "total_count": len(signals),
    }


def _fallback_get_signal(signal_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return _serialize_signal_read_model(client.signal.get(signal_id))


def _fallback_check_signal_eligibility(
    asset_code: str,
    logic_desc: str,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.signal.check_eligibility(
        asset_code=asset_code,
        logic_desc=logic_desc,
    )
    return {
        "is_eligible": result.is_eligible,
        "regime_match": result.regime_match,
        "policy_match": result.policy_match,
        "current_regime": result.current_regime,
        "policy_status": result.policy_status,
        "rejection_reason": result.rejection_reason,
    }


def _fallback_create_signal(
    asset_code: str,
    logic_desc: str,
    invalidation_logic: str,
    invalidation_threshold: float,
    target_regime: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    signal = client.signal.create(
        asset_code=asset_code,
        logic_desc=logic_desc,
        invalidation_logic=invalidation_logic,
        invalidation_threshold=invalidation_threshold,
        target_regime=target_regime,
    )
    return {
        "id": signal.id,
        "asset_code": signal.asset_code,
        "logic_desc": signal.logic_desc,
        "status": signal.status,
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
    }


def _fallback_approve_signal(
    signal_id: int,
    approver: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    signal = client.signal.approve(signal_id, approver=approver)
    return {
        "id": signal.id,
        "status": signal.status,
        "approved_at": signal.approved_at.isoformat() if signal.approved_at else None,
    }


def _fallback_reject_signal(
    signal_id: int,
    reason: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    signal = client.signal.reject(signal_id, reason=reason)
    return {
        "id": signal.id,
        "status": signal.status,
    }


def _fallback_invalidate_signal(
    signal_id: int,
    reason: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    signal = client.signal.invalidate(signal_id, reason=reason)
    return {
        "id": signal.id,
        "status": signal.status,
        "invalidated_at": signal.invalidated_at.isoformat() if signal.invalidated_at else None,
    }


def _internal_handler_signal_create_signal(
    asset_code: str,
    logic_desc: str,
    invalidation_logic: str,
    invalidation_threshold: float,
    target_regime: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        eligibility = client.signal.check_eligibility(
            asset_code=asset_code,
            logic_desc=logic_desc,
            target_regime=target_regime,
        )
        return {
            "success": True,
            "preview_only": True,
            "asset_code": asset_code,
            "target_regime": target_regime,
            "eligibility": {
                "is_eligible": eligibility.is_eligible,
                "regime_match": eligibility.regime_match,
                "policy_match": eligibility.policy_match,
                "current_regime": eligibility.current_regime,
                "policy_status": eligibility.policy_status,
                "rejection_reason": eligibility.rejection_reason,
            },
            "signal_payload_summary": {
                "logic_desc_length": len(logic_desc.strip()),
                "invalidation_logic_length": len(invalidation_logic.strip()),
                "invalidation_threshold": invalidation_threshold,
            },
            "message": ("Preview generated. Confirm to create the pending investment signal."),
        }

    return _call_registered_tool(
        "create_signal",
        {
            "asset_code": asset_code,
            "logic_desc": logic_desc,
            "invalidation_logic": invalidation_logic,
            "invalidation_threshold": invalidation_threshold,
            "target_regime": target_regime,
        },
    )


def _internal_handler_signal_approve_signal(
    signal_id: int,
    approver: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        signal = client.signal.get(signal_id)
        return {
            "success": True,
            "preview_only": True,
            "signal_id": signal_id,
            "signal_status": signal.status,
            "target_status": "approved",
            "asset_code": signal.asset_code,
            "approver": approver,
            "created_at": signal.created_at.isoformat() if signal.created_at else None,
            "message": ("Preview generated. Confirm to approve the pending investment signal."),
        }

    return _call_registered_tool(
        "approve_signal",
        {
            "signal_id": signal_id,
            "approver": approver,
        },
    )


def _internal_handler_signal_reject_signal(
    signal_id: int,
    reason: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        signal = client.signal.get(signal_id)
        return {
            "success": True,
            "preview_only": True,
            "signal_id": signal_id,
            "signal_status": signal.status,
            "target_status": "rejected",
            "asset_code": signal.asset_code,
            "reason": reason,
            "created_at": signal.created_at.isoformat() if signal.created_at else None,
            "message": ("Preview generated. Confirm to reject the pending investment signal."),
        }

    return _call_registered_tool(
        "reject_signal",
        {
            "signal_id": signal_id,
            "reason": reason,
        },
    )


def _internal_handler_signal_invalidate_signal(
    signal_id: int,
    reason: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        signal = client.signal.get(signal_id)
        return {
            "success": True,
            "preview_only": True,
            "signal_id": signal_id,
            "signal_status": signal.status,
            "target_status": "invalidated",
            "asset_code": signal.asset_code,
            "reason": reason,
            "created_at": signal.created_at.isoformat() if signal.created_at else None,
            "message": ("Preview generated. Confirm to invalidate the investment signal."),
        }

    return _call_registered_tool(
        "invalidate_signal",
        {
            "signal_id": signal_id,
            "reason": reason,
        },
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "list_signals": _fallback_list_signals,
    "get_signal": _fallback_get_signal,
    "check_signal_eligibility": _fallback_check_signal_eligibility,
    "create_signal": _fallback_create_signal,
    "approve_signal": _fallback_approve_signal,
    "reject_signal": _fallback_reject_signal,
    "invalidate_signal": _fallback_invalidate_signal,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "signal_create_signal": _internal_handler_signal_create_signal,
    "signal_approve_signal": _internal_handler_signal_approve_signal,
    "signal_reject_signal": _internal_handler_signal_reject_signal,
    "signal_invalidate_signal": _internal_handler_signal_invalidate_signal,
}
