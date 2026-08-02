"""Repository-local SDK MCP bootstrap shared by Django integration points."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from math import isfinite
from pathlib import Path
from threading import RLock
from typing import Any

from shared.infrastructure.async_runtime import run_awaitable_sync

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SDK_ROOT = REPO_ROOT / "sdk"
MCP_CONFIG_PATH = REPO_ROOT / ".mcp.json"
_ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_ALLOWED_ENV_KEYS = {"NO_PROXY", "no_proxy"}
_SDK_MCP_CALL_LOCK = RLock()
_INTERNAL_IDENTITY_ENV_KEYS = (
    "AGOMTRADEPRO_API_TOKEN",
    "AGOMTRADEPRO_INTERNAL_AUTH_SECRET",
    "AGOMTRADEPRO_INTERNAL_USER_ID",
    "AGOMTRADEPRO_INTERNAL_USERNAME",
    "AGOMTRADEPRO_INTERNAL_SOURCE",
)


def _resolve_internal_auth_secret() -> str:
    """Read the same internal-auth secret used by Django request authentication."""

    environment_secret = str(os.getenv("AGOMTRADEPRO_INTERNAL_AUTH_SECRET") or "").strip()
    if environment_secret:
        return environment_secret
    try:
        from django.conf import settings
        from django.core.exceptions import ImproperlyConfigured
    except ImportError:
        return ""
    try:
        return str(getattr(settings, "AGOMTRADEPRO_INTERNAL_AUTH_SECRET", "") or "").strip()
    except ImproperlyConfigured:
        return ""


def ensure_sdk_on_path() -> None:
    """Put this repository's SDK ahead of unrelated installed checkouts."""

    sdk_path = str(SDK_ROOT)
    if sdk_path in sys.path:
        sys.path.remove(sdk_path)
    sys.path.insert(0, sdk_path)


def load_mcp_env_from_repo_config() -> None:
    """Load non-secret MCP process settings from the optional repository config."""

    if not MCP_CONFIG_PATH.exists():
        return
    try:
        if MCP_CONFIG_PATH.stat().st_size > 1_048_576:
            raise ValueError("MCP config exceeds size limit")
        payload = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("MCP config root must be an object")
        raw_servers = payload.get("mcpServers")
        if raw_servers is None:
            return
        if not isinstance(raw_servers, dict):
            raise ValueError("MCP server catalog must be an object")
        raw_server_conf = raw_servers.get("agomtradepro_local")
        if raw_server_conf is None:
            return
        if not isinstance(raw_server_conf, dict):
            raise ValueError("MCP server config must be an object")
        raw_env = raw_server_conf.get("env")
        if raw_env is None:
            return
        if not isinstance(raw_env, dict) or len(raw_env) > 100:
            raise ValueError("MCP environment must be a bounded object")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.error("Failed to load MCP config error_type=%s", type(exc).__name__)
        return
    for raw_key, value in raw_env.items():
        if not isinstance(raw_key, str) or _ENV_KEY_PATTERN.fullmatch(raw_key) is None:
            continue
        if not (raw_key.startswith("AGOMTRADEPRO_") or raw_key in _ALLOWED_ENV_KEYS):
            continue
        if value is None:
            continue
        if not isinstance(value, str | int | float | bool):
            continue
        if isinstance(value, float) and not isfinite(value):
            continue
        normalized_value = str(value)
        if len(normalized_value) > 16_384 or "\x00" in normalized_value:
            continue
        os.environ.setdefault(raw_key, normalized_value)


@contextmanager
def _sdk_internal_identity(*, user_id: int, username: str) -> Iterator[None]:
    """Bind one originating user to an in-process SDK call without exposing its token."""

    if user_id <= 0:
        raise ValueError("MCP internal user id must be positive")
    normalized_username = str(username or "").strip()
    if len(normalized_username) > 150 or any(ord(char) < 32 for char in normalized_username):
        raise ValueError("MCP internal username is invalid")
    internal_auth_secret = _resolve_internal_auth_secret()
    if not internal_auth_secret:
        raise RuntimeError("MCP internal authentication is not configured")

    previous = {key: os.environ.get(key) for key in _INTERNAL_IDENTITY_ENV_KEYS}
    os.environ.pop("AGOMTRADEPRO_API_TOKEN", None)
    os.environ["AGOMTRADEPRO_INTERNAL_AUTH_SECRET"] = internal_auth_secret
    os.environ["AGOMTRADEPRO_INTERNAL_USER_ID"] = str(user_id)
    os.environ["AGOMTRADEPRO_INTERNAL_USERNAME"] = normalized_username
    os.environ["AGOMTRADEPRO_INTERNAL_SOURCE"] = "ai_capability_route"
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def call_sdk_mcp_tool(
    tool_name: str,
    params: dict[str, Any],
    *,
    user_id: int | None = None,
    username: str = "",
) -> Any:
    """Execute one MCP tool through the repository SDK server contract."""

    normalized_tool_name = tool_name.strip()
    if _TOOL_NAME_PATTERN.fullmatch(normalized_tool_name) is None:
        raise ValueError("MCP tool name has invalid format")
    try:
        encoded_params = json.dumps(params, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("MCP tool parameters must be finite JSON") from exc
    if len(encoded_params.encode("utf-8")) > 1_048_576:
        raise ValueError("MCP tool parameters exceed the 1 MiB limit")
    with _SDK_MCP_CALL_LOCK:
        identity = (
            _sdk_internal_identity(user_id=user_id, username=username)
            if user_id is not None
            else nullcontext()
        )
        with identity:
            ensure_sdk_on_path()
            load_mcp_env_from_repo_config()
            from agomtradepro_mcp.server import server  # type: ignore[import-untyped]

            result = run_awaitable_sync(lambda: server.call_tool(normalized_tool_name, params))
    if isinstance(result, tuple) and len(result) == 2:
        return result[1]
    return result
