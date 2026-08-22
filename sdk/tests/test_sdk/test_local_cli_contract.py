"""Contract tests for the local Agent CLI and remote MCP boundary."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass

import pytest

from agomtradepro.local_cli import (
    LocalAgentConfig,
    LocalCliConfigurationError,
    authorization_header,
    build_remote_mcp_server,
    main,
    run_local_agent,
    temporary_provider_environment,
)


@dataclass(frozen=True)
class _Credentials:
    provider: str | None
    remote: str | None

    def get_provider_api_key(self) -> str | None:
        return self.provider

    def get_remote_api_token(self) -> str | None:
        return self.remote


@dataclass
class _FakeServer:
    params: dict[str, object]
    entered: bool = False
    exited: bool = False

    async def __aenter__(self) -> _FakeServer:
        self.entered = True
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.exited = True


class _Result:
    final_output = "local result"


def _config() -> LocalAgentConfig:
    return LocalAgentConfig(
        base_url="https://api.example.test",
        mcp_url="https://mcp.example.test/mcp",
        model="test-model",
        provider_api_key="provider-secret",
        remote_api_token="remote-secret",
    )


def test_local_config_reads_local_credentials_and_redacts_diagnostics() -> None:
    config = LocalAgentConfig.from_environment(
        store=_Credentials("provider-secret", "remote-secret"),
        environ={
            "AGOMTRADEPRO_BASE_URL": "https://api.example.test/",
            "AGOMTRADEPRO_MCP_URL": "https://mcp.example.test/mcp?ignored=yes",
            "AGOMTRADEPRO_LOCAL_MODEL": "test-model",
        },
    )

    diagnostics = config.diagnostics()
    assert diagnostics["run_ready"] is True
    rendered = json.dumps(diagnostics)
    assert "provider-secret" not in rendered
    assert "remote-secret" not in rendered
    assert diagnostics["mcp_url"] == "https://mcp.example.test/mcp"
    assert "provider-secret" not in repr(config)


def test_authorization_header_preserves_scheme_and_rejects_control_chars() -> None:
    assert authorization_header("raw-token") == "Token raw-token"
    assert authorization_header("Bearer raw-token") == "Bearer raw-token"
    assert authorization_header("Token raw-token") == "Token raw-token"
    with pytest.raises(LocalCliConfigurationError):
        authorization_header("raw\n-token")


def test_remote_mcp_factory_receives_only_scoped_remote_token() -> None:
    config = _config()
    captured: list[dict[str, object]] = []

    def factory(params: dict[str, object]) -> _FakeServer:
        captured.append(params)
        return _FakeServer(params)

    server = build_remote_mcp_server(config, server_factory=factory)

    assert isinstance(server, _FakeServer)
    assert captured[0]["url"] == "https://mcp.example.test/mcp"
    headers = captured[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Token remote-secret"
    assert "provider-secret" not in repr(captured[0])


def test_provider_environment_is_local_and_restored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "old-provider")
    monkeypatch.delenv("AGOMTRADEPRO_PROVIDER_API_KEY", raising=False)

    with temporary_provider_environment(_config()):
        assert os.environ["OPENAI_API_KEY"] == "provider-secret"
        assert os.environ["AGOMTRADEPRO_PROVIDER_API_KEY"] == "provider-secret"

    assert os.environ["OPENAI_API_KEY"] == "old-provider"
    assert "AGOMTRADEPRO_PROVIDER_API_KEY" not in os.environ


def test_run_local_agent_keeps_provider_key_out_of_remote_mcp() -> None:
    config = _config()
    server = _FakeServer({})
    seen: dict[str, object] = {}

    def factory(params: dict[str, object]) -> _FakeServer:
        server.params = params
        return server

    def agent_factory(*, instructions: str, model: str | None, mcp_servers: list[object]) -> object:
        seen["instructions"] = instructions
        seen["model"] = model
        seen["servers"] = mcp_servers
        return object()

    async def runner(agent: object, prompt: str) -> _Result:
        assert prompt == "show my tasks"
        assert agent is not None
        assert os.environ["OPENAI_API_KEY"] == "provider-secret"
        return _Result()

    result = asyncio.run(
        run_local_agent(
            "show my tasks",
            config,
            server_factory=factory,
            agent_factory=agent_factory,
            runner=runner,
        )
    )

    assert result == "local result"
    assert server.entered is True
    assert server.exited is True
    assert "provider-secret" not in repr(server.params)
    assert "confirmation" in str(seen["instructions"])


def test_doctor_is_safe_when_run_configuration_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in (
        "AGOMTRADEPRO_PROVIDER_API_KEY",
        "OPENAI_API_KEY",
        "AGOMTRADEPRO_API_TOKEN",
        "AGOMTRADEPRO_MCP_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert main(["doctor"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["run_ready"] is False
    assert output["provider_key_configured"] is False
    assert output["remote_token_configured"] is False


def test_run_fails_closed_before_optional_agent_import(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in (
        "AGOMTRADEPRO_PROVIDER_API_KEY",
        "OPENAI_API_KEY",
        "AGOMTRADEPRO_API_TOKEN",
        "AGOMTRADEPRO_MCP_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert main(["run", "hello"]) == 2
    assert "configuration_error:" in capsys.readouterr().err
