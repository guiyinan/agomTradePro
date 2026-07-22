"""broker_execution runtime handlers backed only by the formal SDK."""

from __future__ import annotations

from typing import Any


def _client():
    from agomtradepro import AgomTradeProClient

    return AgomTradeProClient()


def _internal_handler_broker_execution_overview() -> dict[str, Any]:
    return _client().broker_execution.overview()


def _internal_handler_broker_execution_orders(
    account_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    return _client().broker_execution.list_orders(
        account_id=account_id, status=status, limit=limit
    )


def _internal_handler_broker_execution_order(client_order_id: str) -> dict[str, Any]:
    return _client().broker_execution.get_order(client_order_id)


def _internal_handler_broker_execution_connections() -> dict[str, Any]:
    return _client().broker_execution.connections()


def _internal_handler_broker_execution_reconciliations(limit: int = 100) -> dict[str, Any]:
    return _client().broker_execution.reconciliations(limit=limit)


def _internal_handler_broker_execution_audit(limit: int = 100) -> dict[str, Any]:
    return _client().broker_execution.audit(limit=limit)


def _order_action(
    *,
    action: str,
    client_order_id: str,
    reason: str,
    preview_only: bool = False,
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _client().broker_execution.order_action(
        client_order_id,
        action,
        reason=reason,
        preview_only=preview_only,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


def _internal_handler_broker_execution_approve(
    client_order_id: str,
    reason: str,
    preview_only: bool = False,
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _order_action(
        action="approve",
        client_order_id=client_order_id,
        reason=reason,
        preview_only=preview_only,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


def _internal_handler_broker_execution_reject(
    client_order_id: str,
    reason: str,
    preview_only: bool = False,
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _order_action(
        action="reject",
        client_order_id=client_order_id,
        reason=reason,
        preview_only=preview_only,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


def _internal_handler_broker_execution_cancel(
    client_order_id: str,
    reason: str,
    preview_only: bool = False,
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _order_action(
        action="cancel",
        client_order_id=client_order_id,
        reason=reason,
        preview_only=preview_only,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


def _internal_handler_broker_execution_kill_switch(
    account_id: int,
    reason: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _client().broker_execution.set_kill_switch(
        account_id=account_id,
        active=True,
        reason=reason,
        preview_only=preview_only,
        idempotency_key=idempotency_key,
    )


def _internal_handler_broker_execution_resume(
    account_id: int,
    reason: str,
    reauth_password: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _client().broker_execution.set_kill_switch(
        account_id=account_id,
        active=False,
        reason=reason,
        preview_only=preview_only,
        idempotency_key=idempotency_key,
        reauth_password=reauth_password if not preview_only else None,
    )


def _internal_handler_broker_execution_resolve(
    run_id: int,
    resolution: str,
    reason: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return _client().broker_execution.resolve_reconciliation(
        run_id,
        resolution=resolution,
        reason=reason,
        preview_only=preview_only,
        idempotency_key=idempotency_key,
    )


LEGACY_TOOL_FALLBACKS: dict[str, Any] = {}

GOVERNED_HANDLERS = {
    "get_broker_execution_overview": _internal_handler_broker_execution_overview,
    "list_broker_execution_orders": _internal_handler_broker_execution_orders,
    "get_broker_execution_order": _internal_handler_broker_execution_order,
    "get_broker_execution_connections": _internal_handler_broker_execution_connections,
    "list_broker_execution_reconciliations": _internal_handler_broker_execution_reconciliations,
    "list_broker_execution_audit": _internal_handler_broker_execution_audit,
    "broker_execution_approve_order": _internal_handler_broker_execution_approve,
    "broker_execution_reject_order": _internal_handler_broker_execution_reject,
    "broker_execution_request_cancel": _internal_handler_broker_execution_cancel,
    "broker_execution_trigger_kill_switch": _internal_handler_broker_execution_kill_switch,
    "broker_execution_resume_trading": _internal_handler_broker_execution_resume,
    "broker_execution_resolve_reconciliation": _internal_handler_broker_execution_resolve,
}
