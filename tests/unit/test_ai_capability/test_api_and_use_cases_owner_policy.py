# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_policy."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_policy_workbench_bootstrap_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="policy.read.workbench.bootstrap",
        summary="Read the policy workbench bootstrap payload.",
        description="Return the policy workbench bootstrap payload used by operators.",
        owner_app="policy",
        tags=("policy", "workbench", "bootstrap", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_workbench_bootstrap",),
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
                    name="get_workbench_bootstrap",
                    description="policy workbench bootstrap",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.policy.read.workbench.bootstrap"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "policy.read.workbench.bootstrap"
    assert governed.execution_target["replacement_for"] == ["get_workbench_bootstrap"]
    assert governed.semantic_key == "policy.read.workbench.bootstrap"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_workbench_bootstrap"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "policy.read.workbench.bootstrap"
    )
    assert legacy.semantic_key == "policy.read.workbench.bootstrap"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_policy_workbench_event_detail_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="policy.read.workbench.event_detail",
        summary="Read one policy workbench event detail payload.",
        description="Return one policy workbench event detail payload used by operators.",
        owner_app="policy",
        tags=("policy", "workbench", "detail", "read"),
        input_schema={
            "type": "object",
            "properties": {"event_id": {"type": "integer"}},
            "required": ["event_id"],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_workbench_event_detail",),
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
                    name="get_workbench_event_detail",
                    description="policy workbench event detail",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.policy.read.workbench.event_detail"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "policy.read.workbench.event_detail"
    assert governed.execution_target["replacement_for"] == ["get_workbench_event_detail"]
    assert governed.semantic_key == "policy.read.workbench.event_detail"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_workbench_event_detail"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "policy.read.workbench.event_detail"
    )
    assert legacy.semantic_key == "policy.read.workbench.event_detail"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_policy_workbench_summary_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="policy.read.workbench.summary",
        summary="Read the policy workbench summary payload.",
        description="Return the policy workbench summary payload used by operators.",
        owner_app="policy",
        tags=("policy", "workbench", "summary", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_workbench_summary",),
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
                    name="get_workbench_summary",
                    description="policy workbench summary",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.policy.read.workbench.summary"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "policy.read.workbench.summary"
    assert governed.execution_target["replacement_for"] == ["get_workbench_summary"]
    assert governed.semantic_key == "policy.read.workbench.summary"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_workbench_summary"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "policy.read.workbench.summary"
    assert legacy.semantic_key == "policy.read.workbench.summary"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_policy_workbench_items_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="policy.read.workbench.items",
        summary="Read the policy workbench items payload.",
        description="Return the policy workbench items payload used by operators.",
        owner_app="policy",
        tags=("policy", "workbench", "items", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "tab": {"type": "string"},
                "page": {"type": "integer"},
                "page_size": {"type": "integer"},
            },
            "required": [],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_workbench_items",),
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
                    name="get_workbench_items",
                    description="policy workbench items",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.policy.read.workbench.items"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "policy.read.workbench.items"
    assert governed.execution_target["replacement_for"] == ["get_workbench_items"]
    assert governed.semantic_key == "policy.read.workbench.items"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_workbench_items"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "policy.read.workbench.items"
    assert legacy.semantic_key == "policy.read.workbench.items"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_policy_sentiment_gate_state_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="policy.read.sentiment_gate.state",
        summary="Read the policy sentiment-gate state payload.",
        description="Return the policy sentiment-gate state payload used by operators.",
        owner_app="policy",
        tags=("policy", "sentiment_gate", "state", "read"),
        input_schema={
            "type": "object",
            "properties": {"asset_class": {"type": "string"}},
            "required": [],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_sentiment_gate_state",),
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
                    name="get_sentiment_gate_state",
                    description="policy sentiment gate state",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.policy.read.sentiment_gate.state"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "policy.read.sentiment_gate.state"
    assert governed.execution_target["replacement_for"] == ["get_sentiment_gate_state"]
    assert governed.semantic_key == "policy.read.sentiment_gate.state"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_sentiment_gate_state"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "policy.read.sentiment_gate.state"
    )
    assert legacy.semantic_key == "policy.read.sentiment_gate.state"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_policy_approve_workbench_event_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="policy.approve.workbench_event",
        summary="Preview first, then approve a policy workbench event.",
        description="Governed write capability for policy workbench event approval.",
        owner_app="policy",
        tags=("policy", "workbench", "approve", "write"),
        audit_tags=("policy:approve_workbench_event", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
            },
            "required": ["event_id"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("approve_workbench_event",),
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
                    name="approve_workbench_event",
                    description="policy approve workbench event",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.policy.approve.workbench_event"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["approve_workbench_event"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "policy:approve_workbench_event",
        "mcp:write",
    ]
    assert governed.semantic_key == "policy.approve.workbench_event"

    legacy = by_key["mcp_tool.approve_workbench_event"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "policy.approve.workbench_event"
    assert legacy.semantic_key == "policy.approve.workbench_event"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_policy_reject_workbench_event_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="policy.reject.workbench_event",
        summary="Preview first, then reject a policy workbench event.",
        description="Governed write capability for policy workbench event rejection.",
        owner_app="policy",
        tags=("policy", "workbench", "reject", "write"),
        audit_tags=("policy:reject_workbench_event", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["event_id", "reason"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("reject_workbench_event",),
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
                    name="reject_workbench_event",
                    description="policy reject workbench event",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.policy.reject.workbench_event"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["reject_workbench_event"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "policy:reject_workbench_event",
        "mcp:write",
    ]
    assert governed.semantic_key == "policy.reject.workbench_event"

    legacy = by_key["mcp_tool.reject_workbench_event"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "policy.reject.workbench_event"
    assert legacy.semantic_key == "policy.reject.workbench_event"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_policy_rollback_workbench_event_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="policy.rollback.workbench_event",
        summary="Preview first, then roll back a policy workbench event.",
        description="Governed write capability for policy workbench event rollback.",
        owner_app="policy",
        tags=("policy", "workbench", "rollback", "write"),
        audit_tags=("policy:rollback_workbench_event", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["event_id", "reason"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("rollback_workbench_event",),
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
                    name="rollback_workbench_event",
                    description="policy rollback workbench event",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.policy.rollback.workbench_event"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["rollback_workbench_event"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "policy:rollback_workbench_event",
        "mcp:write",
    ]
    assert governed.semantic_key == "policy.rollback.workbench_event"

    legacy = by_key["mcp_tool.rollback_workbench_event"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "policy.rollback.workbench_event"
    )
    assert legacy.semantic_key == "policy.rollback.workbench_event"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_policy_override_workbench_event_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="policy.override.workbench_event",
        summary="Preview first, then override a policy workbench event.",
        description="Governed write capability for policy workbench event override.",
        owner_app="policy",
        tags=("policy", "workbench", "override", "write"),
        audit_tags=("policy:override_workbench_event", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "reason": {"type": "string"},
                "new_level": {"type": "string"},
            },
            "required": ["event_id", "reason"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("override_workbench_event",),
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
                    name="override_workbench_event",
                    description="policy override workbench event",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.policy.override.workbench_event"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["override_workbench_event"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "policy:override_workbench_event",
        "mcp:write",
    ]
    assert governed.semantic_key == "policy.override.workbench_event"

    legacy = by_key["mcp_tool.override_workbench_event"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "policy.override.workbench_event"
    )
    assert legacy.semantic_key == "policy.override.workbench_event"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_policy_create_event_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="policy.create.event",
        summary="Preview first, then create a policy event.",
        description="Governed staff-only policy event creation capability.",
        owner_app="policy",
        tags=("policy", "event", "configuration", "create", "write"),
        audit_tags=("policy:create_event", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "event_date": {"type": "string"},
                "level": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "evidence_url": {"type": "string"},
            },
            "required": [
                "event_date",
                "level",
                "title",
                "description",
                "evidence_url",
            ],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_policy_event",),
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
                    name="create_policy_event",
                    description="create policy event",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.policy.create.event"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_policy_event"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "policy:create_event",
        "mcp:write",
    ]
    assert governed.semantic_key == "policy.create.event"

    legacy = by_key["mcp_tool.create_policy_event"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "policy.create.event"
    assert legacy.semantic_key == "policy.create.event"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_policy_rss_fetch_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="policy.start.rss_fetch",
        summary="Preview first, then start the synchronous RSS fetch.",
        description="Governed staff-only policy RSS ingestion workflow.",
        owner_app="policy",
        tags=("policy", "rss", "fetch", "workflow", "write"),
        audit_tags=("policy:rss_fetch", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "source_id": {"type": "integer"},
                "force_refetch": {"type": "boolean"},
            },
            "required": [],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("trigger_rss_fetch",),
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
                    name="trigger_rss_fetch",
                    description="trigger policy RSS fetch",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}
    governed = by_key["mcp_tool.policy.start.rss_fetch"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["trigger_rss_fetch"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "policy:rss_fetch",
        "mcp:write",
    ]
    assert governed.semantic_key == "policy.start.rss_fetch"

    legacy = by_key["mcp_tool.trigger_rss_fetch"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "policy.start.rss_fetch"
    assert legacy.semantic_key == "policy.start.rss_fetch"
    assert legacy.enabled_for_terminal is False
