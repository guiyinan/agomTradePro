"""User-owned local client for the governed remote AgomTradePro MCP registry.

The server remains the authority for capability discovery, schemas, role checks,
confirmation and audit.  This module only adapts the standard MCP client
transport to the four versioned core tools; it never implements a second
business-action registry or manufactures confirmation tokens.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast


class LocalMcpError(RuntimeError):
    """Raised when the remote MCP contract is unavailable or malformed."""


class RemoteMcpConfiguration(Protocol):
    """Minimum configuration required by the remote MCP transport."""

    @property
    def mcp_url(self) -> str | None:
        """Return the configured MCP URL."""

    @property
    def remote_api_token(self) -> str | None:
        """Return the scoped remote token."""

    @property
    def mcp_timeout_seconds(self) -> float:
        """Return the transport timeout."""


class McpSessionPort(Protocol):
    """Narrow standard MCP session surface used by the local facade."""

    async def list_tools(self) -> object:
        """Return the server's MCP tool listing."""

    async def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> object:
        """Call one MCP tool and return its protocol result."""


class RemoteMcpTokenProvider(Protocol):
    """Read a fresh scoped remote token for an explicit reconnect."""

    def get_remote_api_token(self) -> str | None:
        """Return the current user-owned remote token, if available."""


class RemoteMcpSessionOpener(Protocol):
    """Open one authenticated session and return its closeable handle."""

    async def __call__(self, token: str) -> RemoteMcpSessionHandle:
        """Open a session using exactly one scoped token."""


@dataclass(frozen=True, slots=True)
class RemoteMcpReconnectPolicy:
    """Bounded explicit reconnect policy; never retries a capability call."""

    max_attempts: int = 2
    retry_delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or not 1 <= self.max_attempts <= 3
        ):
            raise LocalMcpError("max_attempts must be an integer from 1 to 3")
        if not isinstance(self.retry_delay_seconds, (int, float)) or isinstance(
            self.retry_delay_seconds, bool
        ):
            raise LocalMcpError("retry_delay_seconds must be numeric")
        if not 0 <= float(self.retry_delay_seconds) <= 30:
            raise LocalMcpError("retry_delay_seconds must be between 0 and 30 seconds")


