"""Curated runtime TUI metadata for Policy events and workbench review."""

from __future__ import annotations

from typing import Any

_SCREEN = "policy.workbench"
_MODULE = "daily-decisions"
_SOURCE = "approved:runtime-policy-workbench"


def _field(
    key: str,
    label: str,
    *,
    binding: str = "query",
    input_type: str = "text",
    value_type: str = "string",
    required: bool = False,
    options: list[str] | None = None,
) -> dict[str, Any]:
    """Build one typed Policy field."""

    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "binding": binding,
        "input_type": input_type,
        "value_type": value_type,
        "required": required,
    }
    if options is not None:
        field["options"] = options
    return field


def _action(
    *,
    key: str,
    label: str,
    endpoint: str,
    method: str,
    intent: str,
    description: str,
    sequence: int,
    fields: list[dict[str, Any]],
    view_type: str,
    view_model: dict[str, Any],
    effect: str | None = None,
    admin: bool = False,
    task_group: str = "03 政策事件与审核",
) -> dict[str, Any]:
    """Build one Policy task with explicit role and confirmation metadata."""

    action: dict[str, Any] = {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": "admin" if admin else ("read" if method == "GET" else "write"),
        "audience": "admin" if admin else "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": task_group,
        "sequence": sequence,
        "task_tier": "support",
        "fields": fields,
        "view_model": view_model,
    }
    if effect is not None:
        action["effect"] = effect
        action["confirmation_required"] = True
    return action


_LEVEL_OPTIONS = ["P0", "P1", "P2", "P3"]
_EVENT_DATE_PATH = _field(
    "event_date",
    "事件日期",
    binding="path",
    input_type="date",
    required=True,
)
_EVENT_BODY_FIELDS = [
    _field(
        "event_date",
        "事件日期",
        binding="body",
        input_type="date",
        required=True,
    ),
    _field(
        "level",
        "政策档位",
        binding="body",
        input_type="select",
        required=True,
        options=_LEVEL_OPTIONS,
    ),
    _field("title", "事件标题", binding="body", required=True),
    _field(
        "description",
        "事件说明",
        binding="body",
        input_type="textarea",
        required=True,
    ),
    _field("evidence_url", "证据链接", binding="body", required=True),
]
_EVENT_COLUMNS = [
    {"key": "event_date", "label": "事件日期"},
    {"key": "level", "label": "政策档位"},
    {"key": "title", "label": "标题"},
    {"key": "description", "label": "说明"},
    {"key": "evidence_url", "label": "证据链接"},
]

