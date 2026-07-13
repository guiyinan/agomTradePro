# ruff: noqa: F403, F405
"""Core-only read matrix for alpha."""

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
            "alpha.read.provider_status",
            "get_alpha_provider_status",
            ("get_alpha_provider_status",),
            {},
            {
                "cache": {
                    "priority": 10,
                    "status": "available",
                    "max_staleness_days": 5,
                },
                "source": "core-only-fallback",
            },
            "available",
        ),
        (
            "alpha.read.universe_catalog",
            "get_alpha_available_universes",
            ("get_alpha_available_universes",),
            {},
            {
                "universes": ["csi300", "csi500"],
                "source": "core-only-fallback",
            },
            "csi500",
        ),
        (
            "alpha.read.health",
            "check_alpha_health",
            ("check_alpha_health",),
            {},
            {
                "status": "healthy",
                "timestamp": "2026-07-10T12:00:00+00:00",
                "providers": {"available": 2, "total": 3},
                "source": "core-only-fallback",
            },
            "healthy",
        ),
        (
            "alpha.read.inference_ops_overview",
            "alpha_read_inference_ops_overview",
            ("get_alpha_ops_inference_overview",),
            {},
            {
                "active_model": {"model_name": "alpha-v1"},
                "qlib_runtime": {"enabled": True},
                "celery_health": {"is_healthy": True},
                "dashboard_refresh_locks": [],
                "recent_tasks": [],
                "recent_caches": [],
                "recent_alerts": [],
                "source": "core-only-fallback",
            },
            "alpha-v1",
        ),
        (
            "alpha.read.qlib_data_ops_overview",
            "alpha_read_qlib_data_ops_overview",
            ("get_alpha_ops_qlib_data_overview",),
            {},
            {
                "qlib_runtime": {"enabled": True},
                "local_data_status": {
                    "latest_trade_date": "2026-07-10",
                    "lag_days": 1,
                },
                "recent_tasks": [],
                "latest_build_summary": None,
                "source": "core-only-fallback",
            },
            "2026-07-10",
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
