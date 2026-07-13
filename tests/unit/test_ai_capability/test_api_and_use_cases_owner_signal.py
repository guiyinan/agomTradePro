# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_signal."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_signal_create_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="signal.create.signal",
        summary="Preview first, then create a pending investment signal.",
        description="Governed write capability for signal creation.",
        owner_app="signal",
        tags=("signal", "investment", "eligibility", "write"),
        audit_tags=("signal:create_signal", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"asset_code": {"type": "string"}},
            "required": ["asset_code"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_signal",),
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
                    name="create_signal",
                    description="signal create",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.signal.create.signal"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_signal"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "signal:create_signal",
        "mcp:write",
    ]
    assert governed.semantic_key == "signal.create.signal"

    legacy = by_key["mcp_tool.create_signal"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "signal.create.signal"
    assert legacy.semantic_key == "signal.create.signal"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_signal_approve_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="signal.approve.signal",
        summary="Preview first, then approve a pending investment signal.",
        description="Governed write capability for signal approval.",
        owner_app="signal",
        tags=("signal", "investment", "approval", "write"),
        audit_tags=("signal:approve_signal", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"signal_id": {"type": "integer"}},
            "required": ["signal_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("approve_signal",),
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
                    name="approve_signal",
                    description="signal approve",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.signal.approve.signal"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["approve_signal"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "signal:approve_signal",
        "mcp:write",
    ]
    assert governed.semantic_key == "signal.approve.signal"

    legacy = by_key["mcp_tool.approve_signal"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "signal.approve.signal"
    assert legacy.semantic_key == "signal.approve.signal"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_signal_reject_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="signal.reject.signal",
        summary="Preview first, then reject a pending investment signal.",
        description="Governed write capability for signal rejection.",
        owner_app="signal",
        tags=("signal", "investment", "rejection", "write"),
        audit_tags=("signal:reject_signal", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"signal_id": {"type": "integer"}},
            "required": ["signal_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("reject_signal",),
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
                    name="reject_signal",
                    description="signal reject",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.signal.reject.signal"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["reject_signal"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "signal:reject_signal",
        "mcp:write",
    ]
    assert governed.semantic_key == "signal.reject.signal"

    legacy = by_key["mcp_tool.reject_signal"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "signal.reject.signal"
    assert legacy.semantic_key == "signal.reject.signal"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_signal_invalidate_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="signal.invalidate.signal",
        summary="Preview first, then invalidate an investment signal.",
        description="Governed write capability for signal invalidation.",
        owner_app="signal",
        tags=("signal", "investment", "invalidation", "write"),
        audit_tags=("signal:invalidate_signal", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"signal_id": {"type": "integer"}},
            "required": ["signal_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("invalidate_signal",),
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
                    name="invalidate_signal",
                    description="signal invalidate",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.signal.invalidate.signal"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["invalidate_signal"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "signal:invalidate_signal",
        "mcp:write",
    ]
    assert governed.semantic_key == "signal.invalidate.signal"

    legacy = by_key["mcp_tool.invalidate_signal"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "signal.invalidate.signal"
    assert legacy.semantic_key == "signal.invalidate.signal"
    assert legacy.enabled_for_terminal is False


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