RUNTIME_POLICY_EVENT_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key="policy.event-list",
        label="查询政策事件",
        endpoint="/api/policy/events/",
        method="GET",
        intent="list_policy_events",
        description="按日期范围和政策档位查询已记录事件。",
        sequence=300,
        fields=[
            _field(
                "start_date",
                "开始日期",
                input_type="date",
                required=True,
            ),
            _field(
                "end_date",
                "结束日期",
                input_type="date",
                required=True,
            ),
            _field(
                "level",
                "政策档位",
                input_type="select",
                options=["", *_LEVEL_OPTIONS],
            ),
        ],
        view_type="datagrid",
        view_model={
            "kind": "datagrid",
            "rows_path": "events",
            "columns": _EVENT_COLUMNS,
        },
    ),
    _action(
        key="policy.event-detail",
        label="查看政策事件详情",
        endpoint="/api/policy/events/<event_date>/",
        method="GET",
        intent="read_policy_event",
        description="按事件日期查看政策档位、说明与证据链接。",
        sequence=310,
        fields=[_EVENT_DATE_PATH],
        view_type="detail",
        view_model={
            "kind": "detail",
            "title_path": "title",
            "status_path": "level",
        },
    ),
    _action(
        key="policy.event-create",
        label="创建政策事件",
        endpoint="/api/policy/events/",
        method="POST",
        intent="create_policy_event",
        description="由管理员创建带证据链接的政策档位事件。",
        sequence=320,
        fields=_EVENT_BODY_FIELDS,
        view_type="detail",
        view_model={"kind": "detail", "status_path": "success"},
        effect="create",
        admin=True,
    ),
    _action(
        key="policy.workbench-bootstrap",
        label="读取政策工作台上下文",
        endpoint="/api/policy/workbench/bootstrap/",
        method="GET",
        intent="read_policy_workbench_bootstrap",
        description="一次读取政策摘要、默认队列、筛选项、趋势和抓取状态。",
        sequence=330,
        fields=[],
        view_type="detail",
        view_model={"kind": "detail", "status_path": "success"},
    ),
    _action(
        key="policy.workbench-item-detail",
        label="查看待审政策详情",
        endpoint="/api/policy/workbench/items/<event_id>/",
        method="GET",
        intent="read_policy_workbench_item",
        description="查看事件来源、AI 分析、闸门状态、审核记录和资产范围。",
        sequence=340,
        fields=[
            _field(
                "event_id",
                "事件 ID",
                binding="path",
                input_type="number",
                value_type="integer",
                required=True,
            )
        ],
        view_type="detail",
        view_model={
            "kind": "detail",
            "title_path": "item.title",
            "status_path": "item.audit_status",
        },
    ),
    *[
        _action(
            key=f"policy.workbench-{operation}",
            label=label,
            endpoint=f"/api/policy/workbench/items/<event_id>/{operation}/",
            method="POST",
            intent=f"{operation}_policy_workbench_event",
            description=description,
            sequence=sequence,
            fields=[
                _field(
                    "event_id",
                    "事件 ID",
                    binding="path",
                    input_type="number",
                    value_type="integer",
                    required=True,
                ),
                _field(
                    "reason",
                    "审核理由",
                    binding="body",
                    input_type="textarea",
                    required=operation != "approve",
                ),
                *(
                    [
                        _field(
                            "new_level",
                            "临时档位",
                            binding="body",
                            input_type="select",
                            options=["", *_LEVEL_OPTIONS],
                        )
                    ]
                    if operation == "override"
                    else []
                ),
            ],
            view_type="detail",
            view_model={"kind": "detail", "status_path": "success"},
            effect="update",
        )
        for operation, label, description, sequence in (
            (
                "approve",
                "批准政策事件",
                "批准待审事件并记录审核人和理由。",
                350,
            ),
            (
                "reject",
                "拒绝政策事件",
                "拒绝待审事件并要求填写理由。",
                360,
            ),
            (
                "rollback",
                "回滚政策事件",
                "回滚已生效事件并记录回滚理由。",
                370,
            ),
            (
                "override",
                "临时豁免政策事件",
                "带理由临时豁免事件，并可调整政策档位。",
                380,
            ),
        )
    ],
)


def _source_fields(*, required: bool) -> list[dict[str, Any]]:
    """Return RSS source fields with create/update requiredness."""

    return [
        _field("name", "来源名称", binding="body", required=required),
        _field("url", "RSS 地址", binding="body", required=required),
        _field(
            "category",
            "来源类别",
            binding="body",
            input_type="select",
            required=required,
            options=["gov_docs", "central_bank", "mof", "csrc", "media", "other"],
        ),
        _field(
            "is_active",
            "启用",
            binding="body",
            input_type="checkbox",
            value_type="boolean",
            required=required,
        ),
        _field(
            "fetch_interval_hours",
            "抓取间隔（小时）",
            binding="body",
            input_type="number",
            value_type="integer",
            required=required,
        ),
        _field(
            "extract_content",
            "提取正文",
            binding="body",
            input_type="checkbox",
            value_type="boolean",
        ),
        _field(
            "parser_type",
            "解析器",
            binding="body",
            input_type="select",
            options=["feedparser", "httpx"],
        ),
        _field(
            "timeout_seconds",
            "超时秒数",
            binding="body",
            input_type="number",
            value_type="integer",
        ),
        _field(
            "retry_times",
            "重试次数",
            binding="body",
            input_type="number",
            value_type="integer",
        ),
        _field(
            "proxy_enabled",
            "启用代理",
            binding="body",
            input_type="checkbox",
            value_type="boolean",
        ),
        _field("proxy_host", "代理主机", binding="body"),
        _field(
            "proxy_port",
            "代理端口",
            binding="body",
            input_type="number",
            value_type="integer",
        ),
        _field("proxy_username", "代理用户名", binding="body"),
        _field(
            "proxy_password",
            "代理密码",
            binding="body",
            input_type="password",
        ),
        _field(
            "proxy_type",
            "代理类型",
            binding="body",
            input_type="select",
            options=["http", "https", "socks5"],
        ),
        _field(
            "rsshub_enabled",
            "启用 RSSHub",
            binding="body",
            input_type="checkbox",
            value_type="boolean",
        ),
        _field("rsshub_route_path", "RSSHub 路由", binding="body"),
        _field(
            "rsshub_use_global_config",
            "使用全局 RSSHub 配置",
            binding="body",
            input_type="checkbox",
            value_type="boolean",
        ),
        _field("rsshub_custom_base_url", "自定义 RSSHub 地址", binding="body"),
        _field(
            "rsshub_custom_access_key",
            "RSSHub Access Key",
            binding="body",
            input_type="password",
        ),
        _field(
            "rsshub_format",
            "RSSHub 格式",
            binding="body",
            input_type="select",
            options=["", "rss", "atom", "json"],
        ),
    ]


