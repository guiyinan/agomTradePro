"""Thin server-side CLI compatibility facade for AgomTradePro.

The module name is retained for callers of the earlier SDK contract, but the
execution boundary is deliberately server-side. A CLI invocation submits a
request to the authenticated AgomTradePro API; the server owns provider
credentials, model calls, MCP orchestration, confirmation and audit. This
module never imports an Agents SDK, reads a provider key, or runs a local turn
loop.

The remote-MCP helpers remain available for capability inspection and
server-issued confirmation calls. They carry only a scoped AgomTradePro token
and do not execute a provider-backed Agent on the client.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from .client import AgomTradeProClient


class LocalCliConfigurationError(RuntimeError):
    """Raised when the thin server CLI cannot be configured safely."""


class RemoteTokenStore(Protocol):
    """Read one scoped AgomTradePro token for the server API."""

    def get_remote_api_token(self) -> str | None:
        """Return the current scoped server token, if configured."""


@dataclass(frozen=True, slots=True)
class CompositeCredentialStore:
    """Resolve only the scoped server token from environment or keyring."""

    environ: Mapping[str, str] = field(default_factory=lambda: os.environ, repr=False)
    keyring_service: str = "agomtradepro"

    def get_remote_api_token(self) -> str | None:
        """Return ``AGOMTRADEPRO_API_TOKEN`` or a scoped keyring token."""

        value = _nonempty(self.environ.get("AGOMTRADEPRO_API_TOKEN"))
        if value is not None:
            return value
        try:
            import keyring

            return _nonempty(keyring.get_password(self.keyring_service, "api_token"))
        except (ImportError, RuntimeError, OSError):
            return None


@dataclass(frozen=True, slots=True)
class LocalAgentConfig:
    """Legacy-named configuration for the server-side thin CLI.

    ``LocalAgentConfig`` is retained as a source-compatible name only. It has
    no provider key, model, or local execution fields; ``remote_api_token`` is
    the scoped credential used to call the server API.
    """

    base_url: str = "http://127.0.0.1:8000"
    remote_api_token: str | None = field(default=None, repr=False)
    mcp_url: str | None = None
    mcp_timeout_seconds: float = 30.0

    @classmethod
    def from_environment(
        cls,
        store: RemoteTokenStore | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> LocalAgentConfig:
        """Load only server URL, scoped token and optional remote MCP URL."""

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
            remote_api_token=credentials.get_remote_api_token(),
            mcp_url=mcp_url,
            mcp_timeout_seconds=timeout,
        )

    def diagnostics(self) -> dict[str, object]:
        """Return redacted server-side readiness data for ``doctor``."""

        return {
            "base_url": _safe_url(self.base_url),
            "mcp_url": _safe_url(self.mcp_url) if self.mcp_url else None,
            "remote_token_configured": self.remote_api_token is not None,
            "mcp_configured": self.mcp_url is not None,
            "execution_location": "server",
            "provider_key_configured": False,
            "local_agent_enabled": False,
            "run_ready": self._is_server_ready(),
        }

    def require_server_ready(self) -> None:
        """Fail closed unless the scoped server API token is available."""

        if self.remote_api_token is None:
            raise LocalCliConfigurationError("missing server API token")

    def require_remote_ready(self) -> None:
        """Fail closed unless the optional remote MCP transport is configured."""

        missing: list[str] = []
        if self.remote_api_token is None:
            missing.append("server_api_token")
        if self.mcp_url is None:
            missing.append("mcp_url")
        if missing:
            raise LocalCliConfigurationError(", ".join(missing) + " is required")

    def _is_server_ready(self) -> bool:
        return self.remote_api_token is not None


class ServerPromptPort(Protocol):
    """Minimum server prompt surface consumed by the thin CLI."""

    def agent_execute(
        self,
        *,
        task_type: str,
        user_input: str,
    ) -> Mapping[str, object]:
        """Submit one prompt to the server-owned Agent Runtime."""


class ServerClientPort(Protocol):
    """Minimum client surface required for a server-side prompt call."""

    @property
    def prompt(self) -> ServerPromptPort:
        """Return the server prompt API facade."""


class ServerClientFactory(Protocol):
    """Construct an authenticated thin client without provider credentials."""

    def __call__(self, *, base_url: str, api_token: str) -> ServerClientPort:
        """Return a server API client."""


def authorization_header(token: str) -> str:
    """Return a safe DRF/MCP Authorization header for a scoped server token."""

    value = token.strip()
    if not value or "\r" in value or "\n" in value:
        raise LocalCliConfigurationError("server API token is empty or invalid")
    if value.startswith(("Token ", "Bearer ")):
        return value
    return f"Token {value}"


def run_server_agent(
    prompt: str,
    config: LocalAgentConfig,
    *,
    client_factory: ServerClientFactory | None = None,
) -> str:
    """Submit one prompt to the server-side Agent Runtime and return its text."""

    config.require_server_ready()
    if not prompt.strip():
        raise LocalCliConfigurationError("prompt must not be empty")
    if config.remote_api_token is None:
        raise LocalCliConfigurationError("server API token is required")
    factory = client_factory or _default_server_client
    client = factory(base_url=config.base_url, api_token=config.remote_api_token)
    result = client.prompt.agent_execute(task_type="chat", user_input=prompt)
    if not isinstance(result, Mapping):
        raise LocalCliConfigurationError("server returned an invalid Agent result")
    output = result.get("final_answer")
    if output is None:
        output = result.get("output")
    if not isinstance(output, str):
        raise LocalCliConfigurationError("server Agent result has no text output")
    return output


def run_local_agent(
    prompt: str,
    config: LocalAgentConfig,
    *,
    client_factory: ServerClientFactory | None = None,
) -> str:
    """Compatibility alias that always submits to the server."""

    return run_server_agent(prompt, config, client_factory=client_factory)


def run_local_agent_sync(
    prompt: str,
    config: LocalAgentConfig,
    *,
    client_factory: ServerClientFactory | None = None,
) -> str:
    """Compatibility wrapper for callers that use the former sync helper."""

    return run_server_agent(prompt, config, client_factory=client_factory)


def main(argv: list[str] | None = None) -> int:
    """Run server-side prompt or governed remote MCP commands."""

    parser = argparse.ArgumentParser(prog="agomtradepro-cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="show redacted server-side readiness diagnostics")
    run_parser = subparsers.add_parser("run", help="submit a prompt to the server Agent Runtime")
    run_parser.add_argument("prompt", help="user prompt")
    run_parser.add_argument("--json", action="store_true", help="emit a JSON result envelope")
    capabilities_parser = subparsers.add_parser(
        "capabilities", help="discover server-owned MCP capabilities"
    )
    capabilities_parser.add_argument("query", nargs="?", default="")
    capabilities_parser.add_argument("--limit", type=int, default=20)
    schema_parser = subparsers.add_parser("schema", help="read one server capability schema")
    schema_parser.add_argument("capability_key")
    call_parser = subparsers.add_parser("call", help="call one governed server capability")
    call_parser.add_argument("capability_key")
    call_parser.add_argument(
        "--arguments", default="{}", help="JSON object of capability arguments"
    )
    resume_parser = subparsers.add_parser(
        "resume", help="resume or cancel a server-issued confirmation token"
    )
    resume_parser.add_argument("confirmation_token")
    resume_parser.add_argument("--cancel", action="store_true")
    args = parser.parse_args(argv)
    config = LocalAgentConfig.from_environment()
    if args.command == "doctor":
        print(json.dumps(config.diagnostics(), sort_keys=True))
        return 0
    try:
        if args.command == "run":
            output = run_server_agent(args.prompt, config)
            payload: object = {"output": output} if args.json else output
        elif args.command == "capabilities":
            payload = asyncio.run(_run_capability_discovery(config, args.query, args.limit))
        elif args.command == "schema":
            payload = asyncio.run(_run_capability_schema(config, args.capability_key))
        elif args.command == "call":
            arguments = _parse_json_object(args.arguments)
            payload = asyncio.run(_run_capability_call(config, args.capability_key, arguments))
        else:
            payload = asyncio.run(
                _run_confirmation_resume(config, args.confirmation_token, not args.cancel)
            )
    except LocalCliConfigurationError as exc:
        print(f"configuration_error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"input_error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI emits only a stable error class.
        print(f"server_cli_error: {type(exc).__name__}", file=sys.stderr)
        return 1
    if args.command == "run" and not args.json:
        print(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


async def _run_capability_discovery(
    config: LocalAgentConfig,
    query: str,
    limit: int,
) -> list[dict[str, object]]:
    """Run one bounded server-owned capability search."""

    config.require_remote_ready()
    from .local_mcp import open_remote_mcp_capability_client

    async with open_remote_mcp_capability_client(config) as client:
        matches = await client.discover_capabilities(query=query, limit=limit)
    return [dict(match) for match in matches]


async def _run_capability_schema(
    config: LocalAgentConfig,
    capability_key: str,
) -> dict[str, object]:
    """Read one server-owned capability schema."""

    config.require_remote_ready()
    from .local_mcp import open_remote_mcp_capability_client

    async with open_remote_mcp_capability_client(config) as client:
        schema = await client.get_capability_schema(capability_key)
    return dict(schema)


async def _run_capability_call(
    config: LocalAgentConfig,
    capability_key: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Call one server capability while preserving its confirmation envelope."""

    config.require_remote_ready()
    from .local_mcp import open_remote_mcp_capability_client

    async with open_remote_mcp_capability_client(config) as client:
        result = await client.call_capability(capability_key, arguments=arguments)
    return result.as_dict()


async def _run_confirmation_resume(
    config: LocalAgentConfig,
    confirmation_token: str,
    approve: bool,
) -> dict[str, object]:
    """Resume or cancel only a server-issued confirmation token."""

    config.require_remote_ready()
    from .local_mcp import open_remote_mcp_capability_client

    async with open_remote_mcp_capability_client(config) as client:
        result = await client.resume_confirmation(confirmation_token, approve=approve)
    return result.as_dict()


def _default_server_client(*, base_url: str, api_token: str) -> ServerClientPort:
    """Build the typed SDK client used for server-side prompt submission."""

    return cast(ServerClientPort, AgomTradeProClient(base_url=base_url, api_token=api_token))


def _parse_json_object(raw_value: str) -> dict[str, object]:
    """Parse a CLI JSON object without accepting scalar argument envelopes."""

    decoded = json.loads(raw_value)
    if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
        raise ValueError("--arguments must be a JSON object with string keys")
    return cast(dict[str, object], decoded)


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
    "RemoteTokenStore",
    "ServerClientFactory",
    "authorization_header",
    "main",
    "run_local_agent",
    "run_local_agent_sync",
    "run_server_agent",
]


if __name__ == "__main__":  # pragma: no cover - exercised through the package script.
    raise SystemExit(main())
