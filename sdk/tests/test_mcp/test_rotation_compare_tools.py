"""Focused execution coverage for the Rotation asset-comparison raw tool."""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self) -> None:
        self.rotation = SimpleNamespace(
            compare_assets=lambda asset_codes, lookback_days: {
                "calc_date": "2026-07-11",
                "lookback_days": lookback_days,
                "assets": {
                    asset_codes[0]: {
                        "composite_score": 0.12,
                        "ma_signal": "bullish",
                    },
                    asset_codes[1]: {
                        "composite_score": -0.03,
                        "ma_signal": "neutral",
                    },
                },
            },
        )


def test_rotation_compare_executes_through_legacy_raw_tool(
    monkeypatch: pytest.MonkeyPatch,
    legacy_enabled_mcp_server,
) -> None:
    module = importlib.import_module("agomtradepro_mcp.tools.rotation_tools")
    monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)

    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            "compare_assets",
            {
                "asset_codes": ["510300", "511260"],
                "lookback_days": 60,
            },
        )
    )

    rendered = str(result)
    assert "2026-07-11" in rendered
    assert "510300" in rendered
    assert "511260" in rendered
    assert "bullish" in rendered
