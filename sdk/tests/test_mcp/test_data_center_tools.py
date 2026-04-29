import asyncio
import importlib
from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self):
        self.data_center = SimpleNamespace(
            list_providers=lambda: [{"id": 1, "name": "tushare-main"}],
            create_provider=lambda payload: {"id": 2, **payload},
            update_provider=lambda provider_id, payload, partial=True: {
                "id": provider_id,
                "partial": partial,
                **payload,
            },
            test_provider_connection=lambda provider_id: {
                "provider_id": provider_id,
                "success": True,
            },
            get_provider_status=lambda: [{"provider_name": "tushare-main", "status": "healthy"}],
            list_indicators=lambda active_only=False: [
                {"code": "CN_PMI", "active_only": active_only}
            ],
            get_indicator=lambda indicator_code: {"code": indicator_code, "name_cn": "制造业PMI"},
            create_indicator=lambda payload: {"ok": True, "payload": payload},
            update_indicator=lambda indicator_code, payload: {
                "indicator_code": indicator_code,
                "payload": payload,
            },
            delete_indicator=lambda indicator_code: {"ok": True, "indicator_code": indicator_code},
            list_indicator_unit_rules=lambda indicator_code: [
                {"id": 7, "indicator_code": indicator_code}
            ],
            get_indicator_unit_rule=lambda indicator_code, rule_id: {
                "indicator_code": indicator_code,
                "id": rule_id,
            },
            create_indicator_unit_rule=lambda indicator_code, payload: {
                "indicator_code": indicator_code,
                "payload": payload,
            },
            update_indicator_unit_rule=lambda indicator_code, rule_id, payload: {
                "indicator_code": indicator_code,
                "id": rule_id,
                "payload": payload,
            },
            delete_indicator_unit_rule=lambda indicator_code, rule_id: {
                "ok": True,
                "indicator_code": indicator_code,
                "id": rule_id,
            },
            get_latest_quotes=lambda asset_code, strict_freshness=None, max_age_hours=None: {
                "asset_code": asset_code,
                "strict_freshness": strict_freshness,
                "max_age_hours": max_age_hours,
                "price": 12.34,
            },
            get_price_history=lambda asset_code, start=None, end=None, limit=None: {
                "asset_code": asset_code,
                "start": start,
                "end": end,
                "limit": limit,
            },
            get_macro_series=lambda indicator_code, start=None, end=None, limit=None: {
                "indicator_code": indicator_code,
                "start": start,
                "end": end,
                "limit": limit,
            },
            sync_macro=lambda payload: {"ok": True, "payload": payload},
            repair_decision_data_reliability=lambda **kwargs: {
                "ok": True,
                "payload": kwargs,
            },
            get_capital_flows=lambda asset_code, period="5d": {
                "asset_code": asset_code,
                "period": period,
            },
            sync_capital_flows=lambda payload: {"ok": True, "payload": payload},
            get_news=lambda asset_code, limit=20: {"asset_code": asset_code, "limit": limit},
            sync_news=lambda payload: {"ok": True, "payload": payload},
        )
        self.config_center = SimpleNamespace(
            list_capabilities=lambda: [{"key": "data_center_providers"}],
            get_snapshot=lambda: {"sections": [{"title": "数据源", "items": []}]},
        )


@pytest.mark.parametrize(
    "tool_name,arguments",
    [
        ("list_data_center_providers", {}),
        ("data_center_list_indicators", {"active_only": True}),
        ("data_center_get_indicator", {"indicator_code": "CN_PMI"}),
        (
            "data_center_create_indicator",
            {"code": "CN_PMI", "name_cn": "制造业PMI", "default_period_type": "M"},
        ),
        ("data_center_update_indicator", {"indicator_code": "CN_PMI", "category": "growth"}),
        ("data_center_delete_indicator", {"indicator_code": "CN_PMI"}),
        ("data_center_list_indicator_unit_rules", {"indicator_code": "CN_PMI"}),
        (
            "data_center_get_indicator_unit_rule",
            {"indicator_code": "CN_PMI", "rule_id": 7},
        ),
        (
            "data_center_create_indicator_unit_rule",
            {
                "indicator_code": "CN_PMI",
                "dimension_key": "index_level",
                "storage_unit": "指数",
                "display_unit": "指数",
                "multiplier_to_storage": 1.0,
            },
        ),
        (
            "data_center_update_indicator_unit_rule",
            {"indicator_code": "CN_PMI", "rule_id": 7, "priority": 2},
        ),
        (
            "data_center_delete_indicator_unit_rule",
            {"indicator_code": "CN_PMI", "rule_id": 7},
        ),
        (
            "create_data_center_provider",
            {"name": "tushare-main", "source_type": "tushare", "api_key": "token"},
        ),
        ("update_data_center_provider", {"provider_id": 1, "priority": 2}),
        ("test_data_center_provider_connection", {"provider_id": 1}),
        ("get_data_center_provider_status", {}),
        ("data_center_get_quotes", {"asset_code": "000001.SZ"}),
        (
            "data_center_get_quotes",
            {"asset_code": "000001.SZ", "strict_freshness": True, "max_age_hours": 1.5},
        ),
        ("data_center_get_price_history", {"asset_code": "000001.SZ", "limit": 5}),
        ("data_center_get_macro_series", {"indicator_code": "CN_PMI", "limit": 12}),
        (
            "data_center_sync_macro",
            {
                "provider_id": 1,
                "indicator_code": "CN_PMI",
                "start": "2026-01-01",
                "end": "2026-03-31",
            },
        ),
        (
            "data_center_repair_decision_data_reliability",
            {
                "target_date": "2026-04-21",
                "portfolio_id": 366,
                "asset_codes": ["510300.SH"],
                "strict": True,
            },
        ),
        ("data_center_get_capital_flows", {"asset_code": "000001.SZ", "period": "10d"}),
        (
            "data_center_sync_capital_flows",
            {"provider_id": 1, "asset_code": "000001.SZ", "period": "5d"},
        ),
        ("data_center_get_news", {"asset_code": "000001.SZ", "limit": 5}),
        ("data_center_sync_news", {"provider_id": 1, "asset_code": "000001.SZ", "limit": 5}),
    ],
)
def test_data_center_tools_execute(
    monkeypatch: pytest.MonkeyPatch, tool_name: str, arguments: dict
):
    try:
        from agomtradepro_mcp.server import server
    except ModuleNotFoundError as exc:
        if "mcp" in str(exc):
            pytest.skip("mcp package not installed in current test environment")
        raise

    for module_name in [
        "agomtradepro_mcp.tools.config_center_tools",
        "agomtradepro_mcp.tools.data_center_tools",
    ]:
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "AgomTradeProClient", _FakeClient)

    result = asyncio.run(server.call_tool(tool_name, arguments))
    assert result is not None