_RSS_SOURCE_ID = _field(
    "source_id",
    "RSS 源 ID",
    binding="path",
    input_type="number",
    value_type="integer",
    required=True,
)
_KEYWORD_ID = _field(
    "keyword_id",
    "关键词规则 ID",
    binding="path",
    input_type="number",
    value_type="integer",
    required=True,
)
_RSS_SOURCE_COLUMNS = [
    {"key": "id", "label": "ID"},
    {"key": "name", "label": "名称"},
    {"key": "category_display", "label": "类别"},
    {"key": "is_active", "label": "启用"},
    {"key": "parser_type_display", "label": "解析器"},
    {"key": "last_fetch_at", "label": "最近抓取"},
    {"key": "last_fetch_status", "label": "抓取状态"},
    {"key": "last_error_message", "label": "最近错误"},
]

RUNTIME_POLICY_RSS_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key="policy.rss-reader",
        label="阅读 RSS 政策条目",
        endpoint="/api/policy/rss/reader/",
        method="GET",
        intent="read_policy_rss_items",
        description="按来源、档位和信息类别阅读已标准化的 RSS 政策条目。",
        sequence=500,
        fields=[
            _field(
                "source_id",
                "RSS 源 ID",
                input_type="number",
                value_type="integer",
            ),
            _field(
                "level",
                "政策档位",
                input_type="select",
                options=["", "PX", *_LEVEL_OPTIONS],
            ),
            _field(
                "category",
                "信息类别",
                input_type="select",
                options=["", "macro", "sector", "individual", "sentiment", "other"],
            ),
            _field("limit", "每页数量", input_type="number", value_type="integer"),
            _field("offset", "偏移量", input_type="number", value_type="integer"),
        ],
        view_type="datagrid",
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "columns": [
                {"key": "event_date", "label": "日期"},
                {"key": "level", "label": "档位"},
                {"key": "title", "label": "标题"},
                {"key": "info_category", "label": "类别"},
                {"key": "rss_source_name", "label": "来源"},
                {"key": "audit_status", "label": "审核状态"},
                {"key": "risk_impact", "label": "风险影响"},
                {"key": "evidence_url", "label": "证据链接"},
            ],
        },
        task_group="04 RSS 阅读与治理",
    ),
    _action(
        key="policy.rss-source-list",
        label="管理 RSS 源",
        endpoint="/api/policy/rss/sources/",
        method="GET",
        intent="list_policy_rss_sources",
        description="筛选政策 RSS 源及其最近抓取状态。",
        sequence=510,
        fields=[
            _field(
                "category",
                "来源类别",
                input_type="select",
                options=["", "gov_docs", "central_bank", "mof", "csrc", "media", "other"],
            ),
            _field(
                "is_active",
                "启用状态",
                input_type="select",
                value_type="boolean",
                options=["", "true", "false"],
            ),
            _field("parser_type", "解析器"),
            _field("search", "搜索"),
        ],
        view_type="datagrid",
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "columns": _RSS_SOURCE_COLUMNS,
        },
        admin=True,
        task_group="04 RSS 阅读与治理",
    ),
    _action(
        key="policy.rss-source-detail",
        label="查看 RSS 源详情",
        endpoint="/api/policy/rss/sources/<source_id>/",
        method="GET",
        intent="read_policy_rss_source",
        description="查看一个 RSS 源的解析、代理和 RSSHub 配置。",
        sequence=520,
        fields=[_RSS_SOURCE_ID],
        view_type="detail",
        view_model={"kind": "detail", "title_path": "name", "status_path": "last_fetch_status"},
        admin=True,
        task_group="04 RSS 阅读与治理",
    ),
    _action(
        key="policy.rss-source-create",
        label="创建 RSS 源",
        endpoint="/api/policy/rss/sources/",
        method="POST",
        intent="create_policy_rss_source",
        description="创建一个政策 RSS 数据源配置。",
        sequence=530,
        fields=_source_fields(required=True),
        view_type="detail",
        view_model={"kind": "detail", "title_path": "name"},
        effect="create",
        admin=True,
        task_group="04 RSS 阅读与治理",
    ),
    _action(
        key="policy.rss-source-update",
        label="更新 RSS 源",
        endpoint="/api/policy/rss/sources/<source_id>/",
        method="PATCH",
        intent="update_policy_rss_source",
        description="部分更新 RSS 源、代理或 RSSHub 配置。",
        sequence=540,
        fields=[_RSS_SOURCE_ID, *_source_fields(required=False)],
        view_type="detail",
        view_model={"kind": "detail", "title_path": "name"},
        effect="update",
        admin=True,
        task_group="04 RSS 阅读与治理",
    ),
    _action(
        key="policy.rss-source-delete",
        label="删除 RSS 源",
        endpoint="/api/policy/rss/sources/<source_id>/",
        method="DELETE",
        intent="delete_policy_rss_source",
        description="删除一个 RSS 源配置。",
        sequence=550,
        fields=[_RSS_SOURCE_ID],
        view_type="detail",
        view_model={"kind": "detail"},
        effect="delete",
        admin=True,
        task_group="04 RSS 阅读与治理",
    ),
    _action(
        key="policy.rss-source-fetch",
        label="抓取指定 RSS 源",
        endpoint="/api/policy/rss/sources/<source_id>/trigger_fetch/",
        method="POST",
        intent="fetch_policy_rss_source",
        description="触发指定 RSS 源抓取并返回任务跟踪信息。",
        sequence=560,
        fields=[_RSS_SOURCE_ID],
        view_type="detail",
        view_model={"kind": "detail", "status_path": "status"},
        effect="execute",
        admin=True,
        task_group="04 RSS 阅读与治理",
    ),
    _action(
        key="policy.rss-fetch-all",
        label="抓取全部 RSS 源",
        endpoint="/api/policy/rss/sources/fetch_all/",
        method="POST",
        intent="fetch_all_policy_rss_sources",
        description="触发全部启用 RSS 源抓取。",
        sequence=570,
        fields=[
            _field(
                "force_refetch",
                "强制重新抓取",
                binding="body",
                input_type="checkbox",
                value_type="boolean",
            )
        ],
        view_type="detail",
        view_model={"kind": "detail", "status_path": "status"},
        effect="execute",
        admin=True,
        task_group="04 RSS 阅读与治理",
    ),
    _action(
        key="policy.rss-log-list",
        label="查看 RSS 抓取日志",
        endpoint="/api/policy/rss/logs/",
        method="GET",
        intent="list_policy_rss_fetch_logs",
        description="按来源和状态查看 RSS 抓取结果与错误。",
        sequence=580,
        fields=[
            _field("source", "RSS 源 ID", input_type="number", value_type="integer"),
            _field(
                "status",
                "抓取状态",
                input_type="select",
                options=["", "success", "error", "partial"],
            ),
            _field("source__name", "来源名称"),
        ],
        view_type="datagrid",
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "source_name", "label": "来源"},
                {"key": "fetched_at", "label": "抓取时间"},
                {"key": "status_display", "label": "状态"},
                {"key": "items_count", "label": "条目数"},
                {"key": "new_items_count", "label": "新增数"},
                {"key": "fetch_duration_seconds", "label": "耗时秒"},
                {"key": "error_message", "label": "错误"},
            ],
        },
        admin=True,
        task_group="04 RSS 阅读与治理",
    ),
    _action(
        key="policy.rss-log-detail",
        label="查看 RSS 抓取日志详情",
        endpoint="/api/policy/rss/logs/<log_id>/",
        method="GET",
        intent="read_policy_rss_fetch_log",
        description="查看一次 RSS 抓取的结果和错误详情。",
        sequence=590,
        fields=[
            _field(
                "log_id",
                "日志 ID",
                binding="path",
                input_type="number",
                value_type="integer",
                required=True,
            )
        ],
        view_type="detail",
        view_model={"kind": "detail", "status_path": "status"},
        admin=True,
        task_group="04 RSS 阅读与治理",
    ),
    _action(
        key="policy.rss-keyword-list",
        label="管理政策关键词规则",
        endpoint="/api/policy/rss/keywords/",
        method="GET",
        intent="list_policy_rss_keywords",
        description="按档位、类别和启用状态查看关键词规则。",
        sequence=600,
        fields=[
            _field(
                "level",
                "政策档位",
                input_type="select",
                options=["", "PX", *_LEVEL_OPTIONS],
            ),
            _field(
                "is_active",
                "启用状态",
                input_type="select",
                value_type="boolean",
                options=["", "true", "false"],
            ),
            _field("category", "类别"),
        ],
        view_type="datagrid",
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "level", "label": "档位"},
                {"key": "keywords", "label": "关键词"},
                {"key": "weight", "label": "权重"},
                {"key": "category", "label": "类别"},
                {"key": "is_active", "label": "启用"},
                {"key": "updated_at", "label": "更新时间"},
            ],
        },
        admin=True,
        task_group="04 RSS 阅读与治理",
    ),
    *[
        _action(
            key=f"policy.rss-keyword-{operation}",
            label=label,
            endpoint=endpoint,
            method=method,
            intent=f"{operation}_policy_rss_keyword",
            description=description,
            sequence=sequence,
            fields=fields,
            view_type="detail",
            view_model={"kind": "detail"},
            effect=effect,
            admin=True,
            task_group="04 RSS 阅读与治理",
        )
        for operation, label, endpoint, method, description, sequence, fields, effect in (
            (
                "detail",
                "查看政策关键词详情",
                "/api/policy/rss/keywords/<keyword_id>/",
                "GET",
                "查看一个政策关键词规则。",
                610,
                [_KEYWORD_ID],
                None,
            ),
            (
                "create",
                "创建政策关键词规则",
                "/api/policy/rss/keywords/",
                "POST",
                "创建带档位、权重和类别的关键词规则。",
                620,
                [
                    _field(
                        "level",
                        "政策档位",
                        binding="body",
                        input_type="select",
                        required=True,
                        options=["PX", *_LEVEL_OPTIONS],
                    ),
                    _field(
                        "keywords",
                        "关键词（JSON 数组）",
                        binding="body",
                        input_type="textarea",
                        value_type="list",
                        required=True,
                    ),
                    _field(
                        "weight",
                        "权重",
                        binding="body",
                        input_type="number",
                        value_type="integer",
                        required=True,
                    ),
                    _field("category", "类别", binding="body"),
                    _field(
                        "is_active",
                        "启用",
                        binding="body",
                        input_type="checkbox",
                        value_type="boolean",
                    ),
                ],
                "create",
            ),
            (
                "update",
                "更新政策关键词规则",
                "/api/policy/rss/keywords/<keyword_id>/",
                "PATCH",
                "部分更新政策关键词规则。",
                630,
                [
                    _KEYWORD_ID,
                    _field(
                        "level",
                        "政策档位",
                        binding="body",
                        input_type="select",
                        options=["PX", *_LEVEL_OPTIONS],
                    ),
                    _field(
                        "keywords",
                        "关键词（JSON 数组）",
                        binding="body",
                        input_type="textarea",
                        value_type="list",
                    ),
                    _field(
                        "weight",
                        "权重",
                        binding="body",
                        input_type="number",
                        value_type="integer",
                    ),
                    _field("category", "类别", binding="body"),
                    _field(
                        "is_active",
                        "启用",
                        binding="body",
                        input_type="checkbox",
                        value_type="boolean",
                    ),
                ],
                "update",
            ),
            (
                "delete",
                "删除政策关键词规则",
                "/api/policy/rss/keywords/<keyword_id>/",
                "DELETE",
                "删除一个政策关键词规则。",
                640,
                [_KEYWORD_ID],
                "delete",
            ),
        )
    ],
)
