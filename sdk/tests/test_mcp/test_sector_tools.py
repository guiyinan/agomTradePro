"""Focused execution tests for governed Sector legacy replacements."""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self) -> None:
        def ranking(**kwargs):
            return [
                {
                    "sector_code": "801010",
                    "regime": kwargs.get("regime"),
                    "lookback_days": kwargs.get("lookback_days"),
                    "level": kwargs.get("level"),
                    "limit": kwargs.get("limit"),
                }
            ]

        self.sector = SimpleNamespace(
            list_sectors=ranking,
            get_recommendations=ranking,
            get_hot_sectors=ranking,
        )


@pytest.fixture
def patched_sector_client(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("agomtradepro_mcp.tools.sector_tools")
    monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)


@pytest.mark.parametrize(
    "tool_name",
    ("list_sectors", "get_sector_recommendations", "get_hot_sectors"),
)
def test_sector_ranking_aliases_execute_with_explicit_contract(
    legacy_enabled_mcp_server,
    patched_sector_client: None,
    tool_name: str,
) -> None:
    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            tool_name,
            {
                "regime": "Recovery",
                "lookback_days": 30,
                "level": "SW2",
                "limit": 8,
            },
        )
    )

    rendered = str(result)
    assert "801010" in rendered
    assert "Recovery" in rendered
    assert "30" in rendered
    assert "SW2" in rendered
    assert "8" in rendered
