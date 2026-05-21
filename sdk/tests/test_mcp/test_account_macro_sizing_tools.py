import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self):
        self.account = SimpleNamespace(
            get_macro_sizing_config=lambda: {
                "version": 3,
                "market_temperature_hot_factor": 0.82,
            },
            update_macro_sizing_config=lambda payload, partial=True: {
                "version": 4,
                "partial": partial,
                **payload,
            },
        )


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("get_macro_sizing_config", {}),
        (
            "update_macro_sizing_config",
            {
                "market_temperature_hot_factor": 0.8,
                "market_temperature_overheat_factor": 0.7,
                "partial": True,
            },
        ),
    ],
)
def test_account_macro_sizing_tools_can_execute(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    arguments: dict,
):
    try:
        from agomtradepro_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    module = importlib.import_module("agomtradepro_mcp.tools.account_tools")
    monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)

    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result is not None
