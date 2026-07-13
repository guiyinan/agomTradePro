# ruff: noqa: F403, F405
"""Core-only read matrix for data_center."""

from .core_registry_support import *


@pytest.mark.parametrize(
    (
        "capability_key",
        "executor_ref",
        "legacy_tool_names",
        "arguments",
        "payload",
        "expected",
    ),
    [
        (
            "data_center.read.price_history",
            "data_center_get_price_history",
            ("data_center_get_price_history", "get_price_history"),
            {
                "asset_code": "000300.SH",
                "start": "2026-04-01",
                "end": "2026-04-21",
                "freq": "1d",
                "adjustment": "qfq",
                "limit": 1,
            },
            {
                "asset_code": "000300.SH",
                "total": 1,
                "data": [
                    {
                        "asset_code": "000300.SH",
                        "bar_date": "2026-04-21",
                        "close": 4768.0,
                    }
                ],
                "source": "core-only-fallback",
            },
            "4768.0",
        ),
        (
            "data_center.read.latest_quote",
            "data_center_get_quotes",
            ("data_center_get_quotes",),
            {
                "asset_code": "510300.SH",
                "strict_freshness": True,
                "max_age_hours": 1.5,
            },
            {
                "asset_code": "510300.SH",
                "current_price": 3.91,
                "freshness_status": "fresh",
                "must_not_use_for_decision": False,
                "source": "core-only-fallback",
            },
            "fresh",
        ),
        (
            "data_center.read.news",
            "data_center_get_news",
            ("data_center_get_news",),
            {"asset_code": "510300.SH", "limit": 5},
            {
                "asset_code": "510300.SH",
                "total": 1,
                "data": [
                    {
                        "title": "ETF market update",
                        "source": "test",
                    }
                ],
                "source": "core-only-fallback",
            },
            "ETF market update",
        ),
        (
            "data_center.read.capital_flows",
            "data_center_get_capital_flows",
            ("data_center_get_capital_flows",),
            {
                "asset_code": "300502.SZ",
                "start": "2026-04-01",
                "end": "2026-04-10",
                "limit": 2,
            },
            {
                "asset_code": "300502.SZ",
                "query": {
                    "start": "2026-04-01",
                    "end": "2026-04-10",
                    "limit": 2,
                },
                "total": 1,
                "data": [
                    {
                        "asset_code": "300502.SZ",
                        "flow_date": "2026-04-10",
                        "main_net": 5600000.0,
                    }
                ],
                "source": "core-only-fallback",
            },
            "5600000.0",
        ),
        (
            "data_center.read.publisher_detail",
            "data_center_get_publisher",
            ("data_center_get_publisher",),
            {"publisher_code": "NBS"},
            {
                "code": "NBS",
                "name": "National Bureau of Statistics",
                "publisher_type": "official",
                "is_active": True,
                "source": "core-only-fallback",
            },
            "official",
        ),
        (
            "data_center.read.publisher_catalog",
            "data_center_list_publishers",
            ("data_center_list_publishers",),
            {"active_only": True},
            {
                "publishers": [
                    {
                        "code": "NBS",
                        "name": "National Bureau of Statistics",
                        "is_active": True,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "NBS",
        ),
        (
            "data_center.read.indicator_detail",
            "data_center_get_indicator",
            ("data_center_get_indicator",),
            {"indicator_code": "CN_PMI"},
            {
                "code": "CN_PMI",
                "name_cn": "制造业PMI",
                "default_period_type": "M",
                "is_active": True,
                "source": "core-only-fallback",
            },
            "CN_PMI",
        ),
        (
            "data_center.read.indicator_unit_rules",
            "data_center_list_indicator_unit_rules",
            ("data_center_list_indicator_unit_rules",),
            {"indicator_code": "CN_PMI"},
            {
                "indicator_code": "CN_PMI",
                "rules": [
                    {
                        "id": 7,
                        "dimension_key": "index_level",
                        "storage_unit": "指数",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "index_level",
        ),
        (
            "data_center.read.indicator_unit_rule_detail",
            "data_center_get_indicator_unit_rule",
            ("data_center_get_indicator_unit_rule",),
            {"indicator_code": "CN_PMI", "rule_id": 7},
            {
                "id": 7,
                "indicator_code": "CN_PMI",
                "dimension_key": "index_level",
                "storage_unit": "指数",
                "source": "core-only-fallback",
            },
            "index_level",
        ),
    ],
)
def test_agom_capability_call_reads_data_family_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
    capability_key,
    executor_ref,
    legacy_tool_names,
    arguments,
    payload,
    expected,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        executor_ref,
        lambda **kwargs: payload,
    )
    assert all(legacy_tool_names)

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": capability_key,
                "arguments": arguments,
            },
        )
    )

    rendered = str(result)
    assert capability_key in rendered
    assert expected in rendered
    assert "core-only-fallback" in rendered
