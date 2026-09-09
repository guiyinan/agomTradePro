"""Staff tasks for registering data exits and explaining routing decisions."""

from typing import Any

from .tui_metadata_runtime_injection_data_center import _action, _field

_SCREEN = "data-center.egress-config"
_MODULE = "system-governance"
_SOURCE = "approved:runtime-data-center-egress"


def _number(
    key: str,
    label: str,
    *,
    required: bool = False,
    path: bool = False,
    maximum: int | float | None = None,
) -> dict[str, Any]:
    """Build a positive identifier or bounded numeric input."""
    return _field(
        key,
        label,
        binding="path" if path else "body",
        input_type="number",
        value_type="integer",
        presentation_semantic="identifier",
        required=required,
        minimum=1,
        maximum=maximum,
    )


def _endpoint_fields(*, create: bool) -> list[dict[str, Any]]:
    """Keep credentials write-only and partial edits free of default mutations."""
    fields = [] if create else [_number("endpoint_id", "出口编号", required=True, path=True)]
    fields.extend(
        [
            _field("name", "出口名称", required=create),
            _field("region", "出口区域", required=create, placeholder="例如 CN"),
            _field(
                "protocol",
                "连接方式",
                input_type="select",
                required=create,
                options=[
                    {"value": "http", "label": "HTTP 代理"},
                    {"value": "https", "label": "HTTPS 代理"},
                ],
            ),
            _field("host", "代理主机", required=create, placeholder="例如 frpc_egress_visitor"),
            _number("port", "代理端口", required=create, maximum=65535),
            _field("username", "代理账号"),
            _field(
                "password",
                "代理密码（留空保留）",
                input_type="password",
                presentation_semantic="api_token",
            ),
            *(
                []
                if create
                else [
                    _field(
                        "clear_credentials",
                        "清除已保存账号密码",
                        input_type="checkbox",
                        value_type="boolean",
                        default=False,
                    )
                ]
            ),
            _number("concurrency_limit", "最大并发请求数", required=create),
            _field(
                "enabled",
                "启用出口",
                input_type="checkbox",
                value_type="boolean",
                default=False if create else None,
            ),
        ]
    )
    return fields


def _rule_fields(*, create: bool) -> list[dict[str, Any]]:
    """Expose provider, domain and region matching without a freeform config blob."""
    fields = [] if create else [_number("rule_id", "规则编号", required=True, path=True)]
    fields.extend(
        [
            _number("provider_id", "数据源编号", required=create),
            _field(
                "dataset_key", "数据集", required=create, placeholder="行情历史：equity.price.bar"
            ),
            _field(
                "domain_pattern",
                "目标域名",
                required=create,
                placeholder="例如 push2his.eastmoney.com",
            ),
            _field("deployment_region", "执行节点区域", required=create),
            _field(
                "strategy",
                "出网策略",
                input_type="select",
                required=create,
                options=[
                    {"value": "direct", "label": "直连"},
                    {"value": "fixed", "label": "固定出口"},
                    {"value": "direct_fallback", "label": "直连失败后使用备用出口"},
                ],
            ),
            _number("fixed_egress_id", "固定或备用出口编号"),
            _number("priority", "规则优先级（数值小优先）", required=create),
            _field(
                "enabled",
                "启用规则",
                input_type="checkbox",
                value_type="boolean",
                default=False if create else None,
            ),
        ]
    )
    return fields


def _context_fields() -> list[dict[str, Any]]:
    """Collect the actual provider request context for preview or diagnostics."""
    return [
        _number("provider_id", "数据源编号", required=True),
        _field("dataset_key", "数据集", required=True, placeholder="行情历史：equity.price.bar"),
        _field("url", "目标地址", required=True, presentation_semantic="endpoint_url"),
        _field("deployment_region", "执行节点区域", required=True),
    ]


