import asyncio
from types import SimpleNamespace

import agomtradepro
from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader


def test_hedge_effectiveness_uses_canonical_sdk_through_core_registry(
    monkeypatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    hedge = SimpleNamespace(
        check_effectiveness=lambda pair_name: calls.append(pair_name)
        or {
            "pair_name": pair_name,
            "correlation": -0.82,
            "beta": -0.7,
            "hedge_ratio": 0.65,
            "hedge_method": "beta",
            "effectiveness": 0.82,
            "rating": "优秀",
            "recommendation": "维持当前配置",
        }
    )
    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(hedge=hedge),
    )

    manifest = CapabilityRegistryLoader().build_registry()["hedge.compute.effectiveness"]
    assert manifest.executor_ref in server_module.INTERNAL_LEGACY_TOOL_FALLBACKS
    assert manifest.legacy_tool_names == (
        "check_hedge_effectiveness",
        "is_my_hedge_still_working",
    )

    response = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "hedge.compute.effectiveness",
                "arguments": {"pair_name": " 股债对冲 "},
            },
        )
    )

    assert "completed" in str(response)
    assert '"is_effective": true' in str(response).lower()
    assert "0.82" in str(response)
    assert calls == ["股债对冲"]
