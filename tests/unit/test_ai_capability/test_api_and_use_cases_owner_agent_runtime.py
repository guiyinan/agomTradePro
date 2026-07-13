# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_agent_runtime."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_agent_proposal_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="agent_proposal.create.proposal",
        summary="Preview first, then create an agent proposal.",
        description="Governed write capability for agent proposal creation.",
        owner_app="agent_runtime",
        tags=("agent_runtime", "proposal", "approval", "write"),
        audit_tags=("agent_runtime:create_proposal", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"proposal_type": {"type": "string"}},
            "required": ["proposal_type"],
        },
        risk_level="medium",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_agent_proposal",),
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
                    name="create_agent_proposal",
                    description="agent proposal create",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.agent_proposal.create.proposal"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_agent_proposal"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "agent_runtime:create_proposal",
        "mcp:write",
    ]
    assert governed.semantic_key == "agent_proposal.create.proposal"

    legacy = by_key["mcp_tool.create_agent_proposal"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "agent_proposal.create.proposal"
    assert legacy.semantic_key == "agent_proposal.create.proposal"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_agent_proposal_execute_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="agent_proposal.execute.proposal",
        summary="Preview first, then execute an approved agent proposal.",
        description="Governed write capability for agent proposal execution.",
        owner_app="agent_runtime",
        tags=("agent_runtime", "proposal", "execution", "guardrail", "write"),
        audit_tags=("agent_runtime:execute_proposal", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"proposal_id": {"type": "integer"}},
            "required": ["proposal_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("execute_agent_proposal",),
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
                    name="execute_agent_proposal",
                    description="agent proposal execute",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.agent_proposal.execute.proposal"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["execute_agent_proposal"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "agent_runtime:execute_proposal",
        "mcp:write",
    ]
    assert governed.semantic_key == "agent_proposal.execute.proposal"

    legacy = by_key["mcp_tool.execute_agent_proposal"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "agent_proposal.execute.proposal"
    )
    assert legacy.semantic_key == "agent_proposal.execute.proposal"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_agent_proposal_approve_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="agent_proposal.approve.proposal",
        summary="Preview first, then approve a submitted agent proposal.",
        description="Governed write capability for agent proposal approval.",
        owner_app="agent_runtime",
        tags=("agent_runtime", "proposal", "approval", "write"),
        audit_tags=("agent_runtime:approve_proposal", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"proposal_id": {"type": "integer"}},
            "required": ["proposal_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("approve_agent_proposal",),
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
                    name="approve_agent_proposal",
                    description="agent proposal approve",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.agent_proposal.approve.proposal"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["approve_agent_proposal"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "agent_runtime:approve_proposal",
        "mcp:write",
    ]
    assert governed.semantic_key == "agent_proposal.approve.proposal"

    legacy = by_key["mcp_tool.approve_agent_proposal"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "agent_proposal.approve.proposal"
    )
    assert legacy.semantic_key == "agent_proposal.approve.proposal"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_agent_proposal_reject_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="agent_proposal.reject.proposal",
        summary="Preview first, then reject a submitted agent proposal.",
        description="Governed write capability for agent proposal rejection.",
        owner_app="agent_runtime",
        tags=("agent_runtime", "proposal", "rejection", "write"),
        audit_tags=("agent_runtime:reject_proposal", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"proposal_id": {"type": "integer"}},
            "required": ["proposal_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("reject_agent_proposal",),
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
                    name="reject_agent_proposal",
                    description="agent proposal reject",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.agent_proposal.reject.proposal"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["reject_agent_proposal"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "agent_runtime:reject_proposal",
        "mcp:write",
    ]
    assert governed.semantic_key == "agent_proposal.reject.proposal"

    legacy = by_key["mcp_tool.reject_agent_proposal"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "agent_proposal.reject.proposal"
    assert legacy.semantic_key == "agent_proposal.reject.proposal"
    assert legacy.enabled_for_terminal is False
