# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_decision_rhythm."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_governed_write_confirmation_and_replacement_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="decision.create.execution_request",
        summary="Preview first, then create an execution approval request after confirmation.",
        description="Governed write capability for execution-request creation.",
        owner_app="decision_rhythm",
        tags=("decision", "execution", "approval", "write"),
        audit_tags=("decision:create_execution_request", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"account_id": {"type": "string"}},
            "required": ["account_id"],
        },
        risk_level="medium",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("decision_workflow_preview_execution",),
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
                    name="decision_workflow_preview_execution",
                    description="preview execution",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.decision.create.execution_request"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["decision_workflow_preview_execution"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["idempotency_argument_name"] == "idempotency_key"
    assert governed.execution_target["audit_tags"] == [
        "decision:create_execution_request",
        "mcp:write",
    ]
    assert governed.semantic_key == "decision.create.execution_request"

    legacy = by_key["mcp_tool.decision_workflow_preview_execution"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "decision.create.execution_request"
    )
    assert legacy.semantic_key == "decision.create.execution_request"
    assert legacy.priority_weight == 0.1
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_decision_submit_batch_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="decision.submit.request_batch",
        summary="Preview first, then submit a batch of decision requests.",
        description="Governed write capability for decision rhythm batch submission.",
        owner_app="decision_rhythm",
        tags=("decision", "workflow", "batch", "submit", "write"),
        audit_tags=("decision_rhythm:submit_batch", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"payload": {"type": "object"}},
            "required": ["payload"],
        },
        risk_level="medium",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("submit_batch_decision_request",),
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
                    name="submit_batch_decision_request",
                    description="decision batch submit",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.decision.submit.request_batch"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["submit_batch_decision_request"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "decision_rhythm:submit_batch",
        "mcp:write",
    ]
    assert governed.semantic_key == "decision.submit.request_batch"

    legacy = by_key["mcp_tool.submit_batch_decision_request"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "decision.submit.request_batch"
    assert legacy.semantic_key == "decision.submit.request_batch"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_decision_submit_single_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="decision.submit.request",
        summary="Preview first, then submit a single decision request.",
        description="Governed write capability for decision rhythm single request submission.",
        owner_app="decision_rhythm",
        tags=("decision", "workflow", "submit", "write"),
        audit_tags=("decision_rhythm:submit_request", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {"payload": {"type": "object"}},
            "required": ["payload"],
        },
        risk_level="medium",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("submit_decision_request",),
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
                    name="submit_decision_request",
                    description="decision single submit",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.decision.submit.request"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["submit_decision_request"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "decision_rhythm:submit_request",
        "mcp:write",
    ]
    assert governed.semantic_key == "decision.submit.request"

    legacy = by_key["mcp_tool.submit_decision_request"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "decision.submit.request"
    assert legacy.semantic_key == "decision.submit.request"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_decision_execute_request_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="decision.execute.request",
        summary="Preview first, then execute an approved decision request.",
        description="Governed write capability for decision rhythm request execution.",
        owner_app="decision_rhythm",
        tags=("decision", "workflow", "execution", "write"),
        audit_tags=("decision_rhythm:execute_request", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "payload": {"type": "object"},
            },
            "required": ["request_id", "payload"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("decision_execute_request",),
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
                    name="decision_execute_request",
                    description="decision request execute",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.decision.execute.request"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["decision_execute_request"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "decision_rhythm:execute_request",
        "mcp:write",
    ]
    assert governed.semantic_key == "decision.execute.request"

    legacy = by_key["mcp_tool.decision_execute_request"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "decision.execute.request"
    assert legacy.semantic_key == "decision.execute.request"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_decision_cancel_request_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="decision.cancel.request",
        summary="Preview first, then cancel a decision request.",
        description="Governed write capability for decision rhythm request cancellation.",
        owner_app="decision_rhythm",
        tags=("decision", "workflow", "cancel", "write"),
        audit_tags=("decision_rhythm:cancel_request", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["request_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("decision_cancel_request",),
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
                    name="decision_cancel_request",
                    description="decision request cancel",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.decision.cancel.request"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["decision_cancel_request"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "decision_rhythm:cancel_request",
        "mcp:write",
    ]
    assert governed.semantic_key == "decision.cancel.request"

    legacy = by_key["mcp_tool.decision_cancel_request"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "decision.cancel.request"
    assert legacy.semantic_key == "decision.cancel.request"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_decision_reset_quota_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="decision.reset.quota",
        summary="Preview first, then reset decision quota usage counters.",
        description="Governed write capability for staff-only decision quota reset.",
        owner_app="decision_rhythm",
        tags=("decision", "quota", "reset", "account", "write"),
        audit_tags=("decision_rhythm:reset_quota", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "period": {"type": "string"},
            },
            "required": ["account_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("reset_decision_quota",),
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
                    name="reset_decision_quota",
                    description="reset decision quota",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.decision.reset.quota"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["reset_decision_quota"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "decision_rhythm:reset_quota",
        "mcp:write",
    ]
    assert governed.semantic_key == "decision.reset.quota"

    legacy = by_key["mcp_tool.reset_decision_quota"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "decision.reset.quota"
    assert legacy.semantic_key == "decision.reset.quota"
    assert legacy.enabled_for_terminal is False
