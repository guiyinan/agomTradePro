# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_asset_analysis."""

from .core_registry_support import *


def test_asset_analysis_read_fallbacks_use_canonical_sdk_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    class _AssetAnalysis:
        def get_weight_configs(self):
            calls.append(("get_weight_configs", None))
            return {
                "configs": {
                    "default": {
                        "name": "default",
                        "weights": {
                            "regime": 0.4,
                            "policy": 0.25,
                            "sentiment": 0.2,
                            "signal": 0.15,
                        },
                    }
                },
                "active": "default",
            }

        def get_current_weight(self):
            calls.append(("get_current_weight", None))
            return {
                "success": True,
                "weights": {
                    "regime": 0.4,
                    "policy": 0.25,
                    "sentiment": 0.2,
                    "signal": 0.15,
                },
                "asset_type": None,
                "market_condition": None,
            }

        def pool_summary(self, payload=None):
            calls.append(("pool_summary", payload))
            return {
                "success": True,
                "asset_type": payload["asset_type"] if payload else "all",
                "summary": {
                    "investable": 2,
                    "watch": 1,
                    "candidate": 0,
                    "prohibited": 0,
                    "total": 3,
                },
            }

    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(asset_analysis=_AssetAnalysis()),
    )

    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS[
        "asset_analysis_read_weight_config_catalog"
    ]() == {
        "configs": {
            "default": {
                "name": "default",
                "weights": {
                    "regime": 0.4,
                    "policy": 0.25,
                    "sentiment": 0.2,
                    "signal": 0.15,
                },
            }
        },
        "active": "default",
        "total_count": 1,
    }
    assert (
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["asset_analysis_read_current_weight"]()[
            "success"
        ]
        is True
    )
    assert (
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["asset_analysis_read_pool_summary"]("equity")[
            "asset_type"
        ]
        == "equity"
    )
    assert calls == [
        ("get_weight_configs", None),
        ("get_current_weight", None),
        ("pool_summary", {"asset_type": "equity"}),
    ]
