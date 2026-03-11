import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self):
        self.config_center = SimpleNamespace(
            list_capabilities=lambda: [{"key": "valuation_repair"}],
            get_snapshot=lambda: {"sections": [{"title": "系统级配置", "items": []}]},
        )


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("list_config_capabilities", {}),
        ("get_config_center_snapshot", {}),
    ],
)
def test_config_center_tools_can_execute(monkeypatch: pytest.MonkeyPatch, tool_name: str, arguments: dict):
    try:
        from agomsaaf_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    module = importlib.import_module("agomsaaf_mcp.tools.config_center_tools")
    monkeypatch.setattr(module, "AgomSAAFClient", _FakeClient)

    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result is not None
