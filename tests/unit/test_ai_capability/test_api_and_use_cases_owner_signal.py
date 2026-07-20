# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_signal."""

from .api_and_use_cases_support import *


@pytest.mark.parametrize(
    ("capability_key", "legacy_tool_name"),
    [
        ("signal.read.list", "list_signals"),
        ("signal.read.detail", "get_signal"),
        ("signal.check.eligibility", "check_signal_eligibility"),
    ],
)
def test_sync_mcp_tools_preserves_signal_read_replacements(
    capability_key,
    legacy_tool_name,
):
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key=capability_key,
        summary="Read governed investment signal data.",
        description="Governed read capability for investment signal data.",
        owner_app="signal",
        tags=("signal", "investment", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=(legacy_tool_name,),
    )

    with (
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_capability_manifests",
            return_value=[governed_manifest],
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_core_tool_names",
            return_value={"agom_capability_call", "agom_capability_search"},
        ),
        patch(
            "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
            return_value=[
                SimpleNamespace(name="agom_capability_call", description="core", inputSchema={}),
                SimpleNamespace(
                    name=legacy_tool_name,
                    description="signal read",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key[f"mcp_tool.{capability_key}"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["replacement_for"] == [legacy_tool_name]
    assert governed.semantic_key == capability_key
    assert governed.enabled_for_terminal is True

    legacy = by_key[f"mcp_tool.{legacy_tool_name}"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == capability_key
    assert legacy.semantic_key == capability_key
    assert legacy.enabled_for_terminal is False
