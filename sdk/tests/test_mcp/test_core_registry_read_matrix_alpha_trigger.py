# ruff: noqa: F403, F405
"""Core-only read matrix for alpha_trigger."""

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
            "alpha_trigger.read.trigger_list",
            "list_alpha_triggers",
            ("list_alpha_triggers",),
            {},
            {
                "triggers": [
                    {
                        "trigger_id": "trigger-001",
                        "asset_code": "600519.SH",
                        "status": "active",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "trigger-001",
        ),
        (
            "alpha_trigger.read.candidate_list",
            "list_alpha_candidates",
            ("list_alpha_candidates",),
            {},
            {
                "candidates": [
                    {
                        "candidate_id": "candidate-001",
                        "asset_code": "600519.SH",
                        "status": "ACTIONABLE",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "candidate-001",
        ),
        (
            "alpha_trigger.read.candidate_detail",
            "get_alpha_candidate",
            ("get_alpha_candidate",),
            {"candidate_id": "candidate-001"},
            {
                "candidate_id": "candidate-001",
                "trigger_id": "trigger-001",
                "asset_code": "600519.SH",
                "status": "ACTIONABLE",
                "confidence": 0.82,
                "source": "core-only-fallback",
            },
            "600519.SH",
        ),
        (
            "alpha_trigger.read.performance",
            "alpha_trigger_read_performance",
            ("alpha_trigger_performance",),
            {"days": 30, "trigger_id": "trigger-001"},
            {
                "success": True,
                "data": [
                    {
                        "trigger_id": "trigger-001",
                        "asset_code": "600519.SH",
                        "conversion_rate": 50.0,
                    }
                ],
                "summary": {
                    "days": 30,
                    "trigger_id": "trigger-001",
                    "total_triggers": 1,
                },
                "source": "core-only-fallback",
            },
            "conversion_rate",
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
