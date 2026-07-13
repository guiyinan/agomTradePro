# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: owner_risk_center."""

from .api_and_use_cases_support import *


def test_sync_mcp_tools_preserves_risk_center_floor_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.read.floor",
        summary="Read the active global risk floor configuration.",
        description="Return the active global risk floor used by the centralized risk center.",
        owner_app="risk_center",
        tags=("risk_center", "floor", "config", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_risk_floor",),
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
                    name="get_risk_floor",
                    description="risk center floor",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.read.floor"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "risk_center.read.floor"
    assert governed.execution_target["replacement_for"] == ["get_risk_floor"]
    assert governed.semantic_key == "risk_center.read.floor"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_risk_floor"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "risk_center.read.floor"
    assert legacy.semantic_key == "risk_center.read.floor"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_risk_center_template_catalog_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.read.template_catalog",
        summary="Read the active risk template catalog.",
        description="Return the active risk template list used by the centralized risk center.",
        owner_app="risk_center",
        tags=("risk_center", "template", "catalog", "read"),
        input_schema={"type": "object", "properties": {}, "required": []},
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("list_risk_templates",),
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
                    name="list_risk_templates",
                    description="risk center template catalog",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.read.template_catalog"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "risk_center.read.template_catalog"
    assert governed.execution_target["replacement_for"] == ["list_risk_templates"]
    assert governed.semantic_key == "risk_center.read.template_catalog"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.list_risk_templates"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "risk_center.read.template_catalog"
    )
    assert legacy.semantic_key == "risk_center.read.template_catalog"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_risk_center_effective_policy_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.read.effective_policy",
        summary="Read the resolved effective risk policy for a specific account.",
        description="Return the effective account-level risk policy resolved by the centralized risk center.",
        owner_app="risk_center",
        tags=("risk_center", "policy", "effective", "read"),
        input_schema={
            "type": "object",
            "properties": {"account_id": {"type": "integer"}},
            "required": ["account_id"],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_effective_risk_policy",),
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
                    name="get_effective_risk_policy",
                    description="risk center effective policy",
                    inputSchema={"type": "object"},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.read.effective_policy"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "risk_center.read.effective_policy"
    assert governed.execution_target["replacement_for"] == ["get_effective_risk_policy"]
    assert governed.semantic_key == "risk_center.read.effective_policy"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_effective_risk_policy"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "risk_center.read.effective_policy"
    )
    assert legacy.semantic_key == "risk_center.read.effective_policy"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_risk_center_account_policy_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.read.account_policy",
        summary="Read the stored account-level risk policy for a specific account.",
        description="Return the persisted account-level risk policy by account ID.",
        owner_app="risk_center",
        tags=("risk_center", "policy", "account", "read"),
        input_schema={
            "type": "object",
            "properties": {"account_id": {"type": "integer"}},
            "required": ["account_id"],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_account_risk_policy",),
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
                    name="get_account_risk_policy",
                    description="risk center account policy",
                    inputSchema={"type": "object"},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.read.account_policy"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "risk_center.read.account_policy"
    assert governed.execution_target["replacement_for"] == ["get_account_risk_policy"]
    assert governed.semantic_key == "risk_center.read.account_policy"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_account_risk_policy"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "risk_center.read.account_policy"
    )
    assert legacy.semantic_key == "risk_center.read.account_policy"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_risk_center_exception_list_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.read.exception_list",
        summary="Read the active risk exception list, optionally filtered by account.",
        description="Return the current risk exception list from the centralized risk center.",
        owner_app="risk_center",
        tags=("risk_center", "exception", "list", "read"),
        input_schema={
            "type": "object",
            "properties": {"account_id": {"type": "integer"}},
            "required": [],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("list_risk_exceptions",),
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
                    name="list_risk_exceptions",
                    description="risk center exception list",
                    inputSchema={"type": "object"},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.read.exception_list"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "risk_center.read.exception_list"
    assert governed.execution_target["replacement_for"] == ["list_risk_exceptions"]
    assert governed.semantic_key == "risk_center.read.exception_list"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.list_risk_exceptions"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "risk_center.read.exception_list"
    )
    assert legacy.semantic_key == "risk_center.read.exception_list"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_risk_center_pre_trade_check_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.read.pre_trade_check",
        summary="Preview whether a proposed trade would pass centralized risk checks.",
        description="Return the pre-trade risk evaluation for a proposed order.",
        owner_app="risk_center",
        tags=("risk_center", "pre_trade", "risk", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "symbol": {"type": "string"},
                "side": {"type": "string"},
                "quantity": {"type": "number"},
                "price": {"type": "number"},
                "account_equity": {"type": "number"},
                "total_position_value": {"type": "number"},
            },
            "required": [
                "account_id",
                "symbol",
                "side",
                "quantity",
                "price",
                "account_equity",
                "total_position_value",
            ],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("check_pre_trade_risk",),
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
                    name="check_pre_trade_risk",
                    description="risk center pre trade check",
                    inputSchema={"type": "object"},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.read.pre_trade_check"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "risk_center.read.pre_trade_check"
    assert governed.execution_target["replacement_for"] == ["check_pre_trade_risk"]
    assert governed.semantic_key == "risk_center.read.pre_trade_check"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.check_pre_trade_risk"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"] == "risk_center.read.pre_trade_check"
    )
    assert legacy.semantic_key == "risk_center.read.pre_trade_check"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_risk_center_post_investment_check_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.read.post_investment_check",
        summary="Read the post-investment risk evaluation for the current portfolio state.",
        description="Return the post-investment risk evaluation for an account.",
        owner_app="risk_center",
        tags=("risk_center", "post_investment", "risk", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "account_equity": {"type": "number"},
                "positions": {"type": "array"},
            },
            "required": ["account_id", "account_equity"],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("check_post_investment_risk",),
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
                    name="check_post_investment_risk",
                    description="risk center post investment check",
                    inputSchema={"type": "object"},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.read.post_investment_check"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "risk_center.read.post_investment_check"
    assert governed.execution_target["replacement_for"] == ["check_post_investment_risk"]
    assert governed.semantic_key == "risk_center.read.post_investment_check"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.check_post_investment_risk"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "risk_center.read.post_investment_check"
    )
    assert legacy.semantic_key == "risk_center.read.post_investment_check"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_risk_center_daily_report_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.read.daily_report",
        summary="Read a specific risk-center daily report for an account and report date.",
        description="Return the stored daily risk-center report for a specific account and date.",
        owner_app="risk_center",
        tags=("risk_center", "daily_report", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "report_date": {"type": "string"},
            },
            "required": ["account_id", "report_date"],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("get_risk_center_daily_report",),
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
                    name="get_risk_center_daily_report",
                    description="risk center daily report",
                    inputSchema={"type": "object"},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.read.daily_report"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "risk_center.read.daily_report"
    assert governed.execution_target["replacement_for"] == ["get_risk_center_daily_report"]
    assert governed.semantic_key == "risk_center.read.daily_report"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.get_risk_center_daily_report"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "risk_center.read.daily_report"
    assert legacy.semantic_key == "risk_center.read.daily_report"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_risk_center_daily_report_history_read_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.read.daily_report_history",
        summary="Read archived risk-center daily reports by account, single day, or date range.",
        description="Return archived risk-center daily report history from the centralized risk center.",
        owner_app="risk_center",
        tags=("risk_center", "daily_report", "history", "read"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "report_date": {"type": "string"},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        risk_level="low",
        requires_confirmation=False,
        legacy_tool_names=("list_risk_center_daily_reports",),
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
                    name="list_risk_center_daily_reports",
                    description="risk center daily report history",
                    inputSchema={"type": "object"},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.read.daily_report_history"]
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["tool_name"] == "agom_capability_call"
    assert governed.execution_target["capability_key"] == "risk_center.read.daily_report_history"
    assert governed.execution_target["replacement_for"] == ["list_risk_center_daily_reports"]
    assert governed.semantic_key == "risk_center.read.daily_report_history"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.list_risk_center_daily_reports"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert (
        legacy.execution_target["replacement_capability_key"]
        == "risk_center.read.daily_report_history"
    )
    assert legacy.semantic_key == "risk_center.read.daily_report_history"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_risk_center_create_exception_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.create.exception",
        summary="Preview existing exceptions, then create a risk exception.",
        description="Governed write capability for staff risk exception creation.",
        owner_app="risk_center",
        tags=("risk_center", "exception", "override", "create", "write"),
        audit_tags=("risk_center:create_exception", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": ["integer", "null"]},
                "field_name": {"type": "string"},
                "allowed_value": {},
                "reason": {"type": "string"},
                "expires_at": {"type": "string"},
                "is_active": {"type": "boolean"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["field_name", "allowed_value", "reason", "expires_at"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("create_risk_exception",),
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
                    name="create_risk_exception",
                    description="create risk exception",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.create.exception"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["create_risk_exception"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "risk_center:create_exception",
        "mcp:write",
    ]
    assert governed.semantic_key == "risk_center.create.exception"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.create_risk_exception"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == ("risk_center.create.exception")
    assert legacy.semantic_key == "risk_center.create.exception"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_risk_center_update_floor_write_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.update.floor",
        summary="Preview floor changes, then update the global risk floor.",
        description="Governed write capability for staff risk-floor updates.",
        owner_app="risk_center",
        tags=("risk_center", "floor", "configuration", "update", "write"),
        audit_tags=("risk_center:update_floor", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "max_total_position_pct": {"type": "number"},
                "reason": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["reason"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("update_risk_floor",),
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
                    name="update_risk_floor",
                    description="update risk floor",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.update.floor"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["update_risk_floor"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "risk_center:update_floor",
        "mcp:write",
    ]
    assert governed.semantic_key == "risk_center.update.floor"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.update_risk_floor"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == "risk_center.update.floor"
    assert legacy.semantic_key == "risk_center.update.floor"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_risk_center_update_account_policy_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.update.account_policy",
        summary="Preview and upsert an account-scoped risk policy.",
        description="Governed owner-scoped account risk policy write.",
        owner_app="risk_center",
        tags=("risk_center", "account", "policy", "configuration", "update", "write"),
        audit_tags=("risk_center:update_account_policy", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "max_total_position_pct": {"type": "number"},
                "reason": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id", "reason"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("upsert_account_risk_policy",),
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
                    name="upsert_account_risk_policy",
                    description="upsert account risk policy",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.update.account_policy"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["upsert_account_risk_policy"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "risk_center:update_account_policy",
        "mcp:write",
    ]
    assert governed.semantic_key == "risk_center.update.account_policy"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.upsert_account_risk_policy"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == (
        "risk_center.update.account_policy"
    )
    assert legacy.semantic_key == "risk_center.update.account_policy"
    assert legacy.enabled_for_terminal is False


def test_sync_mcp_tools_preserves_risk_center_generate_daily_report_metadata():
    use_case = SyncCapabilitiesUseCase()
    governed_manifest = SimpleNamespace(
        capability_key="risk_center.generate.daily_report",
        summary="Preview and persist a risk-center daily report.",
        description="Governed owner-scoped daily report generation.",
        owner_app="risk_center",
        tags=("risk_center", "daily_report", "generate", "upsert", "write"),
        audit_tags=("risk_center:generate_daily_report", "mcp:write"),
        input_schema={
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "report_date": {"type": "string"},
                "account_equity": {"type": "number"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["account_id", "report_date", "account_equity"],
        },
        risk_level="high",
        requires_confirmation=True,
        idempotency="required",
        legacy_tool_names=("generate_risk_center_daily_report",),
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
                    name="generate_risk_center_daily_report",
                    description="generate risk center daily report",
                    inputSchema={},
                ),
            ],
        ),
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    governed = by_key["mcp_tool.risk_center.generate.daily_report"]
    assert governed.requires_confirmation is True
    assert governed.execution_target["type"] == "mcp_capability"
    assert governed.execution_target["replacement_for"] == ["generate_risk_center_daily_report"]
    assert governed.execution_target["idempotency"] == "required"
    assert governed.execution_target["audit_tags"] == [
        "risk_center:generate_daily_report",
        "mcp:write",
    ]
    assert governed.semantic_key == "risk_center.generate.daily_report"
    assert governed.enabled_for_terminal is True

    legacy = by_key["mcp_tool.generate_risk_center_daily_report"]
    assert legacy.execution_target["type"] == "mcp_tool"
    assert legacy.execution_target["replacement_capability_key"] == (
        "risk_center.generate.daily_report"
    )
    assert legacy.semantic_key == "risk_center.generate.daily_report"
    assert legacy.enabled_for_terminal is False
