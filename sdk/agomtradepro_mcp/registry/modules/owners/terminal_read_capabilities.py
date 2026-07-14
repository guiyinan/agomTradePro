"""Terminal published-action read capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="terminal.search.user_actions",
        title="Published User Action Search",
        summary="Search the authenticated user's published system actions with a bounded result.",
        description=(
            "Search the reviewed TUI operation graph without loading the full action catalog. "
            "Use this bridge when a dedicated business capability is not found."
        ),
        owner_app="terminal",
        risk_level="low",
        executor_kind="internal_handler",
        executor_ref="terminal_search_user_actions",
        tags=("terminal", "tui", "system", "action", "search", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "actions": {"type": "array"},
                "returned_count": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["actions", "returned_count", "limit"],
        },
        audit_tags=("mcp:native", "tui:published_action"),
    ),
    CapabilityManifest(
        capability_key="terminal.read.user_action_schema",
        title="Published User Action Schema",
        summary="Read one visible published system action contract.",
        description=(
            "Return the fields, risk, and confirmation policy for one action discovered "
            "through terminal.search.user_actions."
        ),
        owner_app="terminal",
        risk_level="low",
        executor_kind="internal_handler",
        executor_ref="terminal_read_user_action_schema",
        tags=("terminal", "tui", "system", "action", "schema", "read"),
        input_schema={
            "type": "object",
            "properties": {"action_key": {"type": "string"}},
            "required": ["action_key"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "action_key": {"type": "string"},
                "risk": {"type": "string"},
                "requires_confirmation": {"type": "boolean"},
                "fields": {"type": "array"},
            },
            "required": ["action_key", "risk", "requires_confirmation", "fields"],
        },
        audit_tags=("mcp:native", "tui:published_action"),
    ),
    CapabilityManifest(
        capability_key="terminal.read.user_action_result",
        title="Run Published Read Action",
        summary="Run one authenticated published read action by action key.",
        description=(
            "Execute only actions whose reviewed TUI risk is read. The canonical TUI "
            "runtime rechecks visibility, endpoint permissions, parameters, and audit policy."
        ),
        owner_app="terminal",
        risk_level="low",
        executor_kind="internal_handler",
        executor_ref="terminal_run_user_read_action",
        tags=("terminal", "tui", "system", "action", "execute", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "action_key": {"type": "string"},
                "params": {"type": "object"},
            },
            "required": ["action_key"],
        },
        output_schema={"type": "object", "properties": {}, "required": []},
        audit_tags=("mcp:native", "tui:published_action"),
    ),
]
