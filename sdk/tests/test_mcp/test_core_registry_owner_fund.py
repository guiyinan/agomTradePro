# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_fund."""

from .core_registry_support import *


def test_fund_security_code_schemas_require_display_names():
    registry = CapabilityRegistryLoader().build_registry()

    ranking_items = registry["fund.read.ranking"].output_schema["properties"]["funds"]["items"]
    holding_items = registry["fund.read.holdings"].output_schema["properties"]["holdings"]["items"]
    score = registry["fund.read.score"].output_schema["properties"]["score"]
    catalog_items = registry["fund.read.catalog"].output_schema["properties"]["funds"]["items"]

    assert ranking_items["required"] == ["fund_code", "fund_name"]
    assert holding_items["required"] == ["stock_code", "stock_name"]
    assert score["required"] == ["fund_code", "fund_name"]
    assert catalog_items["required"] == ["fund_code", "fund_name"]


def test_fund_core_only_fallbacks_use_canonical_sdk_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    class _Fund:
        def rank_funds(self, **kwargs):
            calls.append(("rank_funds", kwargs))
            return [{"fund_code": "000001", "rank": 1}]

        def screen_funds(self, **kwargs):
            calls.append(("screen_funds", kwargs))
            return {
                "success": True,
                "regime": kwargs.get("regime") or "Recovery",
                "fund_codes": ["000001"],
                "fund_names": ["华夏成长"],
                "screening_criteria": {},
            }

        def get_fund_detail(self, fund_code):
            calls.append(("get_fund_detail", fund_code))
            return {"fund_code": "000001", "fund_name": "华夏成长"}

        def get_nav_history(self, fund_code, **kwargs):
            calls.append(("get_nav_history", (fund_code, kwargs)))
            return [{"fund_code": "000001", "nav_date": "2026-07-09"}]

        def get_holdings(self, fund_code, **kwargs):
            calls.append(("get_holdings", (fund_code, kwargs)))
            return [{"fund_code": "000001", "stock_code": "600519.SH"}]

    class _Client:
        fund = _Fund()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["rank_funds"]("Recovery", 20) == {
        "regime": "Recovery",
        "funds": [{"fund_code": "000001", "rank": 1}],
        "total_count": 1,
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["fund_compute_screen"](
        regime="Recovery",
        custom_types=["股票型"],
        custom_styles=["成长"],
        min_scale=1000000000,
        limit=10,
    )["fund_codes"] == ["000001"]
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_fund_detail"]("000001.OF") == {
        "fund_code": "000001",
        "fund_name": "华夏成长",
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_fund_nav_history"](
        "000001.OF",
        "2026-07-01",
        "2026-07-10",
    ) == {
        "fund_code": "000001",
        "nav_data": [{"fund_code": "000001", "nav_date": "2026-07-09"}],
        "total_count": 1,
        "query": {
            "start_date": "2026-07-01",
            "end_date": "2026-07-10",
        },
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_fund_holdings"](
        "000001.OF",
        "2026-06-30",
    ) == {
        "fund_code": "000001",
        "report_date": "2026-06-30",
        "holdings": [{"fund_code": "000001", "stock_code": "600519.SH"}],
        "total_count": 1,
    }
    assert calls == [
        ("rank_funds", {"regime": "Recovery", "max_count": 20}),
        (
            "screen_funds",
            {
                "regime": "Recovery",
                "custom_types": ["股票型"],
                "custom_styles": ["成长"],
                "min_scale": 1000000000,
                "limit": 10,
            },
        ),
        ("get_fund_detail", "000001.OF"),
        (
            "get_nav_history",
            (
                "000001.OF",
                {
                    "start_date": date(2026, 7, 1),
                    "end_date": date(2026, 7, 10),
                },
            ),
        ),
        (
            "get_holdings",
            (
                "000001.OF",
                {
                    "report_date": date(2026, 6, 30),
                },
            ),
        ),
    ]


def test_agom_capability_call_computes_fund_screen_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    manifest = CapabilityRegistryLoader().build_registry()["fund.compute.screen"]
    assert manifest.legacy_tool_names == ("screen_funds",)

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "fund_compute_screen",
        lambda **kwargs: {
            "success": True,
            "regime": kwargs.get("regime") or "Recovery",
            "fund_codes": ["000001"],
            "fund_names": ["core-only-fallback"],
            "screening_criteria": {},
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "fund.compute.screen",
                "arguments": {
                    "regime": "Recovery",
                    "custom_types": ["股票型"],
                    "limit": 5,
                },
            },
        )
    )

    rendered = str(result)
    assert "fund.compute.screen" in rendered
    assert "000001" in rendered
    assert "core-only-fallback" in rendered
