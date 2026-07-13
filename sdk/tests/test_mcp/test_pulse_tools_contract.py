import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self):
        self.pulse = SimpleNamespace(
            get_action_recommendation=lambda: {
                "success": True,
                "data": {
                    "asset_weights": {},
                    "risk_budget_pct": 0.0,
                    "position_limit_pct": 0.0,
                    "recommended_sectors": [],
                    "benefiting_styles": [],
                    "hedge_recommendation": None,
                    "reasoning": "Pulse 数据未通过 freshness/reliability 校验，联合行动建议已阻断。",
                    "contract": {
                        "must_not_use_for_decision": True,
                        "blocked_code": "pulse_unreliable",
                        "pulse_is_reliable": False,
                        "stale_indicator_codes": ["CN_PMI", "000300.SH"],
                    },
                },
            }
        )


def test_mcp_action_recommendation_exposes_blocked_contract(
    monkeypatch: pytest.MonkeyPatch,
    legacy_enabled_mcp_server,
):
    module = importlib.import_module("agomtradepro_mcp.tools.pulse_tools")
    monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)

    result = asyncio.run(legacy_enabled_mcp_server.call_tool("get_action_recommendation", {}))
    rendered = str(result)

    assert "must_not_use_for_decision" in rendered
    assert "pulse_unreliable" in rendered
    assert "pulse_is_reliable" in rendered