RUNTIME_EGRESS_SCREEN: dict[str, Any] = {
    "key": _SCREEN,
    "dashboard_layout": "task_flow",
    "workflow": {
        "name": "数据连接治理流程",
        "label": "数据出口配置",
        "role": "登记、验证并控制数据中心的区域出网路径。",
        "previous": {"key": "api-library.data-center", "label": "数据与系统健康"},
        "next": {"key": "system.qlib-center", "label": "Qlib 配置与训练"},
    },
    "business_context": {
        "objective": "让数据中心的区域出口和匹配规则可以在一个管理工作区内完成登记、验证与启停。",
        "decision_output": "出口连接状态、规则命中预览和有限诊断结果。",
        "checkpoints": [
            "先登记停用出口和匹配规则，再完成目标连接测试。",
            "测试通过后启用出口与规则，运行请求前先核对数据源和执行区域。",
            "启用前用预览确认策略与出口，异常时查看诊断尝试顺序。",
        ],
    },
    "dashboard_panels": [
        {
            "key": "egress-endpoints",
            "title": "一、已登记数据出口",
            "kind": "datagrid",
            "action_key": "data-center.egress-endpoints",
            "user_priority": "p0",
            "presentation_semantic": "primary_list",
            "layout_area": "endpoints",
            "target_screen": _SCREEN,
            "empty_message": "尚未登记数据出口；先从任务区登记一个停用出口和匹配规则，再执行连接测试。",
            "error_message": "数据出口清单读取失败，请稍后刷新。",
            "stale_message": "出口配置可能已经变化，请刷新后再编辑。",
            "columns": [
                {"key": "id", "label": "编号"},
                {"key": "name", "label": "出口名称"},
                {"key": "region", "label": "区域"},
                {"key": "protocol", "label": "协议"},
                {"key": "host", "label": "代理主机"},
                {"key": "port", "label": "端口"},
                {"key": "concurrency_limit", "label": "并发上限"},
                {"key": "enabled", "label": "启用"},
                {"key": "username_configured", "label": "账号"},
                {"key": "password_configured", "label": "密码"},
            ],
            "row_actions": [
                {
                    "action_key": "data-center.egress-endpoint-update",
                    "label_template": "修改 {name}",
                    "param_map": {"endpoint_id": "id"},
                    "result_panel_key": "egress-receipt",
                    "refresh_panel_key": "egress-endpoints",
                },
                {
                    "action_key": "data-center.egress-endpoint-test",
                    "label_template": "测试 {name}",
                    "param_map": {"endpoint_id": "id"},
                    "result_panel_key": "egress-receipt",
                },
            ],
        },
        {
            "key": "egress-providers",
            "title": "可用数据源",
            "kind": "datagrid",
            "action_key": "data-center.egress-providers",
            "user_priority": "p1",
            "presentation_semantic": "supporting_list",
            "layout_area": "providers",
            "target_screen": _SCREEN,
            "empty_message": "暂无可用数据源；先在数据中心登记并启用一个服务商连接。",
            "error_message": "数据源清单读取失败，请稍后刷新。",
            "stale_message": "数据源状态可能已经变化，请刷新后再配置规则。",
            "columns": [
                {"key": "id", "label": "编号"},
                {"key": "name", "label": "数据源"},
                {"key": "source_type", "label": "类型"},
                {"key": "tushare_request_mode_label", "label": "连接方式"},
                {"key": "is_active", "label": "启用"},
                {"key": "http_url", "label": "服务地址"},
            ],
            "row_actions": [
                {
                    "action_key": "data-center.egress-rule-create",
                    "label_template": "为 {name} 新增规则",
                    "param_map": {"provider_id": "id"},
                    "result_panel_key": "egress-receipt",
                    "refresh_panel_key": "egress-rules",
                }
            ],
        },
        {
            "key": "egress-rules",
            "title": "二、数据出网规则",
            "kind": "datagrid",
            "action_key": "data-center.egress-rules",
            "user_priority": "p0",
            "presentation_semantic": "primary_list",
            "layout_area": "rules",
            "target_screen": _SCREEN,
            "empty_message": "尚未配置规则；先为数据源登记停用规则，测试通过后再启用。",
            "error_message": "出网规则读取失败，请稍后刷新。",
            "stale_message": "规则可能已经变化，请刷新后再编辑。",
            "columns": [
                {"key": "id", "label": "编号"},
                {"key": "provider_id", "label": "数据源编号"},
                {"key": "provider_name", "label": "数据源"},
                {"key": "dataset_key", "label": "数据集"},
                {"key": "domain_pattern", "label": "目标域名"},
                {"key": "deployment_region", "label": "执行区域"},
                {"key": "strategy_label", "label": "策略"},
                {"key": "fixed_egress_id", "label": "出口编号"},
                {"key": "egress_name", "label": "固定出口"},
                {"key": "enabled", "label": "启用"},
                {"key": "priority", "label": "优先级"},
            ],
            "row_actions": [
                {
                    "action_key": "data-center.egress-rule-update",
                    "label_template": "修改规则 {id}",
                    "param_map": {"rule_id": "id"},
                    "result_panel_key": "egress-receipt",
                    "refresh_panel_key": "egress-rules",
                },
                {
                    "action_key": "data-center.egress-preview",
                    "label_template": "预览 {domain_pattern}",
                    "param_map": {
                        "provider_id": "provider_id",
                        "dataset_key": "dataset_key",
                        "deployment_region": "deployment_region",
                    },
                    "result_panel_key": "egress-receipt",
                },
            ],
        },
        {
            "key": "egress-next-steps",
            "title": "三、配置步骤",
            "kind": "detail",
            "action_key": "data-center.egress-endpoint-create",
            "user_priority": "p1",
            "presentation_semantic": "next_step",
            "layout_area": "next_steps",
            "target_screen": _SCREEN,
            "empty_message": "登记停用出口和停用规则后执行测试；确认成功后依次启用出口、规则并预览命中结果。",
        },
        {
            "key": "egress-receipt",
            "title": "四、最近操作回执",
            "kind": "detail",
            "user_priority": "p1",
            "presentation_semantic": "primary_status",
            "layout_area": "receipt",
            "target_screen": _SCREEN,
            "empty_message": "从出口或规则清单选择修改、测试或预览操作。",
        },
        {
            "key": "egress-endpoint-create",
            "title": "登记新的数据出口",
            "kind": "detail",
            "action_key": "data-center.egress-endpoint-create",
            "user_priority": "p2",
            "presentation_semantic": "next_step",
            "layout_area": "forms",
            "target_screen": _SCREEN,
            "empty_message": "填写出口地址和连接参数，保存后先完成连接测试。",
        },
        {
            "key": "egress-rule-create",
            "title": "新增数据出网规则",
            "kind": "detail",
            "action_key": "data-center.egress-rule-create",
            "user_priority": "p2",
            "presentation_semantic": "next_step",
            "layout_area": "forms",
            "target_screen": _SCREEN,
            "empty_message": "填写数据源、数据集、域名和执行区域，再选择出网策略。",
        },
        {
            "key": "egress-preview",
            "title": "预览规则命中",
            "kind": "detail",
            "action_key": "data-center.egress-preview",
            "user_priority": "p2",
            "presentation_semantic": "next_step",
            "layout_area": "diagnostics",
            "target_screen": _SCREEN,
            "empty_message": "填写一次请求上下文，确认会选择直连还是指定出口。",
        },
        {
            "key": "egress-diagnostics",
            "title": "诊断目标连接",
            "kind": "detail",
            "action_key": "data-center.egress-diagnostics",
            "user_priority": "p2",
            "presentation_semantic": "next_step",
            "layout_area": "diagnostics",
            "target_screen": _SCREEN,
            "empty_message": "对已允许的目标执行有限诊断，查看每次尝试的状态和耗时。",
        },
    ],
}


