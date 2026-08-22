"""Contract tests for local capability discovery and confirmation resume."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from agomtradepro.local_mcp import (
    LocalMcpError,
    RemoteMcpCapabilityClient,
    RemoteMcpConnection,
    RemoteMcpReconnectPolicy,
    RemoteMcpSessionHandle,
)


@dataclass(frozen=True)
class _ToolList:
    tools: tuple[object, ...]


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def list_tools(self) -> _ToolList:
        return _ToolList(
            tools=(
                SimpleNamespace(
                    name="agom_capability_call",
                    title="Capability call",
                    description="Call a governed registry capability.",
                    inputSchema={"type": "object"},
                    outputSchema={"type": "object"},
                ),
            )
        )

    async def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> object:
        request = dict(arguments or {})
        self.calls.append((name, request))
        if name == "agom_bootstrap":
            return SimpleNamespace(
                structuredContent={"ok": True, "status": "completed", "capability_count": 1},
                isError=False,
            )
        if name == "agom_capability_search":
            return SimpleNamespace(
                structuredContent={
                    "ok": True,
                    "status": "completed",
                    "matches": [{"capability_key": "account.read.profile", "risk_level": "read"}],
                },
                isError=False,
            )
        if name == "agom_capability_schema":
            return SimpleNamespace(
                structuredContent={
                    "ok": True,
                    "status": "completed",
                    "capability": {
                        "capability_key": request["capability_key"],
                        "input_schema": {"type": "object"},
                    },
                },
                isError=False,
            )
        if name == "agom_capability_call":
            return SimpleNamespace(
                structuredContent={
                    "ok": False,
                    "status": "confirmation_required",
                    "confirmation_token": "server-issued-token",
                },
                isError=False,
            )
        if name == "agom_confirmation_resume":
            return SimpleNamespace(
                structuredContent={"ok": True, "status": "completed", "result": {"stored": True}},
                isError=False,
            )
        raise AssertionError(name)


@dataclass
class _Config:
    mcp_url: str | None = "https://mcp.example.test/mcp"
    remote_api_token: str | None = "config-token"
    mcp_timeout_seconds: float = 5.0


@dataclass
class _TokenProvider:
    value: str | None

    def get_remote_api_token(self) -> str | None:
        return self.value


def test_local_client_reuses_mcp_tool_listing_and_core_registry() -> None:
    session = _Session()
    client = RemoteMcpCapabilityClient(session)

    tools = asyncio.run(client.list_protocol_tools())
    bootstrap = asyncio.run(client.bootstrap())
    matches = asyncio.run(client.discover_capabilities(query="profile", limit=2))

    assert tools[0].name == "agom_capability_call"
    assert tools[0].input_schema == {"type": "object"}
    assert bootstrap["capability_count"] == 1
    assert matches[0]["capability_key"] == "account.read.profile"
    assert session.calls[1] == (
        "agom_capability_search",
        {"query": "profile", "tags": [], "limit": 2},
    )


def test_schema_call_and_confirmation_resume_preserve_server_contract() -> None:
    session = _Session()
    client = RemoteMcpCapabilityClient(session)

    schema = asyncio.run(client.get_capability_schema("account.read.profile"))
    staged = asyncio.run(
        client.call_capability(
            "account.read.profile",
            arguments={"user_id": 7},
            context={"request_id": "req-1"},
        )
    )
    resumed = asyncio.run(client.resume_confirmation(staged.confirmation_token or ""))

    assert schema["capability_key"] == "account.read.profile"
    assert staged.ok is False
    assert staged.status == "confirmation_required"
    assert staged.confirmation_token == "server-issued-token"
    assert resumed.ok is True
    assert session.calls[-2] == (
        "agom_capability_call",
        {
            "capability_key": "account.read.profile",
            "arguments": {"user_id": 7},
            "context": {"request_id": "req-1"},
        },
    )
    assert session.calls[-1] == (
        "agom_confirmation_resume",
        {"confirmation_token": "server-issued-token", "approve": True},
    )


def test_local_client_rejects_invalid_limits_and_malformed_results() -> None:
    session = _Session()
    client = RemoteMcpCapabilityClient(session)

    with pytest.raises(LocalMcpError):
        asyncio.run(client.discover_capabilities(limit=0))
    with pytest.raises(LocalMcpError):
        asyncio.run(client.get_capability_schema(""))

    class _Malformed:
        async def list_tools(self) -> object:
            return object()

        async def call_tool(
            self, _name: str, _arguments: dict[str, object] | None = None
        ) -> object:
            return object()

    with pytest.raises(LocalMcpError):
        asyncio.run(RemoteMcpCapabilityClient(_Malformed()).bootstrap())


def test_result_repr_does_not_render_payload() -> None:
    session = _Session()
    result = asyncio.run(RemoteMcpCapabilityClient(session).call_capability("x"))
    assert "server-issued-token" not in repr(result)


def test_connection_reconnect_rotates_token_without_retrying_capability_calls() -> None:
    provider = _TokenProvider("first-token")
    opened: list[tuple[str, _Session]] = []
    closed: list[str] = []

    async def open_session(token: str) -> RemoteMcpSessionHandle:
        session = _Session()
        opened.append((token, session))

        async def close() -> None:
            closed.append(token)

        return RemoteMcpSessionHandle(session=session, close=close)

    async def scenario() -> None:
        connection = RemoteMcpConnection(
            _Config(),
            token_provider=provider,
            reconnect_policy=RemoteMcpReconnectPolicy(max_attempts=1),
            session_opener=open_session,
        )
        async with connection as client:
            assert client.connection_generation == 0
            await client.bootstrap()
            provider.value = "rotated-token"
            assert await client.reconnect() == 1
            await client.bootstrap()
            assert client.connection_generation == 1

    asyncio.run(scenario())
    assert [token for token, _session in opened] == ["first-token", "rotated-token"]
    assert closed == ["first-token", "rotated-token"]


def test_reconnect_policy_is_bounded_and_client_without_connection_fails_closed() -> None:
    with pytest.raises(LocalMcpError):
        RemoteMcpReconnectPolicy(max_attempts=0)
    with pytest.raises(LocalMcpError):
        asyncio.run(RemoteMcpCapabilityClient(_Session()).reconnect())

    attempts: list[str] = []

    async def failing_opener(token: str) -> RemoteMcpSessionHandle:
        attempts.append(token)
        raise RuntimeError("transport secret must be redacted")

    async def scenario() -> None:
        connection = RemoteMcpConnection(
            _Config(),
            reconnect_policy=RemoteMcpReconnectPolicy(max_attempts=3),
            session_opener=failing_opener,
        )
        with pytest.raises(LocalMcpError, match="bounded attempts"):
            await connection.__aenter__()

    asyncio.run(scenario())
    assert attempts == ["config-token", "config-token", "config-token"]
