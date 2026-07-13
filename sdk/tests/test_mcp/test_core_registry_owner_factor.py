# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_factor."""

from .core_registry_support import *


def test_factor_catalog_read_fallbacks_use_canonical_sdk_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[str] = []

    class _Factor:
        def get_all_factors(self):
            calls.append("get_all_factors")
            return [
                {
                    "code": "pe_ttm",
                    "name": "市盈率",
                    "category": "value",
                    "direction": "negative",
                },
                {
                    "code": "roe",
                    "name": "净资产收益率",
                    "category": "quality",
                    "direction": "positive",
                },
            ]

        def get_all_configs(self):
            calls.append("get_all_configs")
            return [
                {
                    "name": "价值质量组合",
                    "universe": "all_a",
                    "top_n": 30,
                    "is_active": True,
                }
            ]

    class _Client:
        factor = _Factor()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    definitions = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["factor_read_definition_catalog"]()
    configs = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["factor_read_config_catalog"]()

    assert definitions["total_count"] == 2
    assert definitions["by_category"]["quality"][0]["code"] == "roe"
    assert configs == {
        "configs": [
            {
                "name": "价值质量组合",
                "universe": "all_a",
                "top_n": 30,
                "is_active": True,
            }
        ],
        "total_count": 1,
    }
    assert calls == ["get_all_factors", "get_all_configs"]


def test_factor_top_stocks_fallback_uses_canonical_sdk_method(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[dict[str, str], int]] = []

    class _Factor:
        def get_top_stocks(self, factor_preferences, top_n):
            calls.append((factor_preferences, top_n))
            return {
                "total_stocks": 1,
                "stocks": [
                    {
                        "stock_code": "600000.SH",
                        "composite_score": 88.5,
                    }
                ],
            }

    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(factor=_Factor()),
    )

    result = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["factor_compute_top_stocks"](
        value_preference="high",
        quality_preference="medium",
        growth_preference="low",
        momentum_preference="high",
        top_n=10,
    )

    assert result["total_stocks"] == 1
    assert result["stocks"][0]["stock_code"] == "600000.SH"
    assert calls == [
        (
            {
                "value": "high",
                "quality": "medium",
                "growth": "low",
                "momentum": "high",
            },
            10,
        )
    ]
