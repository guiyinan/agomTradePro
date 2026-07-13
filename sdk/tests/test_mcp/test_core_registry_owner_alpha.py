# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_alpha."""

from .core_registry_support import *


def test_alpha_core_only_fallbacks_use_canonical_sdk_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[str] = []

    class _Alpha:
        def get_provider_status(self):
            calls.append("get_provider_status")
            return {"cache": {"status": "available", "priority": 10}}

        def get_available_universes(self):
            calls.append("get_available_universes")
            return {"universes": ["csi300", "csi500"]}

        def check_health(self):
            calls.append("check_health")
            return {
                "status": "healthy",
                "timestamp": "2026-07-10T12:00:00+00:00",
                "providers": {"available": 2, "total": 3},
            }

        def get_ops_inference_overview(self):
            calls.append("get_ops_inference_overview")
            return {
                "success": True,
                "data": {
                    "active_model": {"model_name": "alpha-v1"},
                    "recent_tasks": [],
                },
            }

        def get_ops_qlib_data_overview(self):
            calls.append("get_ops_qlib_data_overview")
            return {
                "success": True,
                "data": {
                    "local_data_status": {"latest_trade_date": "2026-07-10"},
                    "recent_tasks": [],
                },
            }

    class _Client:
        alpha = _Alpha()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_alpha_provider_status"]() == {
        "cache": {"status": "available", "priority": 10}
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_alpha_available_universes"]() == {
        "universes": ["csi300", "csi500"]
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["check_alpha_health"]() == {
        "status": "healthy",
        "timestamp": "2026-07-10T12:00:00+00:00",
        "providers": {"available": 2, "total": 3},
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["alpha_read_inference_ops_overview"]() == {
        "active_model": {"model_name": "alpha-v1"},
        "recent_tasks": [],
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["alpha_read_qlib_data_ops_overview"]() == {
        "local_data_status": {"latest_trade_date": "2026-07-10"},
        "recent_tasks": [],
    }
    assert calls == [
        "get_provider_status",
        "get_available_universes",
        "check_health",
        "get_ops_inference_overview",
        "get_ops_qlib_data_overview",
    ]
