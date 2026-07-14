"""Terminal published-action write capability manifests."""

from __future__ import annotations

from agomtradepro_mcp.registry.manifest import CapabilityManifest

MANIFESTS = [
    CapabilityManifest(
        capability_key="terminal.execute.user_action",
        title="Execute Published State-Changing Action",
        summary="Preview and confirm one visible AI, write, or admin TUI action.",
        description=(
            "Use a reviewed published action as the fallback for system functionality that "
            "has no dedicated MCP capability. The TUI runtime rechecks user visibility, "
            "permissions, required fields, confirmation, audit policy, and reauthentication."
        ),
        owner_app="terminal",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="terminal_execute_user_action",
        tags=("terminal", "tui", "system", "action", "execute", "write"),
        input_schema={
            "type": "object",
            "properties": {
                "action_key": {"type": "string"},
                "params": {"type": "object"},
                "idempotency_key": {"type": "string"},
                "preview_only": {"type": "boolean"},
            },
            "required": ["action_key"],
        },
        output_schema={"type": "object", "properties": {}, "required": []},
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        idempotency="required",
        audit_tags=(
            "terminal:execute_user_action",
            "tui:published_action",
            "mcp:write",
            "mcp:native",
        ),
    )
]
