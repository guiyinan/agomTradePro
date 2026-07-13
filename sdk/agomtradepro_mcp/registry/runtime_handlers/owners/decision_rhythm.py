"""decision_rhythm runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import (
    _call_registered_tool,
    _unwrap_canonical_success_data,
)


def _fallback_decision_read_advisor_sheet(
    account_id: int | str,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.decision_rhythm.advisor_sheet(account_id=account_id)
    return _unwrap_canonical_success_data(
        response,
        operation="decision.read.advisor_sheet",
    )


def _fallback_list_decision_quotas() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    quotas = client.decision_rhythm.list_quotas()
    return {
        "quotas": quotas,
        "total_count": len(quotas),
    }


def _fallback_list_decision_requests() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    requests = client.decision_rhythm.list_requests()
    return {
        "requests": requests,
        "total_count": len(requests),
    }


def _fallback_get_decision_request(request_id: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.decision_rhythm.get_request(request_id)
    result = response.get("result") if isinstance(response, dict) else None
    return result if isinstance(result, dict) else response


def _fallback_get_decision_rhythm_summary() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.decision_rhythm.summary()
    result = response.get("result") if isinstance(response, dict) else None
    return result if isinstance(result, dict) else response


def _fallback_decision_workflow_list_recommendations(
    account_id: str,
    status: str | None = None,
    user_action: str | None = None,
    security_code: str | None = None,
    recommendation_id: str | None = None,
    include_ignored: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.decision_workflow.list_recommendations(
        account_id=account_id,
        status=status,
        user_action=user_action,
        security_code=security_code,
        recommendation_id=recommendation_id,
        include_ignored=include_ignored,
        page=page,
        page_size=page_size,
    )
    data = response.get("data") if isinstance(response, dict) else None
    return data if isinstance(data, dict) else response


def _fallback_decision_workflow_get_transition_plan(
    plan_id: str,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.decision_workflow.get_transition_plan(plan_id)
    data = response.get("data") if isinstance(response, dict) else None
    return data if isinstance(data, dict) else response


def _fallback_decision_workflow_preview_execution(
    account_id: str,
    plan_id: str | None = None,
    recommendation_id: str | None = None,
    create_request: bool = False,
    market_price: str | float | int | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.decision_workflow.preview_execution(
        account_id=account_id,
        plan_id=plan_id,
        recommendation_id=recommendation_id,
        create_request=create_request,
        market_price=market_price,
    )


def _fallback_submit_batch_decision_request(
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.decision_rhythm.submit_batch(payload)


def _fallback_submit_decision_request(
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.decision_rhythm.submit(payload)


def _fallback_decision_execute_request(
    request_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.decision_rhythm.execute_request(request_id, payload)


def _fallback_decision_cancel_request(
    request_id: str,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.decision_rhythm.cancel_request(request_id, reason)


def _internal_handler_decision_submit_request_batch(
    payload: dict[str, Any],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    normalized_payload = dict(payload or {})
    requests = list(normalized_payload.get("requests") or [])
    quota_period = normalized_payload.get("quota_period", "weekly")

    if preview_only:
        direction_counts: dict[str, int] = {}
        asset_codes: list[str] = []
        for item in requests:
            if not isinstance(item, dict):
                continue
            direction = str(item.get("direction") or "").strip().upper()
            if direction:
                direction_counts[direction] = direction_counts.get(direction, 0) + 1
            asset_code = str(item.get("asset_code") or "").strip()
            if asset_code:
                asset_codes.append(asset_code)

        return {
            "success": True,
            "preview_only": True,
            "summary": {
                "request_count": len(requests),
                "quota_period": quota_period,
                "direction_counts": direction_counts,
                "asset_codes": sorted(set(asset_codes))[:20],
            },
            "message": (
                "Preview generated. Confirm to submit the decision request batch into the "
                "decision rhythm workflow."
            ),
        }

    return _call_registered_tool(
        "submit_batch_decision_request",
        {
            "payload": normalized_payload,
        },
    )


def _internal_handler_decision_submit_request(
    payload: dict[str, Any],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    normalized_payload = dict(payload or {})

    if preview_only:
        asset_code = str(normalized_payload.get("asset_code") or "").strip()
        direction = str(normalized_payload.get("direction") or "").strip().upper()
        quota_period = str(normalized_payload.get("quota_period") or "weekly").strip().lower()
        priority = str(normalized_payload.get("priority") or "").strip().lower()
        return {
            "success": True,
            "preview_only": True,
            "summary": {
                "request_count": 1,
                "asset_code": asset_code or None,
                "direction": direction or None,
                "quota_period": quota_period,
                "priority": priority or None,
                "payload_keys": sorted(normalized_payload),
            },
            "message": (
                "Preview generated. Confirm to submit the decision request into the "
                "decision rhythm workflow."
            ),
        }

    return _call_registered_tool(
        "submit_decision_request",
        {
            "payload": normalized_payload,
        },
    )


def _internal_handler_decision_execute_request(
    request_id: str,
    payload: dict[str, Any],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    normalized_payload = dict(payload or {})

    if preview_only:
        request_detail = client.decision_rhythm.get_request(request_id)
        target = str(normalized_payload.get("target") or "").strip().upper()
        asset_code = str(normalized_payload.get("asset_code") or "").strip()
        return {
            "success": True,
            "preview_only": True,
            "request_id": request_id,
            "request_status": request_detail.get("status") or request_detail.get("request_status"),
            "execution_status": request_detail.get("execution_status"),
            "target": target or None,
            "payload_summary": {
                "asset_code": asset_code or None,
                "target": target or None,
                "payload_keys": sorted(normalized_payload),
            },
            "message": (
                "Preview generated. Confirm to execute the approved decision request into "
                "the selected target."
            ),
        }

    return _call_registered_tool(
        "decision_execute_request",
        {
            "request_id": request_id,
            "payload": normalized_payload,
        },
    )


def _internal_handler_decision_cancel_request(
    request_id: str,
    reason: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        request_detail = client.decision_rhythm.get_request(request_id)
        return {
            "success": True,
            "preview_only": True,
            "request_id": request_id,
            "request_status": request_detail.get("status") or request_detail.get("request_status"),
            "execution_status": request_detail.get("execution_status"),
            "candidate_status": request_detail.get("candidate_status"),
            "target_status": "cancelled",
            "reason": reason,
            "message": (
                "Preview generated. Confirm to cancel the decision request and stop "
                "further execution workflow."
            ),
        }

    return _call_registered_tool(
        "decision_cancel_request",
        {
            "request_id": request_id,
            "reason": reason,
        },
    )


def _internal_handler_decision_reset_quota(
    account_id: str,
    period: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    normalized_account_id = str(account_id or "").strip()
    if not normalized_account_id:
        raise ValueError("account_id must be a non-empty string")

    normalized_period = str(period or "").strip().lower() or None
    allowed_periods = {"daily", "weekly", "monthly"}
    if normalized_period is not None and normalized_period not in allowed_periods:
        raise ValueError("period must be one of: daily, weekly, monthly")

    client = AgomTradeProClient()
    if preview_only:
        current_quotas = client.decision_rhythm.list_quotas(
            account_id=normalized_account_id,
            period=normalized_period,
        )
        if not current_quotas:
            raise ValueError(f"No decision quota found for account_id={normalized_account_id}")
        return {
            "success": True,
            "preview_only": True,
            "account_id": normalized_account_id,
            "requested_period": normalized_period,
            "current_quotas": [
                {
                    "quota_id": quota.get("quota_id"),
                    "period": quota.get("period"),
                    "used_decisions": quota.get("used_decisions"),
                    "used_executions": quota.get("used_executions"),
                    "max_decisions": quota.get("max_decisions"),
                    "max_execution_count": quota.get("max_execution_count"),
                }
                for quota in current_quotas
            ],
            "summary": {
                "account_id": normalized_account_id,
                "quota_count": len(current_quotas),
                "periods": [quota.get("period") for quota in current_quotas],
            },
            "message": "Preview generated. Confirm to reset decision quota usage counters.",
        }

    payload = {"account_id": normalized_account_id}
    if normalized_period is not None:
        payload["period"] = normalized_period
    return client.decision_rhythm.reset_quota(payload)


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "decision_read_advisor_sheet": _fallback_decision_read_advisor_sheet,
    "list_decision_quotas": _fallback_list_decision_quotas,
    "list_decision_requests": _fallback_list_decision_requests,
    "get_decision_request": _fallback_get_decision_request,
    "get_decision_rhythm_summary": _fallback_get_decision_rhythm_summary,
    "decision_workflow_list_recommendations": _fallback_decision_workflow_list_recommendations,
    "decision_workflow_get_transition_plan": _fallback_decision_workflow_get_transition_plan,
    "decision_workflow_preview_execution": _fallback_decision_workflow_preview_execution,
    "submit_batch_decision_request": _fallback_submit_batch_decision_request,
    "submit_decision_request": _fallback_submit_decision_request,
    "decision_execute_request": _fallback_decision_execute_request,
    "decision_cancel_request": _fallback_decision_cancel_request,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "decision_submit_request_batch": _internal_handler_decision_submit_request_batch,
    "decision_submit_request": _internal_handler_decision_submit_request,
    "decision_execute_request": _internal_handler_decision_execute_request,
    "decision_cancel_request": _internal_handler_decision_cancel_request,
    "decision_reset_quota": _internal_handler_decision_reset_quota,
}
