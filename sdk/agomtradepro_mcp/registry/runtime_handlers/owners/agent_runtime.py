"""agent_runtime runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_get_agent_proposal(proposal_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.agent_proposal.get_proposal(proposal_id)


def _fallback_create_agent_proposal(
    proposal_type: str,
    task_id: int | None = None,
    risk_level: str = "medium",
    approval_required: bool = True,
    proposal_payload: dict[str, Any] | None = None,
    approval_reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.agent_proposal.create_proposal(
        proposal_type=proposal_type,
        task_id=task_id,
        risk_level=risk_level,
        approval_required=approval_required,
        proposal_payload=proposal_payload,
        approval_reason=approval_reason,
    )


def _fallback_execute_agent_proposal(
    proposal_id: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.agent_proposal.execute_proposal(proposal_id)


def _fallback_approve_agent_proposal(
    proposal_id: int,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.agent_proposal.approve_proposal(
        proposal_id=proposal_id,
        reason=reason,
    )


def _fallback_reject_agent_proposal(
    proposal_id: int,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.agent_proposal.reject_proposal(
        proposal_id=proposal_id,
        reason=reason,
    )


def _internal_handler_agent_proposal_create_proposal(
    proposal_type: str,
    task_id: int | None = None,
    risk_level: str = "medium",
    approval_required: bool = True,
    proposal_payload: dict[str, Any] | None = None,
    approval_reason: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    normalized_payload = dict(proposal_payload or {})
    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "proposal_type": proposal_type,
            "task_id": task_id,
            "risk_level": risk_level,
            "approval_required": approval_required,
            "approval_reason": approval_reason,
            "proposal_payload_summary": {
                "field_count": len(normalized_payload),
                "keys": sorted(normalized_payload),
            },
            "message": (
                "Preview generated. Confirm to create the agent proposal record and enter "
                "the approval lifecycle."
            ),
        }

    return _call_registered_tool(
        "create_agent_proposal",
        {
            "proposal_type": proposal_type,
            "task_id": task_id,
            "risk_level": risk_level,
            "approval_required": approval_required,
            "proposal_payload": normalized_payload,
            "approval_reason": approval_reason,
        },
    )


def _internal_handler_agent_proposal_execute_proposal(
    proposal_id: int,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        proposal = client.agent_proposal.get_proposal(proposal_id)
        proposal_payload = dict(proposal.get("proposal_payload") or {})
        return {
            "success": True,
            "preview_only": True,
            "proposal_id": proposal_id,
            "proposal_status": proposal.get("status"),
            "risk_level": proposal.get("risk_level"),
            "approval_required": proposal.get("approval_required"),
            "proposal_payload_summary": {
                "field_count": len(proposal_payload),
                "keys": sorted(proposal_payload),
            },
            "message": (
                "Preview generated. Confirm to execute the approved agent proposal with "
                "pre-execution guardrail checks."
            ),
        }

    return _call_registered_tool(
        "execute_agent_proposal",
        {
            "proposal_id": proposal_id,
        },
    )


def _internal_handler_agent_proposal_approve_proposal(
    proposal_id: int,
    reason: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        proposal = client.agent_proposal.get_proposal(proposal_id)
        proposal_payload = dict(proposal.get("proposal_payload") or {})
        return {
            "success": True,
            "preview_only": True,
            "proposal_id": proposal_id,
            "proposal_status": proposal.get("status"),
            "target_status": "approved",
            "risk_level": proposal.get("risk_level"),
            "approval_required": proposal.get("approval_required"),
            "reason": reason,
            "proposal_payload_summary": {
                "field_count": len(proposal_payload),
                "keys": sorted(proposal_payload),
            },
            "message": (
                "Preview generated. Confirm to approve the submitted agent proposal and "
                "make it eligible for execution."
            ),
        }

    return _call_registered_tool(
        "approve_agent_proposal",
        {
            "proposal_id": proposal_id,
            "reason": reason,
        },
    )


def _internal_handler_agent_proposal_reject_proposal(
    proposal_id: int,
    reason: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        proposal = client.agent_proposal.get_proposal(proposal_id)
        proposal_payload = dict(proposal.get("proposal_payload") or {})
        return {
            "success": True,
            "preview_only": True,
            "proposal_id": proposal_id,
            "proposal_status": proposal.get("status"),
            "target_status": "rejected",
            "risk_level": proposal.get("risk_level"),
            "approval_required": proposal.get("approval_required"),
            "reason": reason,
            "proposal_payload_summary": {
                "field_count": len(proposal_payload),
                "keys": sorted(proposal_payload),
            },
            "message": (
                "Preview generated. Confirm to reject the submitted agent proposal and "
                "close its approval flow."
            ),
        }

    return _call_registered_tool(
        "reject_agent_proposal",
        {
            "proposal_id": proposal_id,
            "reason": reason,
        },
    )


def _internal_handler_agent_task_create_task(
    task_domain: str,
    task_type: str,
    input_payload: dict[str, Any] | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    allowed_domains = {"research", "monitoring", "decision", "execution", "ops"}
    if task_domain not in allowed_domains:
        raise ValueError(f"Unsupported agent task domain: {task_domain}")
    payload = dict(input_payload or {})
    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "task_domain": task_domain,
            "task_type": task_type,
            "input_payload_keys": sorted(payload),
            "message": "Preview generated. Confirm to create the Agent task.",
        }
    return _call_registered_tool(
        f"start_{task_domain}_task",
        {"task_type": task_type, "input_payload": payload},
    )


def _internal_handler_agent_task_resume_task(
    task_id: int,
    target_status: str | None = None,
    reason: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    if preview_only:
        current = AgomTradeProClient().agent_runtime.get_task(task_id)
        return {
            "success": True,
            "preview_only": True,
            "task_id": task_id,
            "current_status": current.get("status"),
            "target_status": target_status,
            "reason": reason,
        }
    return _call_registered_tool(
        "resume_agent_task",
        {"task_id": task_id, "target_status": target_status, "reason": reason},
    )


def _internal_handler_agent_task_cancel_task(
    task_id: int,
    reason: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    if preview_only:
        current = AgomTradeProClient().agent_runtime.get_task(task_id)
        return {
            "success": True,
            "preview_only": True,
            "task_id": task_id,
            "current_status": current.get("status"),
            "target_status": "cancelled",
            "reason": reason,
        }
    return _call_registered_tool(
        "cancel_agent_task",
        {"task_id": task_id, "reason": reason},
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_agent_proposal": _fallback_get_agent_proposal,
    "create_agent_proposal": _fallback_create_agent_proposal,
    "execute_agent_proposal": _fallback_execute_agent_proposal,
    "approve_agent_proposal": _fallback_approve_agent_proposal,
    "reject_agent_proposal": _fallback_reject_agent_proposal,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "agent_proposal_create_proposal": _internal_handler_agent_proposal_create_proposal,
    "agent_proposal_execute_proposal": _internal_handler_agent_proposal_execute_proposal,
    "agent_proposal_approve_proposal": _internal_handler_agent_proposal_approve_proposal,
    "agent_proposal_reject_proposal": _internal_handler_agent_proposal_reject_proposal,
    "agent_task_create_task": _internal_handler_agent_task_create_task,
    "agent_task_resume_task": _internal_handler_agent_task_resume_task,
    "agent_task_cancel_task": _internal_handler_agent_task_cancel_task,
}
