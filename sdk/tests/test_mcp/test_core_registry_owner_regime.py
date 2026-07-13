# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_regime."""

from .core_registry_support import *


def test_core_registry_loader_rejects_duplicate_capability_keys():
    loader = CapabilityRegistryLoader(module_paths=())
    manifest = CapabilityManifest(
        capability_key="system.read.regime.current",
        title="One",
        summary="One",
        description="One",
        owner_app="regime",
        risk_level="safe",
        executor_kind="legacy_tool",
        executor_ref="get_current_regime",
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {}, "required": []},
    )

    with pytest.raises(CapabilityManifestValidationError):
        loader.validate_manifests([manifest, manifest])


def test_agom_capability_call_bridges_to_legacy_tool(
    monkeypatch: pytest.MonkeyPatch,
    legacy_enabled_mcp_server,
):
    tool_manager = getattr(legacy_enabled_mcp_server, "_tool_manager", None)
    assert tool_manager is not None
    tool_obj = getattr(tool_manager, "_tools", {}).get("get_current_regime")
    assert tool_obj is not None

    monkeypatch.setattr(
        tool_obj,
        "fn",
        lambda **kwargs: {
            "dominant_regime": "Recovery",
            "source": "test-double",
            "kwargs": kwargs,
        },
    )

    result = asyncio.run(
        legacy_enabled_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "system.read.regime.current",
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert "system.read.regime.current" in rendered
    assert "Recovery" in rendered


def test_agom_capability_call_uses_internal_fallback_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_current_regime",
        lambda **kwargs: {
            "dominant_regime": "Recovery",
            "source": "core-only-fallback",
            "kwargs": kwargs,
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "system.read.regime.current",
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert "system.read.regime.current" in rendered
    assert "core-only-fallback" in rendered


def test_regime_navigator_core_only_fallback_uses_canonical_sdk_method(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[str] = []

    class _Pulse:
        def get_navigator(self):
            calls.append("get_navigator")
            return {
                "success": True,
                "data": {
                    "regime_name": "Recovery",
                    "confidence": 0.61,
                    "movement": {"direction": "transitioning"},
                    "asset_guidance": {"risk_budget_pct": 0.85},
                    "watch_indicators": [{"code": "PMI"}],
                },
            }

    class _Client:
        pulse = _Pulse()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_regime_navigator"]() == {
        "regime_name": "Recovery",
        "confidence": 0.61,
        "movement": {"direction": "transitioning"},
        "asset_guidance": {"risk_budget_pct": 0.85},
        "watch_indicators": [{"code": "PMI"}],
    }
    assert calls == ["get_navigator"]


def test_regime_distribution_core_only_fallback_uses_canonical_sdk_method(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[object, object]] = []

    class _Regime:
        def get_regime_distribution(self, start_date=None, end_date=None):
            calls.append((start_date, end_date))
            return {
                "Recovery": 3,
                "Overheat": 1,
                "Stagflation": 0,
                "Deflation": 1,
            }

    class _Client:
        regime = _Regime()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_regime_distribution"](
        start_date="2026-07-01",
        end_date="2026-07-10",
    ) == {
        "distribution": {
            "Recovery": 3,
            "Overheat": 1,
            "Stagflation": 0,
            "Deflation": 1,
        },
        "total_count": 5,
    }
    assert calls == [(date(2026, 7, 1), date(2026, 7, 10))]


def test_regime_calculate_core_only_fallback_uses_canonical_sdk_method(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[dict] = []
    response = {
        "success": True,
        "snapshot": {
            "observed_at": "2026-07-10",
            "dominant_regime": "Recovery",
        },
        "warnings": [],
        "error": None,
    }

    class _Regime:
        def calculate_snapshot(self, **kwargs):
            calls.append(kwargs)
            return response

    class _Client:
        regime = _Regime()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    assert (
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["calculate_regime"](
            as_of_date="2026-07-10",
            use_pit=False,
            growth_indicator="PMI",
            inflation_indicator="CPI",
            data_source="tushare",
        )
        == response
    )
    assert calls == [
        {
            "as_of_date": date(2026, 7, 10),
            "use_pit": False,
            "growth_indicator": "PMI",
            "inflation_indicator": "CPI",
            "data_source": "tushare",
        }
    ]


def test_agom_capability_search_finds_seed_capability(core_only_mcp_server):
    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_search",
            {
                "query": "regime",
                "limit": 10,
            },
        )
    )

    assert "system.read.regime.current" in str(result)
