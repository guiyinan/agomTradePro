import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self):
        self.risk_center = SimpleNamespace(
            get_floor=lambda: {"max_total_position_pct": 0.8},
            update_floor=lambda payload: {"updated": payload},
            list_templates=lambda: [{"key": "moderate"}],
            upsert_account_policy=lambda payload: {"policy": payload},
            get_account_policy=lambda account_id: {"account_id": account_id},
            get_effective_policy=lambda account_id: {
                "account_id": account_id,
                "parameters": {"max_total_position_pct": 0.8},
            },
            list_exceptions=lambda account_id=None: [{"account_id": account_id}],
            create_exception=lambda payload: {"exception": payload},
        )


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("get_risk_floor", {}),
        ("update_risk_floor", {"payload": {"max_total_position_pct": 0.75, "reason": "test"}}),
        ("list_risk_templates", {}),
        ("upsert_account_risk_policy", {"payload": {"account_id": 1, "max_total_position_pct": 0.7}}),
        ("get_account_risk_policy", {"account_id": 1}),
        ("get_effective_risk_policy", {"account_id": 1}),
        ("list_risk_exceptions", {"account_id": 1}),
        (
            "create_risk_exception",
            {
                "payload": {
                    "account_id": 1,
                    "field_name": "max_total_position_pct",
                    "allowed_value": 0.9,
                    "reason": "temporary test",
                    "expires_at": "2026-06-28T00:00:00Z",
                }
            },
        ),
    ],
)
def test_risk_center_tools_can_execute(monkeypatch: pytest.MonkeyPatch, tool_name: str, arguments: dict):
    try:
        from agomtradepro_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    module = importlib.import_module("agomtradepro_mcp.tools.risk_center_tools")
    monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)

    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result is not None
