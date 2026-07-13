"""Shared runtime handler primitives without server composition dependencies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_legacy_tool_caller: Callable[[str, dict[str, Any]], Any] | None = None


def configure_legacy_tool_caller(
    caller: Callable[[str, dict[str, Any]], Any],
) -> None:
    """Inject the server-owned legacy tool caller at composition time."""

    global _legacy_tool_caller
    _legacy_tool_caller = caller


def _call_registered_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    """Delegate to the configured server tool manager without importing server."""

    if _legacy_tool_caller is None:
        raise RuntimeError("Legacy tool caller is not configured")
    return _legacy_tool_caller(tool_name, arguments)


def _unwrap_canonical_success_data(
    response: dict[str, Any],
    *,
    operation: str,
) -> dict[str, Any]:
    if "success" not in response:
        return response
    if response.get("success") is not True:
        error = str(response.get("error") or f"{operation} failed")
        raise ValueError(error)
    data = response.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"{operation} returned an invalid canonical data payload")
    return data
