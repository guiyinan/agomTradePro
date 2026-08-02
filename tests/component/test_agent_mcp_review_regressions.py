"""Regression coverage for the 2026-07-18 Agent/MCP review."""

from __future__ import annotations

import asyncio
import os
import sys
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.ai_capability.application.sync_use_cases import SyncCapabilitiesUseCase
from apps.terminal.application.ai_capability_gateway import (
    DjangoTerminalCapabilityGateway,
)
from apps.terminal.infrastructure.models import TerminalCommandORM
from shared.infrastructure import mcp_runtime
from shared.infrastructure.async_runtime import run_awaitable_sync, run_sync_compatible


@pytest.mark.django_db
def test_terminal_capability_gateway_uses_domain_command_identifier():
    command = TerminalCommandORM._default_manager.create(
        name="review_regression_command",
        description="Regression command",
        command_type="api",
        api_endpoint="/api/agent-runtime/health/",
        category="ops",
        tags=["review"],
        is_active=True,
    )

    commands = DjangoTerminalCapabilityGateway().list_active_commands()
    payload = next(item for item in commands if item["name"] == command.name)

    assert payload["id"] == str(command.pk)
    assert payload["pk"] == str(command.pk)


@pytest.mark.django_db
def test_capability_sync_isolates_source_failures_and_continues():
    use_case = SyncCapabilitiesUseCase()

    with (
        patch.object(use_case, "_sync_builtin", return_value=[]) as builtin,
        patch.object(
            use_case,
            "_sync_terminal_commands",
            side_effect=RuntimeError("terminal source failed"),
        ) as terminal,
        patch.object(use_case, "_sync_mcp_tools", return_value=[]) as mcp_tools,
        patch.object(use_case, "_sync_apis", return_value=[]) as apis,
    ):
        result = use_case.execute(sync_type="full")

    builtin.assert_called_once_with()
    terminal.assert_called_once_with()
    mcp_tools.assert_called_once_with()
    apis.assert_called_once_with()
    assert result.error_count == 1
    assert result.summary["terminal_command"]["error"] == "capability_source_sync_failed"
    assert result.summary["mcp_tool"]["disabled"] == 0
    assert result.summary["api"]["disabled"] == 0


def test_sync_bridge_works_inside_an_existing_event_loop():
    marker = ContextVar("agent_mcp_review_marker", default="missing")

    async def _inner() -> str:
        await asyncio.sleep(0)
        return marker.get()

    async def _outer() -> str:
        marker.set("propagated")
        return run_awaitable_sync(_inner)

    assert asyncio.run(_outer()) == "propagated"


def test_sync_callable_bridge_works_inside_an_existing_event_loop():
    marker = ContextVar("agent_mcp_sync_marker", default="missing")

    async def _outer() -> str:
        marker.set("propagated")
        return run_sync_compatible(marker.get)

    assert asyncio.run(_outer()) == "propagated"


def test_malformed_mcp_config_degrades_without_raising(tmp_path, monkeypatch):
    config_path = tmp_path / ".mcp.json"
    config_path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(mcp_runtime, "MCP_CONFIG_PATH", config_path)

    mcp_runtime.load_mcp_env_from_repo_config()


def test_in_process_mcp_call_binds_and_restores_originating_user(monkeypatch):
    observed: dict[str, str | None] = {}

    class FakeServer:
        async def call_tool(self, _tool_name, _params):
            observed.update(
                token=os.environ.get("AGOMTRADEPRO_API_TOKEN"),
                user_id=os.environ.get("AGOMTRADEPRO_INTERNAL_USER_ID"),
                username=os.environ.get("AGOMTRADEPRO_INTERNAL_USERNAME"),
                source=os.environ.get("AGOMTRADEPRO_INTERNAL_SOURCE"),
            )
            return ([], {"ok": True})

    monkeypatch.setenv("AGOMTRADEPRO_INTERNAL_AUTH_SECRET", "internal-secret")
    monkeypatch.setenv("AGOMTRADEPRO_API_TOKEN", "global-token")
    monkeypatch.setenv("AGOMTRADEPRO_INTERNAL_USER_ID", "99")
    monkeypatch.setenv("AGOMTRADEPRO_INTERNAL_USERNAME", "previous")
    monkeypatch.setitem(
        sys.modules,
        "agomtradepro_mcp.server",
        SimpleNamespace(server=FakeServer()),
    )
    monkeypatch.setattr(mcp_runtime, "ensure_sdk_on_path", lambda: None)
    monkeypatch.setattr(mcp_runtime, "load_mcp_env_from_repo_config", lambda: None)

    result = mcp_runtime.call_sdk_mcp_tool(
        "agom_capability_call",
        {"capability_key": "equity.read.research_snapshot", "arguments": {}},
        user_id=7,
        username="researcher",
    )

    assert result == {"ok": True}
    assert observed == {
        "token": None,
        "user_id": "7",
        "username": "researcher",
        "source": "ai_capability_route",
    }
    assert os.environ["AGOMTRADEPRO_API_TOKEN"] == "global-token"
    assert os.environ["AGOMTRADEPRO_INTERNAL_USER_ID"] == "99"
    assert os.environ["AGOMTRADEPRO_INTERNAL_USERNAME"] == "previous"
