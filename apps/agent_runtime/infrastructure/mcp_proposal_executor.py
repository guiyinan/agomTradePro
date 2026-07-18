"""Execute approved Agent proposals through the governed MCP core surface."""

from __future__ import annotations

import os
from contextlib import contextmanager
from threading import RLock
from typing import Any

from django.conf import settings

from apps.agent_runtime.domain.entities import AgentProposal
from shared.infrastructure.async_runtime import run_sync_compatible
from shared.infrastructure.django_sdk_transport import DjangoSdkTransport
from shared.infrastructure.mcp_runtime import call_sdk_mcp_tool, ensure_sdk_on_path

_MCP_ROLE_LOCK = RLock()


@contextmanager
def _trusted_mcp_context(role: str, actor: dict[str, Any]):
    """Scope trusted role and internal auth across one stage/resume execution."""

    with _MCP_ROLE_LOCK:
        overrides = {
            "AGOMTRADEPRO_MCP_ROLE": role,
            "AGOMTRADEPRO_INTERNAL_AUTH_SECRET": getattr(
                settings,
                "AGOMTRADEPRO_INTERNAL_AUTH_SECRET",
                "",
            ),
            "AGOMTRADEPRO_INTERNAL_USER_ID": str(actor.get("user_id") or ""),
            "AGOMTRADEPRO_INTERNAL_USERNAME": str(actor.get("username") or "terminal_approver"),
            "AGOMTRADEPRO_INTERNAL_SOURCE": "terminal_approval",
        }
        previous = {key: os.environ.get(key) for key in overrides}
        os.environ.update(overrides)
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _persist_local_audit_log(payload: dict[str, Any]) -> str | None:
    """Persist an embedded MCP audit event through the Audit application facade."""

    from apps.audit.application.interface_services import log_operation_payload

    result = run_sync_compatible(lambda: log_operation_payload(**payload))
    if not result.get("success"):
        raise RuntimeError(str(result.get("error") or "Local MCP audit write failed"))
    log_id = result.get("log_id")
    return str(log_id) if log_id is not None else None


@contextmanager
def _local_mcp_io(actor: dict[str, Any]):
    """Scope socket-free SDK transport and local audit persistence."""

    ensure_sdk_on_path()
    from agomtradepro.transport import use_request_transport
    from agomtradepro_mcp.audit import use_audit_sink

    with use_request_transport(DjangoSdkTransport(actor=actor)), use_audit_sink(
        _persist_local_audit_log
    ):
        yield


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
        with _trusted_mcp_context(trusted_role, actor or {}), _local_mcp_io(actor or {}):
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
