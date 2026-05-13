import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self):
        self.config_center = SimpleNamespace(
            list_capabilities=lambda: [{"key": "valuation_repair"}],
            get_snapshot=lambda: {"sections": [{"title": "系统级配置", "items": []}]},
            get_qlib_runtime=lambda: {"enabled": True},
            update_qlib_runtime=lambda payload: {"updated": payload},
            list_qlib_training_profiles=lambda: [{"profile_key": "lgb_v1"}],
            save_qlib_training_profile=lambda payload: {"saved": payload},
            list_qlib_training_runs=lambda limit=20: [{"run_id": "run-1", "limit": limit}],
            get_qlib_training_run_detail=lambda run_id: {"run_id": run_id},
            trigger_qlib_training=lambda payload: {"queued": payload},
        )


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("list_config_capabilities", {}),
        ("get_config_center_snapshot", {}),
        ("get_qlib_runtime_config", {}),
        ("update_qlib_runtime_config", {"enabled": True}),
        (
            "save_qlib_training_profile",
            {
                "profile_key": "lgb_v1",
                "name": "LGB V1",
                "model_name": "lgb_csi300",
                "model_type": "LGBModel",
            },
        ),
        ("list_qlib_training_profiles", {}),
        ("list_qlib_training_runs", {"limit": 5}),
        ("get_qlib_training_run_detail", {"run_id": "run-1"}),
        ("trigger_qlib_training", {"model_name": "lgb_csi300", "model_type": "LGBModel"}),
    ],
)
def test_config_center_tools_can_execute(monkeypatch: pytest.MonkeyPatch, tool_name: str, arguments: dict):
    try:
        from agomtradepro_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    module = importlib.import_module("agomtradepro_mcp.tools.config_center_tools")
    monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)

    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result is not None
