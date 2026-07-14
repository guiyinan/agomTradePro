"""Execute approved Agent proposals through the governed MCP core surface."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from apps.agent_runtime.domain.entities import AgentProposal

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SDK_ROOT = _REPO_ROOT / "sdk"
_MCP_CONFIG_PATH = _REPO_ROOT / ".mcp.json"
_MCP_ROLE_LOCK = RLock()


def _ensure_sdk_on_path() -> None:
    """Put this repository's SDK ahead of unrelated installed checkouts."""

    sdk_path = str(_SDK_ROOT)
    if sdk_path in sys.path:
        sys.path.remove(sdk_path)
    sys.path.insert(0, sdk_path)


def _load_mcp_env_from_repo_config() -> None:
    """Load non-secret MCP process settings from the repository config."""

    if not _MCP_CONFIG_PATH.exists():
        return
    payload = json.loads(_MCP_CONFIG_PATH.read_text(encoding="utf-8"))
    server_conf = (payload.get("mcpServers") or {}).get("agomtradepro_local") or {}
    for key, value in (server_conf.get("env") or {}).items():
        if value is not None:
            os.environ.setdefault(str(key), str(value))


def call_sdk_mcp_tool(tool_name: str, params: dict[str, Any]) -> Any:
    """Call one core tool through the local SDK MCP server contract."""

    _ensure_sdk_on_path()
    _load_mcp_env_from_repo_config()
    from agomtradepro_mcp.server import server

    result = asyncio.run(server.call_tool(tool_name, params))
    if isinstance(result, tuple) and len(result) == 2:
        return result[1]
    return result


@contextmanager
def _trusted_mcp_role(role: str):
    """Scope a server-derived role across one stage-and-resume execution."""

    with _MCP_ROLE_LOCK:
        previous = os.environ.get("AGOMTRADEPRO_MCP_ROLE")
        os.environ["AGOMTRADEPRO_MCP_ROLE"] = role
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("AGOMTRADEPRO_MCP_ROLE", None)
            else:
                os.environ["AGOMTRADEPRO_MCP_ROLE"] = previous


class ApprovedMcpCapabilityExecutor:
    """Run one approved proposal via MCP stage-and-resume calls."""

    def execute(
        self,
        *,
        proposal: AgentProposal,
        actor: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Execute the immutable capability payload and return its MCP envelope."""

        payload = dict(proposal.proposal_payload or {})
        capability_key = str(payload.get("capability_key") or "").strip()
        arguments = payload.get("arguments")
        if not capability_key:
            raise RuntimeError("Approved MCP proposal is missing capability_key")
        if not isinstance(arguments, dict):
            raise RuntimeError("Approved MCP proposal arguments must be an object")

        audit_context = {
            "request_id": proposal.request_id,
            "user_id": (actor or {}).get("user_id"),
            "username": (actor or {}).get("username", "terminal_approver"),
            "mcp_role": ",".join((actor or {}).get("roles", [])),
            "client_id": "terminal_approval",
        }
        trusted_role = "admin" if bool((actor or {}).get("is_staff")) else "read_only"
        with _trusted_mcp_role(trusted_role):
            staged = call_sdk_mcp_tool(
                "agom_capability_call",
                {
                    "capability_key": capability_key,
                    "arguments": dict(arguments),
                    "context": audit_context,
                },
            )
            if not isinstance(staged, dict):
                raise RuntimeError("MCP capability call returned an invalid envelope")

            if staged.get("status") == "confirmation_required":
                confirmation_token = str(staged.get("confirmation_token") or "").strip()
                if not confirmation_token:
                    raise RuntimeError("MCP confirmation response did not include a token")
                result = call_sdk_mcp_tool(
                    "agom_confirmation_resume",
                    {"confirmation_token": confirmation_token, "approve": True},
                )
            else:
                result = staged

        if not isinstance(result, dict):
            raise RuntimeError("MCP execution returned an invalid envelope")
        if not result.get("ok"):
            error = result.get("error") or {}
            code = error.get("code") if isinstance(error, dict) else "mcp_execution_failed"
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(f"{code}: {message or 'MCP execution failed'}")
        return result
