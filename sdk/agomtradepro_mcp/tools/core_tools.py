"""Unified MCP core tool surface backed by the capability registry."""

from __future__ import annotations

import secrets
from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro_mcp.registry.dispatcher import CapabilityDispatcher

CORE_TOOL_NAMES: tuple[str, ...] = (
    "agom_bootstrap",
    "agom_capability_search",
    "agom_capability_schema",
    "agom_capability_call",
    "agom_confirmation_resume",
    "agom_workflow_start",
    "agom_workflow_status",
)

_WORKFLOW_DEFINITIONS: dict[str, dict[str, Any]] = {
    "macro.regime_policy_snapshot": {
        "title": "Regime + Policy Snapshot",
        "steps": [
            "system.read.regime.current",
            "system.read.policy.status",
        ],
    },
    "ops.task_monitor_snapshot": {
        "title": "Task Monitor Snapshot",
        "steps": [
            "task_monitor.read.dashboard",
            "task_monitor.read.celery_health",
        ],
    },
}


def register_core_tools(
    server: FastMCP,
    *,
    dispatcher: CapabilityDispatcher,
    welcome_message_factory,
) -> dict[str, dict[str, Any]]:
    """Register the stable MCP core tools and return workflow run storage."""
    workflow_runs: dict[str, dict[str, Any]] = {}

    @server.tool()
    def agom_bootstrap() -> dict[str, Any]:
        """Return startup guidance and capability registry summary."""
        capabilities = dispatcher.list_capabilities()
        return {
            "ok": True,
            "status": "completed",
            "server": "agomtradepro",
            "message": "AgomTradePro MCP core tools are active.",
            "instructions": welcome_message_factory(),
            "core_tools": list(CORE_TOOL_NAMES),
            "capability_count": len(capabilities),
            "capabilities": [manifest.to_summary_dict() for manifest in capabilities[:10]],
            "workflow_keys": sorted(_WORKFLOW_DEFINITIONS),
        }

    @server.tool()
    def agom_capability_search(
        query: str = "",
        tags: list[str] | None = None,
        owner_app: str | None = None,
        risk_level: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search registry-backed capabilities."""
        matches = dispatcher.search(
            query=query,
            tags=tags or [],
            owner_app=owner_app,
            risk_level=risk_level,
            limit=limit,
        )
        return {
            "ok": True,
            "status": "completed",
            "query": query,
            "matches": matches,
            "total_matches": len(matches),
        }

    @server.tool()
    def agom_capability_schema(capability_key: str) -> dict[str, Any]:
        """Return schema metadata for a capability key."""
        try:
            schema = dispatcher.get_schema(capability_key)
        except KeyError as exc:
            return {
                "ok": False,
                "status": "error",
                "error": {
                    "code": "capability_not_found",
                    "message": str(exc),
                },
                "capability_key": capability_key,
            }
        return {
            "ok": True,
            "status": "completed",
            "capability": schema,
        }

    @server.tool()
    def agom_capability_call(
        capability_key: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one capability through the dispatcher."""
        return dispatcher.call(
            capability_key=capability_key,
            arguments=arguments or {},
        )

    @server.tool()
    def agom_confirmation_resume(
        confirmation_token: str,
        approve: bool = True,
    ) -> dict[str, Any]:
        """Resume or cancel a pending confirmation."""
        return dispatcher.resume_confirmation(
            confirmation_token=confirmation_token,
            approve=approve,
        )

    @server.tool()
    def agom_workflow_start(
        workflow_key: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a small approved workflow over registry capabilities."""
        definition = _WORKFLOW_DEFINITIONS.get(workflow_key)
        if definition is None:
            return {
                "ok": False,
                "status": "error",
                "error": {
                    "code": "workflow_not_found",
                    "message": f"Unknown workflow_key: {workflow_key}",
                },
                "workflow_key": workflow_key,
            }

        run_id = secrets.token_urlsafe(12)
        step_results = []
        for capability_key in definition["steps"]:
            step_results.append(
                {
                    "capability_key": capability_key,
                    "result": dispatcher.call(
                        capability_key=capability_key,
                        arguments=arguments or {},
                    ),
                }
            )
        workflow_runs[run_id] = {
            "run_id": run_id,
            "workflow_key": workflow_key,
            "title": definition["title"],
            "status": "completed",
            "steps": step_results,
        }
        return {
            "ok": True,
            "status": "completed",
            "workflow_run": workflow_runs[run_id],
        }

    @server.tool()
    def agom_workflow_status(run_id: str) -> dict[str, Any]:
        """Return the current status for a previously started workflow."""
        workflow_run = workflow_runs.get(run_id)
        if workflow_run is None:
            return {
                "ok": False,
                "status": "error",
                "error": {
                    "code": "workflow_run_not_found",
                    "message": f"Unknown workflow run: {run_id}",
                },
                "run_id": run_id,
            }
        return {
            "ok": True,
            "status": "completed",
            "workflow_run": workflow_run,
        }

    return workflow_runs
