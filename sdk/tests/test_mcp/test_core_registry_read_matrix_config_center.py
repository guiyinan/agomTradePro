# ruff: noqa: F403, F405
"""Core-only read matrix for config_center."""

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
            "config_center.read.capability_catalog",
            "list_config_capabilities",
            ("list_config_capabilities",),
            {},
            {
                "capabilities": [
                    {
                        "key": "qlib_runtime",
                        "name": "Qlib Runtime",
                        "permission": "staff",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "qlib_runtime",
        ),
        (
            "config_center.read.qlib_runtime",
            "get_qlib_runtime_config",
            ("get_qlib_runtime_config",),
            {},
            {
                "configured": True,
                "enabled": True,
                "provider_uri": "D:/qlib/cn_data",
                "region": "CN",
                "model_root": "D:/qlib/models",
                "training_task_running": False,
                "validation_errors": [],
                "source": "core-only-fallback",
            },
            "D:/qlib/cn_data",
        ),
        (
            "config_center.read.qlib_training_profiles",
            "list_qlib_training_profiles",
            ("list_qlib_training_profiles",),
            {},
            {
                "profiles": [
                    {
                        "profile_key": "lgb_v1",
                        "name": "LGB V1",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "lgb_v1",
        ),
        (
            "config_center.read.alpha_universe_catalog",
            "list_alpha_universes",
            ("list_alpha_universes",),
            {"include_inactive": True},
            {
                "universes": [
                    {
                        "universe_id": "all_a_share",
                        "is_active": True,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "all_a_share",
        ),
        (
            "config_center.read.alpha_universe_members",
            "get_alpha_universe_members",
            ("get_alpha_universe_members",),
            {"universe_id": "all_a_share", "limit": 100},
            {
                "universe_id": "all_a_share",
                "member_count": 2,
                "members": ["600000.SH", "000001.SZ"],
                "limit": 100,
                "source": "core-only-fallback",
            },
            "600000.SH",
        ),
        (
            "config_center.read.qlib_training_runs",
            "list_qlib_training_runs",
            ("list_qlib_training_runs",),
            {"limit": 20},
            {
                "runs": [
                    {
                        "run_id": "run-001",
                        "status": "SUCCEEDED",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "SUCCEEDED",
        ),
        (
            "config_center.read.qlib_training_run_detail",
            "get_qlib_training_run_detail",
            ("get_qlib_training_run_detail",),
            {"run_id": "run-001"},
            {
                "run_id": "run-001",
                "status": "SUCCEEDED",
                "model_name": "lgb_csi300",
                "model_type": "LGBModel",
                "resolved_train_config": {},
                "result_metrics": {"ic": 0.08},
                "error_message": "",
                "source": "core-only-fallback",
            },
            "lgb_csi300",
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
