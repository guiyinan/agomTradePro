"""Focused execution coverage for the Rotation correlation legacy alias."""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self) -> None:
        self.rotation = SimpleNamespace(
            get_correlation_matrix=lambda asset_codes, window_days: {
                "calc_date": "2026-07-11",
                "window_days": window_days,
                "assets": asset_codes,
                "correlation_matrix": {
                    asset_codes[0]: {
                        asset_codes[0]: 1.0,
                        asset_codes[1]: -0.35,
                    },
                    asset_codes[1]: {
                        asset_codes[0]: -0.35,
                        asset_codes[1]: 1.0,
                    },
                },
            },
        )


def test_rotation_correlation_executes_through_legacy_alias(
    monkeypatch: pytest.MonkeyPatch,
    legacy_enabled_mcp_server,
) -> None:
    module = importlib.import_module("agomtradepro_mcp.tools.rotation_tools")
    monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)

    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            "get_correlation_matrix",
            {
                "asset_codes": ["510300", "511260"],
                "window_days": 45,
            },
        )
    )

    rendered = str(result)
    assert "2026-07-11" in rendered
    assert "510300" in rendered
    assert "511260" in rendered
    assert "-0.35" in rendered
    assert "45" in rendered