def _egress_action(
    key: str,
    label: str,
    endpoint: str,
    fields: list[dict[str, Any]],
    *,
    method: str = "POST",
    columns: list[dict[str, str]] | None = None,
    description: str,
    task_group: str = "01 数据出口",
    sequence: int = 600,
    task_tier: str = "operation",
    effect: str | None = None,
    confirmation_required: bool | None = None,
    audit_required: bool | None = None,
) -> dict[str, Any]:
    """Build one staff action for the dedicated data-egress workbench."""
    action = _action(
        key="data-center.egress-" + key,
        label=label,
        endpoint=(
            endpoint if endpoint.startswith("/api/") else "/api/data-center/egress/" + endpoint
        ),
        intent="data_center_egress_" + key.replace("-", "_"),
        method=method,
        effect=(
            effect
            if effect is not None
            else ("read" if method == "GET" or key == "preview" else "update")
        ),
        view_type="datagrid" if columns else "detail",
        description=description,
        task_group=task_group,
        sequence=sequence,
        fields=fields,
        confirmation_required=(
            confirmation_required
            if confirmation_required is not None
            else method != "GET" and key != "preview"
        ),
        audit_required=(
            audit_required if audit_required is not None else method != "GET" and key != "preview"
        ),
        view_model=(
            {"kind": "datagrid", "rows_path": "results", "columns": columns}
            if columns
            else {
                "kind": "detail",
                "field_presentations": {"checked_at": "metadata", "attempts": "multiline"},
            }
        ),
    )
    action["screen_key"] = _SCREEN
    action["module_key"] = _MODULE
    action["source"] = _SOURCE
    action["task_tier"] = task_tier
    action["result_semantics"] = ["primary_list"] if columns else ["primary_status"]
    return action


