"""Local Agent CLI and remote MCP composition for AgomTradePro.

The local runner owns provider credentials.  The remote server receives only
the scoped API/MCP token and tool calls; provider credentials are never placed
in MCP headers, request bodies, or diagnostics.

This module intentionally keeps the optional OpenAI Agents dependency lazy so
the core SDK and the ``doctor`` command remain usable without it installed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, Self, cast
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from agents.mcp import MCPServerStreamableHttpParams


class LocalCliConfigurationError(RuntimeError):
    """Raised when a local CLI run cannot be configured safely."""


class LocalCredentialStore(Protocol):
    """Read credentials owned by the local user host."""

    def get_provider_api_key(self) -> str | None:
        """Return the local model-provider key, if configured."""

    def get_remote_api_token(self) -> str | None:
        """Return the scoped AgomTradePro API token, if configured."""


class RemoteMcpServerFactory(Protocol):
    """Construct a remote MCP server from sanitized transport parameters."""

    def __call__(self, params: dict[str, object]) -> object:
        """Return an async-context-manager MCP server instance."""


class LocalAgentFactory(Protocol):
    """Construct an Agents SDK agent at the local process boundary."""

    def __call__(
        self,
        *,
        instructions: str,
        model: str | None,
        mcp_servers: list[object],
    ) -> object:
        """Return a configured local agent instance."""


class LocalRunner(Protocol):
    """Run a local agent without moving provider credentials to the server."""

    async def __call__(self, agent: object, prompt: str) -> object:
        """Run one prompt and return the provider SDK result."""


@dataclass(frozen=True, slots=True)
class CompositeCredentialStore:
    """Resolve environment credentials before an optional OS keyring.

    The keyring import is deliberately lazy.  A missing keyring package or
    unavailable desktop keyring is treated as an empty fallback, never as a
    reason to copy a secret into the repository or remote MCP request.
    """

    environ: Mapping[str, str] = field(default_factory=lambda: os.environ, repr=False)
    keyring_service: str = "agomtradepro-local"

    def get_provider_api_key(self) -> str | None:
        """Return ``AGOMTRADEPRO_PROVIDER_API_KEY`` or ``OPENAI_API_KEY``."""

        for name in ("AGOMTRADEPRO_PROVIDER_API_KEY", "OPENAI_API_KEY"):
            value = _nonempty(self.environ.get(name))
            if value is not None:
                return value
        return self._get_keyring("provider_api_key")

    def get_remote_api_token(self) -> str | None:
        """Return the scoped remote token from env or the local keyring."""

        value = _nonempty(self.environ.get("AGOMTRADEPRO_API_TOKEN"))
        return value if value is not None else self._get_keyring("remote_api_token")

    def _get_keyring(self, key: str) -> str | None:
        try:
            import keyring

            return _nonempty(keyring.get_password(self.keyring_service, key))
        except (ImportError, RuntimeError, OSError):
            return None


@dataclass(frozen=True, slots=True)
class LocalAgentConfig:
    """Immutable local-run configuration with secrets hidden from ``repr``."""

    base_url: str = "http://127.0.0.1:8000"
    mcp_url: str | None = None
    provider_name: str = "openai"
    model: str | None = None
    provider_api_key: str | None = field(default=None, repr=False)
    remote_api_token: str | None = field(default=None, repr=False)
    mcp_timeout_seconds: float = 30.0

    @classmethod
    def from_environment(
        cls,
        store: LocalCredentialStore | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> Self:
        """Load local configuration without accepting secrets from CLI prompts."""

        env = environ if environ is not None else os.environ
        credentials = store if store is not None else CompositeCredentialStore(environ=env)
        base_url = _normalise_url(
            env.get("AGOMTRADEPRO_BASE_URL")
            or env.get("AGOMTRADEPRO_API_BASE_URL")
            or "http://127.0.0.1:8000",
            "base URL",
        )
        mcp_value = _nonempty(env.get("AGOMTRADEPRO_MCP_URL"))
        mcp_url = _normalise_url(mcp_value, "MCP URL") if mcp_value is not None else None
        timeout_value = _nonempty(env.get("AGOMTRADEPRO_MCP_TIMEOUT_SECONDS"))
        timeout = 30.0
        if timeout_value is not None:
            try:
                timeout = float(timeout_value)
            except ValueError as exc:
                raise LocalCliConfigurationError(
                    "AGOMTRADEPRO_MCP_TIMEOUT_SECONDS must be numeric"
                ) from exc
            if timeout <= 0:
                raise LocalCliConfigurationError(
                    "AGOMTRADEPRO_MCP_TIMEOUT_SECONDS must be positive"
                )
        return cls(
            base_url=base_url,
            mcp_url=mcp_url,
            provider_name=_nonempty(env.get("AGOMTRADEPRO_LOCAL_PROVIDER")) or "openai",
            model=_nonempty(env.get("AGOMTRADEPRO_LOCAL_MODEL")),
            provider_api_key=credentials.get_provider_api_key(),
            remote_api_token=credentials.get_remote_api_token(),
            mcp_timeout_seconds=timeout,
        )

    def diagnostics(self) -> dict[str, object]:
        """Return redacted readiness data suitable for terminal output."""

        return {
            "base_url": _safe_url(self.base_url),
            "mcp_url": _safe_url(self.mcp_url) if self.mcp_url else None,
            "provider": self.provider_name,
            "model_configured": self.model is not None,
            "provider_key_configured": self.provider_api_key is not None,
            "remote_token_configured": self.remote_api_token is not None,
            "mcp_configured": self.mcp_url is not None,
            "run_ready": self._is_run_ready(),
        }

    def require_run_ready(self) -> None:
        """Fail closed unless all local and remote run prerequisites exist."""

        missing: list[str] = []
        if self.provider_api_key is None:
            missing.append("provider_api_key")
        if self.remote_api_token is None:
            missing.append("remote_api_token")
        if self.mcp_url is None:
            missing.append("mcp_url")
        if missing:
            raise LocalCliConfigurationError(
                "missing local CLI configuration: " + ", ".join(missing)
            )

    def _is_run_ready(self) -> bool:
        return (
            self.provider_api_key is not None
            and self.remote_api_token is not None
            and self.mcp_url is not None
        )


def authorization_header(token: str) -> str:
    """Return a safe DRF/MCP Authorization header for a scoped remote token."""

    value = token.strip()
    if not value or "\r" in value or "\n" in value:
        raise LocalCliConfigurationError("remote_api_token is empty or contains invalid characters")
    if value.startswith(("Token ", "Bearer ")):
        return value
    return f"Token {value}"


def build_remote_mcp_server(
    config: LocalAgentConfig,
    *,
    server_factory: RemoteMcpServerFactory | None = None,
) -> object:
    """Build a streamable HTTP MCP client carrying only the remote token."""

    config.require_run_ready()
    if config.mcp_url is None or config.remote_api_token is None:
        raise LocalCliConfigurationError("remote MCP configuration is incomplete")
    params: dict[str, object] = {
        "url": config.mcp_url,
        "headers": {
            "Authorization": authorization_header(config.remote_api_token),
            "Accept": "application/json, text/event-stream",
        },
        "timeout": config.mcp_timeout_seconds,
    }
    if server_factory is not None:
        return server_factory(params)
    try:
        from agents.mcp import MCPServerStreamableHttp
    except ImportError as exc:
        raise LocalCliConfigurationError(
            "install the optional 'agent' dependency to run the local agent"
        ) from exc
    typed_params = cast("MCPServerStreamableHttpParams", params)
    return MCPServerStreamableHttp(params=typed_params, name="agomtradepro-remote")


@contextlib.contextmanager
def temporary_provider_environment(config: LocalAgentConfig) -> Iterator[None]:
    """Expose the provider key only to the local Agents SDK call, then restore it."""

    config.require_run_ready()
    if config.provider_api_key is None:
        raise LocalCliConfigurationError("provider_api_key is required")
    names = ["AGOMTRADEPRO_PROVIDER_API_KEY"]
    if config.provider_name.lower() == "openai":
        names.append("OPENAI_API_KEY")
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ[name] = config.provider_api_key
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


async def run_local_agent(
    prompt: str,
    config: LocalAgentConfig,
    *,
    server_factory: RemoteMcpServerFactory | None = None,
    agent_factory: LocalAgentFactory | None = None,
    runner: LocalRunner | None = None,
) -> str:
    """Run a local provider-backed agent with governed remote MCP tools.

    The remote MCP server is an async context manager.  Its headers contain
    only the scoped API token; the provider key is temporarily available to
    the local provider SDK and is restored before this function returns.
    """

    config.require_run_ready()
    if not prompt.strip():
        raise LocalCliConfigurationError("prompt must not be empty")
    server = build_remote_mcp_server(config, server_factory=server_factory)
    make_agent = agent_factory or _default_agent_factory
    run = runner or _default_runner
    instructions = (
        "You are the AgomTradePro local agent. Use only the capabilities exposed by the "
        "remote MCP server. Never request, print, or transmit provider credentials. "
        "For medium/high-risk mutations, preserve the server confirmation and audit flow; "
        "do not bypass approval or invent tool parameters."
    )
    model = config.model
    agent = make_agent(instructions=instructions, model=model, mcp_servers=[server])
    async with _async_context(server):
        with temporary_provider_environment(config):
            result = await run(agent, prompt)
    output = getattr(result, "final_output", result)
    if not isinstance(output, str):
        raise LocalCliConfigurationError("local agent returned a non-text result")
    return output


def run_local_agent_sync(
    prompt: str,
    config: LocalAgentConfig,
    *,
    server_factory: RemoteMcpServerFactory | None = None,
    agent_factory: LocalAgentFactory | None = None,
    runner: LocalRunner | None = None,
) -> str:
    """Synchronous wrapper for terminal entrypoints."""

    return asyncio.run(
        run_local_agent(
            prompt,
            config,
            server_factory=server_factory,
            agent_factory=agent_factory,
            runner=runner,
        )
    )


def main(argv: list[str] | None = None) -> int:
    """Run ``agomtradepro-agent doctor`` or the local ``run`` command."""

    parser = argparse.ArgumentParser(prog="agomtradepro-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="show redacted local readiness diagnostics")
    run_parser = subparsers.add_parser("run", help="run a local agent through remote MCP")
    run_parser.add_argument("prompt", help="user prompt")
    run_parser.add_argument("--json", action="store_true", help="emit a JSON result envelope")
    args = parser.parse_args(argv)
    config = LocalAgentConfig.from_environment()
    if args.command == "doctor":
        print(json.dumps(config.diagnostics(), sort_keys=True))
        return 0
    try:
        output = run_local_agent_sync(args.prompt, config)
    except LocalCliConfigurationError as exc:
        print(f"configuration_error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI must not print provider/transport details.
        print(f"local_agent_error: {type(exc).__name__}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"output": output}, ensure_ascii=False))
    else:
        print(output)
    return 0


def _default_agent_factory(
    *,
    instructions: str,
    model: str | None,
    mcp_servers: list[object],
) -> object:
    try:
        from agents import Agent
    except ImportError as exc:
        raise LocalCliConfigurationError(
            "install the optional 'agent' dependency to run the local agent"
        ) from exc
    kwargs: dict[str, object] = {
        "name": "AgomTradePro Local Agent",
        "instructions": instructions,
        "mcp_servers": mcp_servers,
    }
    if model is not None:
        kwargs["model"] = model
    agent_constructor = cast(Any, Agent)
    return agent_constructor(**kwargs)


async def _default_runner(agent: object, prompt: str) -> object:
    try:
        from agents import Runner
    except ImportError as exc:
        raise LocalCliConfigurationError(
            "install the optional 'agent' dependency to run the local agent"
        ) from exc
    runner_class = cast(Any, Runner)
    return await runner_class.run(agent, prompt)


@contextlib.asynccontextmanager
async def _async_context(server: object) -> AsyncIterator[object]:
    if not hasattr(server, "__aenter__") or not hasattr(server, "__aexit__"):
        raise LocalCliConfigurationError("remote MCP server is not an async context manager")
    async_server = server
    entered = await async_server.__aenter__()
    try:
        yield entered
    except BaseException as exc:
        suppress = await async_server.__aexit__(type(exc), exc, exc.__traceback__)
        if not suppress:
            raise
    else:
        await async_server.__aexit__(None, None, None)


def _nonempty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalise_url(value: str | None, label: str) -> str:
    if value is None:
        raise LocalCliConfigurationError(f"{label} is required")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LocalCliConfigurationError(f"{label} must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise LocalCliConfigurationError(f"{label} must not contain userinfo")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


__all__ = [
    "CompositeCredentialStore",
    "LocalAgentConfig",
    "LocalCliConfigurationError",
    "LocalCredentialStore",
    "authorization_header",
    "build_remote_mcp_server",
    "main",
    "run_local_agent",
    "run_local_agent_sync",
    "temporary_provider_environment",
]


if __name__ == "__main__":  # pragma: no cover - exercised through the package script.
    raise SystemExit(main())
