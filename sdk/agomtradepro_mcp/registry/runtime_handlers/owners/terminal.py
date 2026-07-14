"""Terminal published-action runtime capability handlers."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

_ACTION_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


def _validated_action_key(action_key: str) -> str:
    """Return one path-safe published action key."""

    normalized = str(action_key or "").strip()
    if not normalized or _ACTION_KEY_PATTERN.fullmatch(normalized) is None:
        raise ValueError("action_key contains unsupported characters")
    return normalized


def _client():
    """Build the authenticated SDK client lazily."""

    from agomtradepro import AgomTradeProClient

    return AgomTradeProClient()


def _action_schema(action_key: str) -> dict[str, Any]:
    """Read one action contract through the authenticated Terminal API."""

    key = _validated_action_key(action_key)
    payload = _client().get(f"api/terminal/tui/actions/{key}/schema/")
    if not isinstance(payload, dict) or payload.get("action_key") != key:
        raise ValueError("Terminal action schema returned an invalid payload")
    return payload


def _internal_handler_terminal_search_user_actions(
    query: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Search visible published actions without returning the full catalog."""

    payload = _client().get(
        "api/terminal/tui/actions/search/",
        params={"query": str(query or ""), "limit": max(1, min(int(limit), 20))},
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("actions"), list):
        raise ValueError("Terminal action search returned an invalid payload")
    return payload


def _internal_handler_terminal_read_user_action_schema(action_key: str) -> dict[str, Any]:
    """Return one visible published action schema."""

    return _action_schema(action_key)


def _run_action(action_key: str, params: dict[str, Any], *, confirmed: bool) -> dict[str, Any]:
    """Run one action through the canonical audited TUI action endpoint."""

    key = _validated_action_key(action_key)
    payload = _client().post(
        f"api/tui/actions/{key}/run/",
        json={
            "params": dict(params or {}),
            "confirmed": confirmed,
            "confirmation": {
                "source": "mcp_governed_action_bridge",
                "confirmed": confirmed,
            },
        },
    )
    if not isinstance(payload, dict):
        raise ValueError("Terminal action execution returned an invalid payload")
    return payload


def _internal_handler_terminal_run_user_read_action(
    action_key: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute only a published read-risk action."""

    schema = _action_schema(action_key)
    if str(schema.get("risk") or "").lower() != "read":
        raise PermissionError("Use terminal.execute.user_action for non-read actions")
    return _run_action(action_key, dict(params or {}), confirmed=False)


def _internal_handler_terminal_execute_user_action(
    action_key: str,
    params: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    preview_only: bool = False,
) -> dict[str, Any]:
    """Preview or execute one published non-read action after MCP confirmation."""

    schema = _action_schema(action_key)
    risk = str(schema.get("risk") or "").lower()
    if risk not in {"ai", "write", "admin"}:
        raise PermissionError("Use terminal.read.user_action_result for read actions")
    if preview_only:
        return {
            "preview_only": True,
            "action": schema,
            "params": dict(params or {}),
            "idempotency_key": str(idempotency_key or ""),
        }
    return _run_action(action_key, dict(params or {}), confirmed=True)


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "terminal_search_user_actions": _internal_handler_terminal_search_user_actions,
    "terminal_read_user_action_schema": _internal_handler_terminal_read_user_action_schema,
    "terminal_run_user_read_action": _internal_handler_terminal_run_user_read_action,
    "terminal_execute_user_action": _internal_handler_terminal_execute_user_action,
}
