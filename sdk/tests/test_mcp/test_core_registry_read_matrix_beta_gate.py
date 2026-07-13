# ruff: noqa: F403, F405
"""Core-only read matrix for beta_gate."""

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
            "beta_gate.read.config_catalog",
            "list_beta_gate_configs",
            ("list_beta_gate_configs",),
            {},
            {
                "configs": [
                    {
                        "config_id": "balanced-v1",
                        "risk_profile": "balanced",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "balanced-v1",
        ),
        (
            "beta_gate.compute.config_comparison",
            "compare_beta_gate_configs",
            ("compare_beta_gate_version",),
            {
                "version1": "balanced-v1",
                "version2": "balanced-v2",
            },
            {
                "config1": {
                    "config_id": "balanced-v1",
                    "version": 1,
                    "is_active": False,
                },
                "config2": {
                    "config_id": "balanced-v2",
                    "version": 2,
                    "is_active": True,
                },
                "differences": [
                    {
                        "field": "is_active",
                        "config1": False,
                        "config2": True,
                    }
                ],
                "source": "core-only-fallback",
            },
            "is_active",
        ),
        (
            "beta_gate.compute.batch_evaluation",
            "beta_gate_compute_batch_evaluation",
            ("test_beta_gate",),
            {
                "asset_codes": ["000001.SH", "000300.SH"],
                "asset_class": "equity",
                "current_regime": "Recovery",
                "regime_confidence": 0.6,
                "policy_level": 0,
                "risk_profile": "balanced",
            },
            {
                "config": {
                    "config_id": "balanced-v1",
                    "risk_profile": "balanced",
                    "version": 1,
                },
                "query": {
                    "asset_codes": ["000001.SH", "000300.SH"],
                    "risk_profile": "balanced",
                },
                "results": [{"asset_code": "000001.SH", "passed": True}],
                "summary": {"total": 2, "passed": 2, "blocked": 0},
                "source": "core-only-fallback",
            },
            "balanced-v1",
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