RUNTIME_EGRESS_ACTIONS: tuple[dict[str, Any], ...] = (
    _egress_action(
        "endpoints",
        "查看数据出口",
        "endpoints/",
        [],
        method="GET",
        description="查看已登记的出口和连接设置。",
        task_group="01 出口清单",
        sequence=10,
        task_tier="support",
        columns=[
            {"key": "id", "label": "编号"},
            {"key": "name", "label": "出口名称"},
            {"key": "region", "label": "区域"},
            {"key": "protocol", "label": "协议"},
            {"key": "host", "label": "代理主机"},
            {"key": "port", "label": "端口"},
            {"key": "concurrency_limit", "label": "并发上限"},
            {"key": "enabled", "label": "启用"},
            {"key": "username_configured", "label": "账号"},
            {"key": "password_configured", "label": "密码"},
        ],
    ),
    _egress_action(
        "providers",
        "查看可用数据源",
        "/api/data-center/providers/",
        [],
        method="GET",
        description="查看可用于出网规则的数据源和当前连接方式。",
        task_group="01 出口清单",
        sequence=11,
        task_tier="support",
        columns=[
            {"key": "id", "label": "编号"},
            {"key": "name", "label": "数据源"},
            {"key": "source_type", "label": "类型"},
            {"key": "tushare_request_mode_label", "label": "连接方式"},
            {"key": "is_active", "label": "启用"},
            {"key": "http_url", "label": "服务地址"},
        ],
    ),
    _egress_action(
        "endpoint-create",
        "登记数据出口",
        "endpoints/",
        _endpoint_fields(create=True),
        description="登记境内出口连接；完成出口与匹配规则测试后再启用。",
        task_group="01 出口管理",
        sequence=20,
    ),
    _egress_action(
        "endpoint-update",
        "修改数据出口",
        "endpoints/{endpoint_id}/",
        _endpoint_fields(create=False),
        method="PATCH",
        description="更新出口设置或停用出口；密码留空保留。",
        task_group="01 出口管理",
        sequence=21,
    ),
    _egress_action(
        "endpoint-test",
        "测试数据出口",
        "endpoints/{endpoint_id}/test/",
        [_number("endpoint_id", "出口编号", required=True, path=True), *_context_fields()],
        description="通过已配置出口和匹配规则验证实际目标连接，查看失败原因。",
        task_group="03 连接验证",
        sequence=30,
    ),
    _egress_action(
        "rules",
        "查看出网规则",
        "rules/",
        [],
        method="GET",
        description="查看数据源、域名和执行区域对应的出网策略。",
        task_group="02 路由规则",
        sequence=40,
        task_tier="support",
        columns=[
            {"key": "id", "label": "编号"},
            {"key": "provider_id", "label": "数据源编号"},
            {"key": "provider_name", "label": "数据源"},
            {"key": "dataset_key", "label": "数据集"},
            {"key": "domain_pattern", "label": "目标域名"},
            {"key": "deployment_region", "label": "执行区域"},
            {"key": "strategy_label", "label": "策略"},
            {"key": "fixed_egress_id", "label": "出口编号"},
            {"key": "egress_name", "label": "固定出口"},
            {"key": "enabled", "label": "启用"},
            {"key": "priority", "label": "优先级"},
        ],
    ),
    _egress_action(
        "rule-create",
        "新增出网规则",
        "rules/",
        _rule_fields(create=True),
        description="为指定数据源和域名选择直连或境内出口。",
        task_group="02 路由规则",
        sequence=50,
    ),
    _egress_action(
        "rule-update",
        "修改出网规则",
        "rules/{rule_id}/",
        _rule_fields(create=False),
        method="PATCH",
        description="更新或停用规则，停用后恢复其他规则或默认路径。",
        task_group="02 路由规则",
        sequence=51,
    ),
    _egress_action(
        "preview",
        "预览出网选择",
        "rules/preview/",
        _context_fields(),
        description="解释当前请求会使用哪个出口；不发起外部请求。",
        task_group="03 连接验证",
        sequence=60,
        task_tier="operation",
    ),
    _egress_action(
        "diagnostics",
        "诊断数据连接",
        "diagnostics/",
        _context_fields(),
        description="对允许的目标执行有限连接诊断，查看尝试顺序和错误。",
        task_group="03 连接验证",
        sequence=61,
    ),
)
