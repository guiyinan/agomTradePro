"""TAR-01 tests for the terminal Agent MCP child-process boundary."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from django.conf import settings

from apps.agent_runtime.application.terminal_agent import TerminalAgentChatRequestDTO
from apps.agent_runtime.infrastructure.terminal_agent_service import (
    OpenAIAgentsTerminalService,
)


def _request() -> TerminalAgentChatRequestDTO:
    """Build a deterministic request whose prompt must not enter child env."""

    return TerminalAgentChatRequestDTO(
        message="prompt-must-never-cross-the-environment-boundary",
        session_id="local-cli-session",
        user_id=7,
        username="ops_user",
        user_role="read_only",
        user_is_admin=False,
        mcp_enabled=True,
        provider_ref=None,
        model=None,
        context={},
    )


def _capture_child_environment() -> tuple[dict[str, str], dict[str, Any]]:
    """Return a fake MCP child environment and constructor metadata."""

    captured: dict[str, Any] = {}

    class FakeServer:
        def __init__(
            self,
            *,
            params: dict[str, Any],
            cache_tools_list: bool,
            client_session_timeout_seconds: float,
            tool_filter: object,
            name: str,
        ) -> None:
            captured["params"] = params
            captured["cache_tools_list"] = cache_tools_list
            captured["client_session_timeout_seconds"] = client_session_timeout_seconds
            captured["tool_filter"] = tool_filter
            captured["name"] = name

    service = OpenAIAgentsTerminalService()
    tool_access = SimpleNamespace(
        auto_allowed={"agom_capability_search": {"tool_name": "agom_capability_search"}},
        gated={},
        allowed_tool_names=frozenset({"agom_capability_search"}),
    )
    service._build_mcp_server({"MCPServerStdio": FakeServer}, _request(), tool_access)
    params = cast(dict[str, Any], captured["params"])
    return cast(dict[str, str], params["env"]), captured


def test_mcp_child_uses_explicit_allowlist_and_keeps_required_identity(monkeypatch) -> None:
    """Only required runtime/config values cross into the MCP child process."""

    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.production")
    monkeypatch.setenv("PYTHONPATH", "C:\\host\\path\\with-prompt-secret")
    monkeypatch.setenv("AGOMTRADEPRO_BASE_URL", "https://web.example.test")
    monkeypatch.setenv("AGOMTRADEPRO_API_TOKEN", "host-api-token")
    monkeypatch.setenv("AGOMTRADEPRO_USERNAME", "host-username")
    monkeypatch.setenv("AGOMTRADEPRO_PASSWORD", "host-password")
    monkeypatch.setenv("AGOMTRADEPRO_INTERNAL_AUTH_SECRET", "host-internal-secret")
    monkeypatch.setenv("AGOMTRADEPRO_AUDIT_SECRET_KEY", "host-audit-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db-user:db-password@example.test/db")
    monkeypatch.setenv("OPENAI_API_KEY", "host-openai-key")
    monkeypatch.setenv("AGOMTRADEPRO_AUDIT_URL", "https://audit-user:audit-password@example.test")
    monkeypatch.setattr(settings, "AGOMTRADEPRO_INTERNAL_AUTH_SECRET", "settings-internal-secret")
    monkeypatch.setattr(settings, "AUDIT_INTERNAL_SECRET_KEY", "settings-audit-secret")

    child_env, captured = _capture_child_environment()

    sdk_root = str(Path(__file__).resolve().parents[3] / "sdk")
    assert child_env["PYTHONPATH"] == sdk_root
    assert child_env["DJANGO_SETTINGS_MODULE"] == "core.settings.production"
    assert child_env["AGOMTRADEPRO_BASE_URL"] == "https://web.example.test"
    assert child_env["AGOMTRADEPRO_INTERNAL_AUTH_SECRET"] == "settings-internal-secret"
    assert child_env["AGOMTRADEPRO_AUDIT_SECRET_KEY"] == "settings-audit-secret"
    assert child_env["AGOMTRADEPRO_INTERNAL_USER_ID"] == "7"
    assert child_env["AGOMTRADEPRO_INTERNAL_USERNAME"] == "ops_user"
    assert child_env["AGOMTRADEPRO_INTERNAL_SOURCE"] == "terminal_mcp"
    assert child_env["AGOMTRADEPRO_MCP_ROLE"] == "read_only"
    assert child_env["AGOMTRADEPRO_MCP_ENFORCE_RBAC"] == "true"
    assert child_env["AGOMTRADEPRO_MCP_ENABLE_CORE_TOOLS"] == "true"
    assert child_env["AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS"] == "false"
    assert child_env["AGOMTRADEPRO_TIMEOUT"] == "8.0"
    assert child_env["AGOMTRADEPRO_MAX_RETRIES"] == "0"
    assert child_env["AGOMTRADEPRO_AUDIT_TIMEOUT_SECONDS"] == "2.0"
    assert child_env["AGOMTRADEPRO_AUDIT_MAX_ATTEMPTS"] == "1"
    assert child_env["AGOMTRADEPRO_AUDIT_RETRY_BACKOFF_SECONDS"] == "0"

    forbidden_keys = {
        "AGOMTRADEPRO_API_TOKEN",
        "AGOMTRADEPRO_USERNAME",
        "AGOMTRADEPRO_PASSWORD",
        "DATABASE_URL",
        "OPENAI_API_KEY",
        "AGOMTRADEPRO_AUDIT_URL",
    }
    assert forbidden_keys.isdisjoint(child_env)
    rendered_env = repr(child_env)
    for secret in (
        "prompt-must-never-cross-the-environment-boundary",
        "host-api-token",
        "host-password",
        "db-password",
        "host-openai-key",
        "audit-password",
    ):
        assert secret not in rendered_env

    assert captured["params"]["args"] == ["-m", "agomtradepro_mcp.server"]
    assert captured["cache_tools_list"] is True


def test_mcp_child_does_not_invent_missing_secrets(monkeypatch) -> None:
    """Missing settings remain absent instead of being filled from host env."""

    monkeypatch.delenv("AGOMTRADEPRO_INTERNAL_AUTH_SECRET", raising=False)
    monkeypatch.delenv("AGOMTRADEPRO_AUDIT_SECRET_KEY", raising=False)
    monkeypatch.setattr(settings, "AGOMTRADEPRO_INTERNAL_AUTH_SECRET", "")
    monkeypatch.setattr(settings, "AUDIT_INTERNAL_SECRET_KEY", "")

    child_env, _ = _capture_child_environment()

    assert "AGOMTRADEPRO_INTERNAL_AUTH_SECRET" not in child_env
    assert "AGOMTRADEPRO_AUDIT_SECRET_KEY" not in child_env