@dataclass(frozen=True, slots=True)
class RemoteMcpSessionHandle:
    """A session plus its transport cleanup callback."""

    session: McpSessionPort
    close: Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RemoteMcpTool:
    """One tool advertised by the remote MCP protocol."""

    name: str
    title: str | None
    description: str | None
    input_schema: Mapping[str, object]
    output_schema: Mapping[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-compatible copy without retaining provider secrets."""

        payload: dict[str, object] = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "input_schema": dict(self.input_schema),
        }
        if self.output_schema is not None:
            payload["output_schema"] = dict(self.output_schema)
        return payload


@dataclass(frozen=True, slots=True)
class RemoteMcpCallResult:
    """Normalized core-tool response returned to the local CLI."""

    ok: bool
    status: str
    payload: Mapping[str, object] = field(repr=False)
    transport_error: bool = False

    @property
    def confirmation_token(self) -> str | None:
        """Return a server-issued pending confirmation token, if present."""

        value = self.payload.get("confirmation_token")
        return value if isinstance(value, str) and value else None

    def as_dict(self) -> dict[str, object]:
        """Return the exact normalized response envelope."""

        return dict(self.payload)


class RemoteMcpCapabilityClient:
    """Call the canonical MCP registry through an already-open session."""

    def __init__(
        self,
        session: McpSessionPort,
        *,
        reconnect_callback: Callable[[], Awaitable[McpSessionPort]] | None = None,
    ) -> None:
        self._session = session
        self._reconnect_callback = reconnect_callback
        self._connection_generation = 0

    @property
    def connection_generation(self) -> int:
        """Return a non-secret counter incremented after explicit reconnect."""

        return self._connection_generation

    async def reconnect(self) -> int:
        """Reconnect explicitly and return the new connection generation.

        No capability call is retried automatically. Callers must decide
        whether a failed read is safe to repeat; mutation calls remain exactly
        once unless their server contract supplies idempotency.
        """

        if self._reconnect_callback is None:
            raise LocalMcpError("remote MCP reconnect is not configured")
        self._session = await self._reconnect_callback()
        self._connection_generation += 1
        return self._connection_generation

    async def list_protocol_tools(self) -> tuple[RemoteMcpTool, ...]:
        """List MCP protocol tools without inferring business permissions."""

        result = await self._session.list_tools()
        raw_tools = getattr(result, "tools", None)
        if not isinstance(raw_tools, Sequence) or isinstance(raw_tools, (str, bytes)):
            raise LocalMcpError("MCP list_tools returned an invalid tools collection")
        tools: list[RemoteMcpTool] = []
        for raw_tool in raw_tools:
            name = _read_string(raw_tool, "name")
            if name is None:
                raise LocalMcpError("MCP list_tools returned a tool without a name")
            input_schema = _read_mapping(raw_tool, "inputSchema")
            if input_schema is None:
                raise LocalMcpError(f"MCP tool {name!r} has no input schema")
            output_schema = _read_mapping(raw_tool, "outputSchema")
            tools.append(
                RemoteMcpTool(
                    name=name,
                    title=_read_string(raw_tool, "title"),
                    description=_read_string(raw_tool, "description"),
                    input_schema=input_schema,
                    output_schema=output_schema,
                )
            )
        return tuple(tools)

    async def bootstrap(self) -> Mapping[str, object]:
        """Read the server registry summary and versioned discovery guidance."""

        return (await self._core_call("agom_bootstrap", {})).payload

    async def discover_capabilities(
        self,
        *,
        query: str = "",
        tags: Sequence[str] = (),
        owner_app: str | None = None,
        risk_level: str | None = None,
        limit: int = 20,
    ) -> tuple[Mapping[str, object], ...]:
        """Search server-registered capabilities using the bounded core API."""

        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise LocalMcpError("capability discovery limit must be an integer from 1 to 20")
        arguments: dict[str, object] = {
            "query": query,
            "tags": list(tags),
            "limit": limit,
        }
        if owner_app is not None:
            arguments["owner_app"] = owner_app
        if risk_level is not None:
            arguments["risk_level"] = risk_level
        payload = (await self._core_call("agom_capability_search", arguments)).payload
        matches = payload.get("matches")
        if not isinstance(matches, Sequence) or isinstance(matches, (str, bytes)):
            raise LocalMcpError("capability discovery returned an invalid matches collection")
        normalized: list[Mapping[str, object]] = []
        for match in matches:
            mapping = _as_mapping(match)
            if mapping is None or not isinstance(mapping.get("capability_key"), str):
                raise LocalMcpError("capability discovery returned an invalid match")
            normalized.append(dict(mapping))
        return tuple(normalized)

    async def get_capability_schema(self, capability_key: str) -> Mapping[str, object]:
        """Read one server-owned capability schema after exact key validation."""

        key = _required_text(capability_key, "capability_key")
        payload = (await self._core_call("agom_capability_schema", {"capability_key": key})).payload
        capability = _as_mapping(payload.get("capability"))
        if capability is None or capability.get("capability_key") != key:
            raise LocalMcpError("capability schema returned an invalid capability payload")
        return dict(capability)

    async def call_capability(
        self,
        capability_key: str,
        *,
        arguments: Mapping[str, object] | None = None,
        context: Mapping[str, object] | None = None,
    ) -> RemoteMcpCallResult:
        """Call one capability through server-side authorization and audit."""

        key = _required_text(capability_key, "capability_key")
        request: dict[str, object] = {
            "capability_key": key,
            "arguments": dict(arguments or {}),
        }
        if context is not None:
            request["context"] = dict(context)
        return await self._core_call("agom_capability_call", request)

    async def resume_confirmation(
        self,
        confirmation_token: str,
        *,
        approve: bool = True,
    ) -> RemoteMcpCallResult:
        """Resume or cancel only a token previously issued by the server."""

        token = _required_text(confirmation_token, "confirmation_token")
        if not isinstance(approve, bool):
            raise LocalMcpError("approve must be a boolean")
        return await self._core_call(
            "agom_confirmation_resume",
            {"confirmation_token": token, "approve": approve},
        )

    async def _core_call(
        self,
        tool_name: str,
        arguments: dict[str, object],
    ) -> RemoteMcpCallResult:
        raw_result = await self._session.call_tool(tool_name, arguments)
        payload = _extract_payload(raw_result)
        transport_error = _read_bool(raw_result, "isError") or _read_bool(raw_result, "is_error")
        ok = payload.get("ok") is True and not transport_error
        status = payload.get("status")
        if not isinstance(status, str) or not status:
            raise LocalMcpError(f"MCP tool {tool_name!r} returned no stable status")
        return RemoteMcpCallResult(
            ok=ok,
            status=status,
            payload=payload,
            transport_error=transport_error,
        )


@contextlib.asynccontextmanager
async def open_remote_mcp_capability_client(
    config: RemoteMcpConfiguration,
    *,
    token_provider: RemoteMcpTokenProvider | None = None,
    reconnect_policy: RemoteMcpReconnectPolicy | None = None,
) -> AsyncIterator[RemoteMcpCapabilityClient]:
    """Open an authenticated streamable-HTTP MCP session for local commands."""

    if config.mcp_url is None:
        raise LocalMcpError("remote MCP configuration is incomplete")
    if config.remote_api_token is None and (
        token_provider is None or token_provider.get_remote_api_token() is None
    ):
        raise LocalMcpError("remote MCP configuration is incomplete")
    connection = RemoteMcpConnection(
        config,
        token_provider=token_provider,
        reconnect_policy=reconnect_policy,
    )
    async with connection as client:
        yield client


class RemoteMcpConnection:
    """Own one MCP transport and rotate its token during explicit reconnect."""

    def __init__(
        self,
        config: RemoteMcpConfiguration,
        *,
        token_provider: RemoteMcpTokenProvider | None = None,
        reconnect_policy: RemoteMcpReconnectPolicy | None = None,
        session_opener: RemoteMcpSessionOpener | None = None,
    ) -> None:
        self._config = config
        self._token_provider = token_provider
        self._reconnect_policy = reconnect_policy or RemoteMcpReconnectPolicy()
        self._session_opener = session_opener or self._open_http_session
        self._handle: RemoteMcpSessionHandle | None = None

    async def __aenter__(self) -> RemoteMcpCapabilityClient:
        """Open the first session and return its governed capability client."""

        session = await self._open_session()
        return RemoteMcpCapabilityClient(session, reconnect_callback=self._reconnect_session)

    async def __aexit__(self, *_args: object) -> None:
        """Close the active transport without suppressing cleanup errors."""

        await self._close_session()

    async def _reconnect_session(self) -> McpSessionPort:
        await self._close_session()
        return await self._open_session()

    async def _open_session(self) -> McpSessionPort:
        token = self._current_token()
        last_error: BaseException | None = None
        for attempt in range(self._reconnect_policy.max_attempts):
            try:
                self._handle = await self._session_opener(token)
                return self._handle.session
            except Exception as exc:  # noqa: BLE001 - transport boundary is redacted below.
                last_error = exc
                if attempt + 1 < self._reconnect_policy.max_attempts:
                    delay = float(self._reconnect_policy.retry_delay_seconds)
                    if delay:
                        await asyncio.sleep(delay)
        raise LocalMcpError("remote MCP connection failed after bounded attempts") from last_error

    async def _close_session(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            await handle.close()

    def _current_token(self) -> str:
        token = self._token_provider.get_remote_api_token() if self._token_provider else None
        value = token or self._config.remote_api_token
        if value is None or not value.strip():
            raise LocalMcpError("remote MCP configuration is incomplete")
        return value

    async def _open_http_session(self, token: str) -> RemoteMcpSessionHandle:
        """Open a standard streamable-HTTP session with one scoped token."""

        try:
            import httpx
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:
            raise LocalMcpError(
                "install the SDK MCP dependencies before using remote capabilities"
            ) from exc

        if self._config.mcp_url is None:
            raise LocalMcpError("remote MCP configuration is incomplete")
        from .local_cli import authorization_header

        headers = {
            "Authorization": authorization_header(token),
            "Accept": "application/json, text/event-stream",
        }
        stack = contextlib.AsyncExitStack()
        await stack.__aenter__()
        try:
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers=headers,
                    timeout=float(self._config.mcp_timeout_seconds),
                )
            )
            streams = await stack.enter_async_context(
                streamable_http_client(self._config.mcp_url, http_client=http_client)
            )
            read_stream, write_stream, _session_id = streams
            session_type = cast(Any, ClientSession)
            session = await stack.enter_async_context(session_type(read_stream, write_stream))
            await session.initialize()
            return RemoteMcpSessionHandle(
                session=cast(McpSessionPort, session),
                close=stack.aclose,
            )
        except BaseException:
            await stack.aclose()
            raise


def _extract_payload(result: object) -> dict[str, object]:
    """Extract one structured JSON envelope from an MCP result."""

    for name in ("structuredContent", "structured_content"):
        structured = _read_value(result, name)
        mapping = _as_mapping(structured)
        if mapping is not None:
            return dict(mapping)
    content = _read_value(result, "content")
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
        for item in content:
            text = _read_string(item, "text")
            if text is None:
                continue
            try:
                decoded = json.loads(text)
            except (TypeError, ValueError) as exc:
                raise LocalMcpError("MCP result text is not valid JSON") from exc
            mapping = _as_mapping(decoded)
            if mapping is not None:
                return dict(mapping)
    raise LocalMcpError("MCP result did not contain a structured JSON envelope")


def _read_value(value: object, name: str) -> object | None:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _read_string(value: object, name: str) -> str | None:
    raw = _read_value(value, name)
    return raw if isinstance(raw, str) else None


def _read_mapping(value: object, name: str) -> Mapping[str, object] | None:
    return _as_mapping(_read_value(value, name))


def _read_bool(value: object, name: str) -> bool:
    raw = _read_value(value, name)
    return raw if isinstance(raw, bool) else False


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if any(not isinstance(key, str) for key in value):
        return None
    return cast(Mapping[str, object], value)


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocalMcpError(f"{name} must be a non-empty string")
    return value.strip()


__all__ = [
    "LocalMcpError",
    "McpSessionPort",
    "RemoteMcpCallResult",
    "RemoteMcpCapabilityClient",
    "RemoteMcpConfiguration",
    "RemoteMcpConnection",
    "RemoteMcpReconnectPolicy",
    "RemoteMcpSessionHandle",
    "RemoteMcpTokenProvider",
    "RemoteMcpTool",
    "open_remote_mcp_capability_client",
]
