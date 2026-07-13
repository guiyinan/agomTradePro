# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_sector."""

from .core_registry_support import *


def test_agom_capability_call_reads_sector_rotation_ranking_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    manifest = CapabilityRegistryLoader().build_registry()["sector.read.rotation_ranking"]
    assert manifest.legacy_tool_names == (
        "list_sectors",
        "get_sector_recommendations",
        "get_hot_sectors",
    )

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "sector_read_rotation_ranking",
        lambda **kwargs: {
            "success": True,
            "regime": kwargs.get("regime"),
            "analysis_date": "2026-07-12",
            "top_sectors": [
                {
                    "sector_code": "801010",
                    "source": "core-only-fallback",
                }
            ],
            "status": "available",
            "data_source": "persisted",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "sector.read.rotation_ranking",
                "arguments": {
                    "regime": "Recovery",
                    "lookback_days": 30,
                    "level": "SW1",
                    "top_n": 5,
                },
            },
        )
    )

    rendered = str(result)
    assert "sector.read.rotation_ranking" in rendered
    assert "801010" in rendered
    assert "core-only-fallback" in rendered
