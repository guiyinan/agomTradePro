"""Shared MCP server fixtures for core-only and legacy compatibility tests."""

from __future__ import annotations

import importlib

import pytest


def _reload_server_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enable_legacy_tools: bool,
):
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ENABLE_CORE_TOOLS", "true")
    monkeypatch.setenv(
        "AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS",
        "true" if enable_legacy_tools else "false",
    )
    import agomtradepro_mcp.server as server_module

    return importlib.reload(server_module)


@pytest.fixture
def core_only_mcp_server(monkeypatch: pytest.MonkeyPatch):
    """Reload MCP server with only governed core tools enabled."""
    try:
        server_module = _reload_server_module(
            monkeypatch,
            enable_legacy_tools=False,
        )
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    yield server_module.server

    _reload_server_module(monkeypatch, enable_legacy_tools=False)


@pytest.fixture
def legacy_enabled_mcp_server(monkeypatch: pytest.MonkeyPatch):
    """Reload MCP server with legacy raw tools enabled for compatibility tests."""
    try:
        server_module = _reload_server_module(
            monkeypatch,
            enable_legacy_tools=True,
        )
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    yield server_module.server

    _reload_server_module(monkeypatch, enable_legacy_tools=False)
