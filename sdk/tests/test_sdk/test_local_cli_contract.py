"""Contract tests for the server-side CLI compatibility facade."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from agomtradepro.local_cli import (
    LocalAgentConfig,
    LocalCliConfigurationError,
    RemoteTokenStore,
    authorization_header,
    main,
    run_local_agent,
    run_server_agent,
)


@dataclass(frozen=True)
class _Credentials(RemoteTokenStore):
    token: str | None

    def get_remote_api_token(self) -> str | None:
        return self.token


@dataclass
class _ServerPrompt:
    calls: list[dict[str, str]]
    result: dict[str, object]

    def agent_execute(self, *, task_type: str, user_input: str) -> dict[str, object]:
        self.calls.append({"task_type": task_type, "user_input": user_input})
        return self.result


@dataclass
class _ServerClient:
    prompt: _ServerPrompt


def _config() -> LocalAgentConfig:
    return LocalAgentConfig(
        base_url="https://api.example.test",
        remote_api_token="remote-secret",
        mcp_url="https://mcp.example.test/mcp",
    )


def test_config_reads_only_scoped_server_token_and_redacts_diagnostics() -> None:
    config = LocalAgentConfig.from_environment(
        store=_Credentials("remote-secret"),
        environ={
            "AGOMTRADEPRO_BASE_URL": "https://api.example.test/",
            "AGOMTRADEPRO_MCP_URL": "https://mcp.example.test/mcp?ignored=yes",
            "AGOMTRADEPRO_PROVIDER_API_KEY": "must-not-be-read",
            "OPENAI_API_KEY": "must-not-be-read",
        },
    )

    diagnostics = config.diagnostics()
    assert diagnostics["execution_location"] == "server"
    assert diagnostics["run_ready"] is True
    assert diagnostics["provider_key_configured"] is False
    rendered = json.dumps(diagnostics)
    assert "remote-secret" not in rendered
    assert "must-not-be-read" not in rendered
    assert config.mcp_url == "https://mcp.example.test/mcp"
    assert "remote-secret" not in repr(config)


def test_authorization_header_preserves_scheme_and_rejects_control_chars() -> None:
    assert authorization_header("raw-token") == "Token raw-token"
    assert authorization_header("Bearer raw-token") == "Bearer raw-token"
    assert authorization_header("Token raw-token") == "Token raw-token"
    with pytest.raises(LocalCliConfigurationError):
        authorization_header("raw\n-token")


def test_run_uses_server_prompt_api_and_never_accepts_provider_fields() -> None:
    calls: list[dict[str, str]] = []
    prompt = _ServerPrompt(calls, {"final_answer": "server result"})

    def factory(*, base_url: str, api_token: str) -> _ServerClient:
        assert base_url == "https://api.example.test"
        assert api_token == "remote-secret"
        return _ServerClient(prompt)

    assert run_server_agent("show my tasks", _config(), client_factory=factory) == "server result"
    assert calls == [{"task_type": "chat", "user_input": "show my tasks"}]
    assert run_local_agent("show my tasks", _config(), client_factory=factory) == "server result"
    assert len(calls) == 2


def test_local_name_is_only_a_compatibility_alias() -> None:
    source = Path("sdk/agomtradepro/local_cli.py").read_text(encoding="utf-8")
    assert "from agents" not in source
    assert "provider_api_key" not in source
    assert "temporary_provider_environment" not in source
    assert "run_server_agent" in source


def test_doctor_is_safe_when_server_token_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("AGOMTRADEPRO_API_TOKEN", raising=False)
    monkeypatch.delenv("AGOMTRADEPRO_MCP_URL", raising=False)

    assert main(["doctor"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["run_ready"] is False
    assert output["execution_location"] == "server"
    assert output["provider_key_configured"] is False


def test_run_fails_closed_before_any_server_call_without_token(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("AGOMTRADEPRO_API_TOKEN", raising=False)
    monkeypatch.delenv("AGOMTRADEPRO_MCP_URL", raising=False)

    assert main(["run", "hello"]) == 2
    assert "configuration_error:" in capsys.readouterr().err
