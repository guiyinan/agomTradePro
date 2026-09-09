"""Staff tasks for registering data exits and explaining routing decisions."""

from typing import Any

from .tui_metadata_runtime_injection_data_center import _action, _field


def _number(key: str, label: str, *, required: bool = False, path: bool = False) -> dict[str, Any]:
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
            _number("port", "代理端口", required=create),
            _field("username", "代理账号"),
            _field(
                "password",
                "代理密码（留空保留）",
                input_type="password",
                presentation_semantic="api_token",
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


def _egress_action(
    key: str,
    label: str,
    endpoint: str,
    fields: list[dict[str, Any]],
    *,
    method: str = "POST",
    columns: list[dict[str, str]] | None = None,
    description: str,
) -> dict[str, Any]:
    """Reuse the Data Center staff audience, audit and presentation contract."""
    action = _action(
        key="data-center.egress-" + key,
        label=label,
        endpoint="/api/data-center/egress/" + endpoint,
        intent="data_center_egress_" + key.replace("-", "_"),
        method=method,
        effect="read" if method == "GET" or key == "preview" else "update",
        view_type="datagrid" if columns else "detail",
        description=description,
        task_group="06 数据出网",
        sequence=600,
        fields=fields,
        confirmation_required=method != "GET" and key != "preview",
        audit_required=method != "GET" and key != "preview",
        view_model=(
            {"kind": "datagrid", "rows_path": "results", "columns": columns}
            if columns
            else {
                "kind": "detail",
                "field_presentations": {"checked_at": "metadata", "attempts": "multiline"},
            }
        ),
    )
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
        columns=[
            {"key": "id", "label": "编号"},
            {"key": "name", "label": "出口"},
            {"key": "region", "label": "区域"},
            {"key": "enabled", "label": "启用"},
            {"key": "host", "label": "代理主机"},
            {"key": "port", "label": "端口"},
        ],
    ),
    _egress_action(
        "endpoint-create",
        "登记数据出口",
        "endpoints/",
        _endpoint_fields(create=True),
        description="登记境内出口连接；完成测试后再启用。",
    ),
    _egress_action(
        "endpoint-update",
        "修改数据出口",
        "endpoints/{endpoint_id}/",
        _endpoint_fields(create=False),
        method="PATCH",
        description="更新出口设置或停用出口；密码留空保留。",
    ),
    _egress_action(
        "endpoint-test",
        "测试数据出口",
        "endpoints/{endpoint_id}/test/",
        [_number("endpoint_id", "出口编号", required=True, path=True), *_context_fields()],
        description="通过已配置出口验证实际目标连接，查看失败原因。",
    ),
    _egress_action(
        "rules",
        "查看出网规则",
        "rules/",
        [],
        method="GET",
        description="查看数据源、域名和执行区域对应的出网策略。",
        columns=[
            {"key": "id", "label": "编号"},
            {"key": "provider_id", "label": "数据源编号"},
            {"key": "domain_pattern", "label": "目标域名"},
            {"key": "strategy_label", "label": "策略"},
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
    ),
    _egress_action(
        "rule-update",
        "修改出网规则",
        "rules/{rule_id}/",
        _rule_fields(create=False),
        method="PATCH",
        description="更新或停用规则，停用后恢复其他规则或默认路径。",
    ),
    _egress_action(
        "preview",
        "预览出网选择",
        "rules/preview/",
        _context_fields(),
        description="解释当前请求会使用哪个出口；不发起外部请求。",
    ),
    _egress_action(
        "diagnostics",
        "诊断数据连接",
        "diagnostics/",
        _context_fields(),
        description="对允许的目标执行有限连接诊断，查看尝试顺序和错误。",
    ),
)
