"""Runtime TUI metadata for the owner-scoped strategy workbench."""

from __future__ import annotations

from typing import Any

from apps.strategy.domain.entities import ActionType, ApprovalMode, StrategyType

_SCREEN = "macro-regime.strategy"
_MODULE = "macro-regime"
_SOURCE = "approved:runtime-strategy-workbench"
_STRATEGIES = "/api/strategy/strategies/"


def _path_id(key: str, label: str) -> dict[str, Any]:
    """Build one positive integer path field."""

    return {
        "key": key,
        "label": label,
        "binding": "path",
        "input_type": "number",
        "value_type": "integer",
        "required": True,
        "min": 1,
    }


def _body_id(key: str, label: str) -> dict[str, Any]:
    """Build one positive integer body field."""

    return {
        "key": key,
        "label": label,
        "binding": "body",
        "input_type": "number",
        "value_type": "integer",
        "required": True,
        "min": 1,
    }


def _hidden(key: str, value: str) -> dict[str, Any]:
    """Build a fixed body value for a typed adapter."""

    return {
        "key": key,
        "label": key,
        "binding": "body",
        "input_type": "hidden",
        "value_type": "string",
        "required": True,
        "default": value,
    }


def _strategy_fields(*, required: bool) -> list[dict[str, Any]]:
    """Build scalar create/update fields for one strategy."""

    fields: list[dict[str, Any]] = [
        {
            "key": "name",
            "label": "策略名称",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": required,
            "max": 200,
        },
        {
            "key": "description",
            "label": "策略说明",
            "binding": "body",
            "input_type": "textarea",
            "value_type": "string",
            "required": False,
        },
    ]
    if required:
        fields.append(
            {
                "key": "strategy_type",
                "label": "策略类型",
                "binding": "body",
                "input_type": "select",
                "value_type": "string",
                "required": True,
                "options": [item.value for item in StrategyType],
            }
        )
    max_position_field = {
        "key": "max_position_pct",
        "label": "单资产最大仓位（%）",
        "binding": "body",
        "input_type": "number",
        "value_type": "float",
        "required": False,
        "min": 0,
        "max": 100,
    }
    max_total_field = {
        "key": "max_total_position_pct",
        "label": "总仓位上限（%）",
        "binding": "body",
        "input_type": "number",
        "value_type": "float",
        "required": False,
        "min": 0,
        "max": 100,
    }
    if required:
        max_position_field["default"] = 20
        max_total_field["default"] = 95
    fields.extend(
        [
            max_position_field,
            max_total_field,
            {
                "key": "stop_loss_pct",
                "label": "止损比例（%）",
                "binding": "body",
                "input_type": "number",
                "value_type": "float",
                "required": False,
                "min": 0,
                "max": 100,
            },
        ]
    )
    return fields


def _rule_base_fields(rule_type: str) -> list[dict[str, Any]]:
    """Build the common body of one flat condition-rule mutation."""

    return [
        _body_id("strategy", "策略 ID"),
        _hidden("rule_type", rule_type),
        {
            "key": "rule_name",
            "label": "规则名称",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": True,
            "max": 200,
        },
        {
            "key": "action",
            "label": "触发动作",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": True,
            "options": [item.value for item in ActionType],
        },
        {
            "key": "weight",
            "label": "目标权重",
            "binding": "body",
            "input_type": "number",
            "value_type": "float",
            "required": False,
            "min": 0,
            "max": 1,
        },
        {
            "key": "target_assets",
            "label": "目标资产代码",
            "binding": "body",
            "input_type": "text",
            "value_type": "list",
            "required": False,
        },
        {
            "key": "priority",
            "label": "优先级",
            "binding": "body",
            "input_type": "number",
            "value_type": "integer",
            "required": False,
            "default": 10,
            "min": 0,
            "max": 100,
        },
        {
            "key": "is_enabled",
            "label": "启用规则",
            "binding": "body",
            "input_type": "checkbox",
            "value_type": "boolean",
            "required": False,
            "default": True,
        },
    ]


def _macro_rule_fields() -> list[dict[str, Any]]:
    """Build a macro rule without exposing condition JSON."""

    return [
        *_rule_base_fields("macro"),
        {
            "key": "indicator",
            "label": "宏观指标代码",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": True,
            "max": 100,
        },
        {
            "key": "operator",
            "label": "判断方式",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": True,
            "options": [">", ">=", "<", "<=", "==", "!=", "between", "trend"],
        },
        {
            "key": "threshold",
            "label": "比较阈值",
            "binding": "body",
            "input_type": "number",
            "value_type": "float",
            "required": False,
        },
        {
            "key": "min_value",
            "label": "区间最小值",
            "binding": "body",
            "input_type": "number",
            "value_type": "float",
            "required": False,
        },
        {
            "key": "max_value",
            "label": "区间最大值",
            "binding": "body",
            "input_type": "number",
            "value_type": "float",
            "required": False,
        },
        {
            "key": "direction",
            "label": "趋势方向",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": False,
            "options": ["up", "down"],
        },
        {
            "key": "periods",
            "label": "连续周期",
            "binding": "body",
            "input_type": "number",
            "value_type": "integer",
            "required": False,
            "min": 2,
            "max": 24,
        },
    ]


def _regime_rule_fields() -> list[dict[str, Any]]:
    """Build a Regime rule without exposing condition JSON."""

    regimes = ["Recovery", "Overheat", "Stagflation", "Deflation"]
    return [
        *_rule_base_fields("regime"),
        {
            "key": "operator",
            "label": "判断方式",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": True,
            "options": ["==", "in", "transitions"],
        },
        {
            "key": "regime_value",
            "label": "目标状态",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": False,
            "options": regimes,
        },
        {
            "key": "regime_values",
            "label": "允许状态集合",
            "binding": "body",
            "input_type": "text",
            "value_type": "list",
            "required": False,
        },
        {
            "key": "from_regime",
            "label": "转换前状态",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": False,
            "options": regimes,
        },
        {
            "key": "to_regime",
            "label": "转换后状态",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": False,
            "options": regimes,
        },
    ]


def _signal_rule_fields() -> list[dict[str, Any]]:
    """Build a signal rule without exposing condition JSON."""

    return [
        *_rule_base_fields("signal"),
        {
            "key": "operator",
            "label": "判断方式",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": True,
            "options": ["exists", "score"],
        },
        {
            "key": "asset_code",
            "label": "资产代码",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": True,
            "max": 64,
        },
        {
            "key": "min_score",
            "label": "最低评分",
            "binding": "body",
            "input_type": "number",
            "value_type": "float",
            "required": False,
        },
    ]


def _composite_rule_fields() -> list[dict[str, Any]]:
    """Build a bounded two-condition composite rule."""

    fields = [
        *_rule_base_fields("composite"),
        _hidden("operator", "=="),
        {
            "key": "composite_logic",
            "label": "两个条件的关系",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": True,
            "options": ["AND", "OR"],
        },
    ]
    for prefix, label in (("first", "条件一"), ("second", "条件二")):
        fields.extend(
            [
                {
                    "key": f"{prefix}_type",
                    "label": f"{label}类型",
                    "binding": "body",
                    "input_type": "select",
                    "value_type": "string",
                    "required": True,
                    "options": ["macro", "regime", "signal"],
                },
                {
                    "key": f"{prefix}_operator",
                    "label": f"{label}运算符",
                    "binding": "body",
                    "input_type": "select",
                    "value_type": "string",
                    "required": True,
                    "options": [">", ">=", "<", "<=", "==", "!=", "exists", "score"],
                },
                {
                    "key": f"{prefix}_key",
                    "label": f"{label}指标或资产",
                    "binding": "body",
                    "input_type": "text",
                    "value_type": "string",
                    "required": False,
                    "max": 100,
                },
                {
                    "key": f"{prefix}_value",
                    "label": f"{label}阈值或状态",
                    "binding": "body",
                    "input_type": "text",
                    "value_type": "string",
                    "required": False,
                    "max": 100,
                },
            ]
        )
    return fields


def _mutation(
    *,
    key: str,
    label: str,
    endpoint: str,
    method: str,
    effect: str,
    sequence: int,
    fields: list[dict[str, Any]],
    description: str,
) -> dict[str, Any]:
    """Build one confirmed owner-scoped strategy mutation."""

    return {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": key.replace(".", "_").replace("-", "_"),
        "risk": "write",
        "audience": "authenticated",
        "effect": effect,
        "confirmation_required": True,
        "audit_required": True,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": description,
        "source": _SOURCE,
        "task_group": "09 策略工作台",
        "sequence": sequence,
        "task_tier": "support",
        "fields": fields,
        "view_model": {"kind": "detail"},
    }


def _rule_mutation(
    *,
    key: str,
    label: str,
    fields: list[dict[str, Any]],
    sequence: int,
    update: bool = False,
) -> dict[str, Any]:
    """Build one typed create or full-replacement rule action."""

    endpoint = "/api/strategy/tui/rules/"
    method = "POST"
    effect = "create"
    action_fields = fields
    if update:
        endpoint = "/api/strategy/tui/rules/<int:rule_id>/"
        method = "PATCH"
        effect = "update"
        action_fields = [_path_id("rule_id", "规则 ID"), *fields]
    return _mutation(
        key=key,
        label=label,
        endpoint=endpoint,
        method=method,
        effect=effect,
        sequence=sequence,
        fields=action_fields,
        description="使用结构化字段维护条件规则，后端负责生成条件对象。",
    )


def _script_fields(*, required: bool) -> list[dict[str, Any]]:
    """Build script configuration fields without sandbox JSON."""

    return [
        _body_id("strategy", "策略 ID"),
        {
            "key": "script_language",
            "label": "脚本语言",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": required,
            "default": "python",
            "options": ["python"],
        },
        {
            "key": "script_code",
            "label": "受限 Python 脚本",
            "binding": "body",
            "input_type": "textarea",
            "value_type": "string",
            "required": required,
        },
        {
            "key": "allowed_modules",
            "label": "允许导入模块",
            "binding": "body",
            "input_type": "text",
            "value_type": "list",
            "required": False,
        },
        {
            "key": "version",
            "label": "配置版本",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": False,
            "default": "1.0",
            "max": 20,
        },
        {
            "key": "is_active",
            "label": "启用脚本",
            "binding": "body",
            "input_type": "checkbox",
            "value_type": "boolean",
            "required": False,
            "default": True,
        },
    ]


def _ai_fields(*, required: bool) -> list[dict[str, Any]]:
    """Build AI strategy configuration fields."""

    return [
        _body_id("strategy", "策略 ID"),
        *[
            {
                "key": key,
                "label": label,
                "binding": "body",
                "input_type": "number",
                "value_type": "integer",
                "required": False,
                "min": 1,
            }
            for key, label in (
                ("prompt_template", "Prompt 模板 ID"),
                ("chain_config", "执行链 ID"),
                ("ai_provider", "AI 服务商 ID"),
            )
        ],
        {
            "key": "temperature",
            "label": "温度",
            "binding": "body",
            "input_type": "number",
            "value_type": "float",
            "required": False,
            "default": 0.7,
            "min": 0,
            "max": 2,
        },
        {
            "key": "max_tokens",
            "label": "最大 Token",
            "binding": "body",
            "input_type": "number",
            "value_type": "integer",
            "required": False,
            "default": 2000,
            "min": 1,
        },
        {
            "key": "approval_mode",
            "label": "审批模式",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": required,
            "default": ApprovalMode.CONDITIONAL.value,
            "options": [item.value for item in ApprovalMode],
        },
        {
            "key": "confidence_threshold",
            "label": "自动执行置信度",
            "binding": "body",
            "input_type": "number",
            "value_type": "float",
            "required": False,
            "default": 0.8,
            "min": 0,
            "max": 1,
        },
    ]


def _position_fields(*, required: bool) -> list[dict[str, Any]]:
    """Build position-rule fields while leaving JSON defaults server-side."""

    fields: list[dict[str, Any]] = [
        _body_id("strategy", "策略 ID"),
        {
            "key": "name",
            "label": "仓位规则名称",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": required,
            "max": 200,
        },
        {
            "key": "description",
            "label": "规则说明",
            "binding": "body",
            "input_type": "textarea",
            "value_type": "string",
            "required": False,
        },
        {
            "key": "is_active",
            "label": "启用仓位规则",
            "binding": "body",
            "input_type": "checkbox",
            "value_type": "boolean",
            "required": False,
            "default": True,
        },
        {
            "key": "price_precision",
            "label": "价格精度",
            "binding": "body",
            "input_type": "number",
            "value_type": "integer",
            "required": False,
            "default": 2,
            "min": 0,
            "max": 8,
        },
    ]
    for key, label in (
        ("buy_condition_expr", "买入条件表达式"),
        ("sell_condition_expr", "卖出条件表达式"),
        ("buy_price_expr", "买入价表达式"),
        ("sell_price_expr", "卖出价表达式"),
        ("stop_loss_expr", "止损价表达式"),
        ("take_profit_expr", "止盈价表达式"),
        ("position_size_expr", "仓位计算表达式"),
    ):
        fields.append(
            {
                "key": key,
                "label": label,
                "binding": "body",
                "input_type": "textarea",
                "value_type": "string",
                "required": required and key not in {"buy_condition_expr", "sell_condition_expr"},
            }
        )
    return fields


RUNTIME_STRATEGY_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "strategy.workbench-list",
        "label": "查看策略清单",
        "endpoint": _STRATEGIES,
        "method": "GET",
        "intent": "list_owner_strategies",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "按类型、状态或关键词查看本人策略。管理员可查看全量。",
        "source": _SOURCE,
        "task_group": "09 策略工作台",
        "sequence": 900,
        "task_tier": "support",
        "fields": [
            {
                "key": "strategy_type",
                "label": "策略类型",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "options": [item.value for item in StrategyType],
            },
            {
                "key": "is_active",
                "label": "仅看启用状态",
                "binding": "query",
                "input_type": "checkbox",
                "value_type": "boolean",
                "required": False,
            },
            {
                "key": "search",
                "label": "搜索名称或说明",
                "binding": "query",
                "input_type": "text",
                "value_type": "string",
                "required": False,
            },
        ],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "results",
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "name", "label": "策略"},
                {"key": "strategy_type", "label": "类型"},
                {"key": "version", "label": "版本"},
                {"key": "is_active", "label": "已启用"},
                {"key": "max_position_pct", "label": "单资产上限"},
                {"key": "max_total_position_pct", "label": "总仓位上限"},
                {"key": "updated_at", "label": "更新时间"},
            ],
        },
    },
    {
        "key": "strategy.workbench-detail",
        "label": "查看策略详情",
        "endpoint": f"{_STRATEGIES}<int:strategy_id>/",
        "method": "GET",
        "intent": "read_owner_strategy",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "查看风险参数、规则数量和脚本/AI 配置状态。",
        "source": _SOURCE,
        "task_group": "09 策略工作台",
        "sequence": 910,
        "task_tier": "support",
        "fields": [_path_id("strategy_id", "策略 ID")],
        "view_model": {
            "kind": "detail",
            "title_path": "name",
            "status_path": "is_active",
        },
    },
    _mutation(
        key="strategy.workbench-create",
        label="新建策略",
        endpoint="/api/strategy/tui/strategies/",
        method="POST",
        effect="create",
        sequence=920,
        fields=_strategy_fields(required=True),
        description="创建一条默认停用的策略，再分别配置规则、脚本或 AI 参数。",
    ),
    _mutation(
        key="strategy.workbench-update",
        label="更新策略并升级版本",
        endpoint="/api/strategy/tui/strategies/<int:strategy_id>/",
        method="PATCH",
        effect="update",
        sequence=930,
        fields=[_path_id("strategy_id", "策略 ID"), *_strategy_fields(required=False)],
        description="更新标量风险参数并由服务端把版本号递增一次。",
    ),
    _mutation(
        key="strategy.workbench-activate",
        label="启用策略",
        endpoint=f"{_STRATEGIES}<int:strategy_id>/activate/",
        method="POST",
        effect="update",
        sequence=940,
        fields=[_path_id("strategy_id", "策略 ID")],
        description="在配置检查完成后启用策略。",
    ),
    _mutation(
        key="strategy.workbench-deactivate",
        label="停用策略",
        endpoint=f"{_STRATEGIES}<int:strategy_id>/deactivate/",
        method="POST",
        effect="update",
        sequence=950,
        fields=[_path_id("strategy_id", "策略 ID")],
        description="停止策略后续执行，不删除历史证据。",
    ),
    _mutation(
        key="strategy.workbench-delete",
        label="删除策略",
        endpoint=f"{_STRATEGIES}<int:strategy_id>/",
        method="DELETE",
        effect="delete",
        sequence=960,
        fields=[_path_id("strategy_id", "策略 ID")],
        description="永久删除本人策略及其级联配置。",
    ),
    {
        "key": "strategy.rule-list",
        "label": "查看条件规则",
        "endpoint": "/api/strategy/rules/",
        "method": "GET",
        "intent": "list_strategy_rules",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "按策略、规则类型和启用状态查看条件规则。",
        "source": _SOURCE,
        "task_group": "09 策略工作台",
        "sequence": 970,
        "task_tier": "support",
        "fields": [
            {
                **_body_id("strategy", "策略 ID"),
                "binding": "query",
            },
            {
                "key": "rule_type",
                "label": "规则类型",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "options": ["macro", "regime", "signal", "composite"],
            },
            {
                "key": "is_enabled",
                "label": "仅看启用状态",
                "binding": "query",
                "input_type": "checkbox",
                "value_type": "boolean",
                "required": False,
            },
        ],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "results",
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "rule_name", "label": "规则"},
                {"key": "rule_type", "label": "类型"},
                {"key": "action", "label": "动作"},
                {"key": "weight", "label": "权重"},
                {"key": "priority", "label": "优先级"},
                {"key": "is_enabled", "label": "已启用"},
            ],
        },
    },
    _rule_mutation(
        key="strategy.rule-create-macro",
        label="新建宏观规则",
        fields=_macro_rule_fields(),
        sequence=980,
    ),
    _rule_mutation(
        key="strategy.rule-update-macro",
        label="替换宏观规则",
        fields=_macro_rule_fields(),
        sequence=990,
        update=True,
    ),
    _rule_mutation(
        key="strategy.rule-create-regime",
        label="新建 Regime 规则",
        fields=_regime_rule_fields(),
        sequence=1000,
    ),
    _rule_mutation(
        key="strategy.rule-update-regime",
        label="替换 Regime 规则",
        fields=_regime_rule_fields(),
        sequence=1010,
        update=True,
    ),
    _rule_mutation(
        key="strategy.rule-create-signal",
        label="新建信号规则",
        fields=_signal_rule_fields(),
        sequence=1020,
    ),
    _rule_mutation(
        key="strategy.rule-update-signal",
        label="替换信号规则",
        fields=_signal_rule_fields(),
        sequence=1030,
        update=True,
    ),
    _rule_mutation(
        key="strategy.rule-create-composite",
        label="新建双条件组合规则",
        fields=_composite_rule_fields(),
        sequence=1040,
    ),
    _rule_mutation(
        key="strategy.rule-update-composite",
        label="替换双条件组合规则",
        fields=_composite_rule_fields(),
        sequence=1050,
        update=True,
    ),
    _mutation(
        key="strategy.rule-enable",
        label="启用条件规则",
        endpoint="/api/strategy/rules/<int:rule_id>/enable/",
        method="POST",
        effect="update",
        sequence=1060,
        fields=[_path_id("rule_id", "规则 ID")],
        description="启用一条本人可访问的条件规则。",
    ),
    _mutation(
        key="strategy.rule-disable",
        label="停用条件规则",
        endpoint="/api/strategy/rules/<int:rule_id>/disable/",
        method="POST",
        effect="update",
        sequence=1070,
        fields=[_path_id("rule_id", "规则 ID")],
        description="停用条件规则而不删除历史配置。",
    ),
    _mutation(
        key="strategy.rule-delete",
        label="删除条件规则",
        endpoint="/api/strategy/rules/<int:rule_id>/",
        method="DELETE",
        effect="delete",
        sequence=1080,
        fields=[_path_id("rule_id", "规则 ID")],
        description="永久删除一条条件规则。",
    ),
    {
        "key": "strategy.script-list",
        "label": "查看脚本配置",
        "endpoint": "/api/strategy/script-configs/",
        "method": "GET",
        "intent": "list_strategy_scripts",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "查看本人策略的脚本版本、哈希与启用状态。",
        "source": _SOURCE,
        "task_group": "09 策略工作台",
        "sequence": 1090,
        "task_tier": "support",
        "fields": [
            {
                **_body_id("strategy", "策略 ID"),
                "binding": "query",
            }
        ],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "results",
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "strategy", "label": "策略 ID"},
                {"key": "script_language", "label": "语言"},
                {"key": "version", "label": "版本"},
                {"key": "script_hash", "label": "脚本哈希"},
                {"key": "is_active", "label": "已启用"},
                {"key": "updated_at", "label": "更新时间"},
            ],
        },
    },
    _mutation(
        key="strategy.script-create",
        label="新建脚本配置",
        endpoint="/api/strategy/script-configs/",
        method="POST",
        effect="create",
        sequence=1100,
        fields=_script_fields(required=True),
        description="保存受限 Python 脚本；沙箱对象由服务端默认值管理。",
    ),
    _mutation(
        key="strategy.script-update",
        label="更新脚本配置",
        endpoint="/api/strategy/script-configs/<int:config_id>/",
        method="PATCH",
        effect="update",
        sequence=1110,
        fields=[_path_id("config_id", "脚本配置 ID"), *_script_fields(required=False)],
        description="更新脚本正文、允许模块、版本或启用状态。",
    ),
    _mutation(
        key="strategy.script-delete",
        label="删除脚本配置",
        endpoint="/api/strategy/script-configs/<int:config_id>/",
        method="DELETE",
        effect="delete",
        sequence=1120,
        fields=[_path_id("config_id", "脚本配置 ID")],
        description="删除一条脚本配置。",
    ),
    _mutation(
        key="strategy.script-test",
        label="沙箱测试脚本",
        endpoint="/api/strategy/test-script/",
        method="POST",
        effect="execute",
        sequence=1130,
        fields=[
            {
                "key": "script_code",
                "label": "受限 Python 脚本",
                "binding": "body",
                "input_type": "textarea",
                "value_type": "string",
                "required": True,
            }
        ],
        description="在受限环境中测试脚本并返回执行时间和信号。",
    ),
    {
        "key": "strategy.ai-config-list",
        "label": "查看 AI 策略配置",
        "endpoint": "/api/strategy/ai-configs/",
        "method": "GET",
        "intent": "list_ai_strategy_configs",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "查看审批模式、置信度阈值与模型参数。",
        "source": _SOURCE,
        "task_group": "09 策略工作台",
        "sequence": 1140,
        "task_tier": "support",
        "fields": [
            {
                **_body_id("strategy", "策略 ID"),
                "binding": "query",
            }
        ],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "results",
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "strategy", "label": "策略 ID"},
                {"key": "ai_provider", "label": "服务商"},
                {"key": "approval_mode", "label": "审批模式"},
                {"key": "confidence_threshold", "label": "置信度"},
                {"key": "temperature", "label": "温度"},
                {"key": "max_tokens", "label": "最大 Token"},
            ],
        },
    },
    _mutation(
        key="strategy.ai-config-create",
        label="新建 AI 策略配置",
        endpoint="/api/strategy/ai-configs/",
        method="POST",
        effect="create",
        sequence=1150,
        fields=_ai_fields(required=True),
        description="绑定 Prompt、执行链与服务商，并设置审批阈值。",
    ),
    _mutation(
        key="strategy.ai-config-update",
        label="更新 AI 策略配置",
        endpoint="/api/strategy/ai-configs/<int:config_id>/",
        method="PATCH",
        effect="update",
        sequence=1160,
        fields=[_path_id("config_id", "AI 配置 ID"), *_ai_fields(required=False)],
        description="局部更新模型参数和审批模式。",
    ),
    _mutation(
        key="strategy.ai-config-delete",
        label="删除 AI 策略配置",
        endpoint="/api/strategy/ai-configs/<int:config_id>/",
        method="DELETE",
        effect="delete",
        sequence=1170,
        fields=[_path_id("config_id", "AI 配置 ID")],
        description="删除一条 AI 策略配置。",
    ),
    {
        "key": "strategy.position-rule-list",
        "label": "查看仓位规则",
        "endpoint": "/api/strategy/position-rules/",
        "method": "GET",
        "intent": "list_position_rules",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "查看策略绑定的仓位与价格表达式配置。",
        "source": _SOURCE,
        "task_group": "09 策略工作台",
        "sequence": 1180,
        "task_tier": "support",
        "fields": [
            {
                **_body_id("strategy", "策略 ID"),
                "binding": "query",
            }
        ],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "results",
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "strategy", "label": "策略 ID"},
                {"key": "strategy_name", "label": "策略"},
                {"key": "name", "label": "规则"},
                {"key": "price_precision", "label": "价格精度"},
                {"key": "is_active", "label": "已启用"},
                {"key": "updated_at", "label": "更新时间"},
            ],
        },
    },
    _mutation(
        key="strategy.position-rule-create",
        label="新建仓位规则",
        endpoint="/api/strategy/position-rules/",
        method="POST",
        effect="create",
        sequence=1190,
        fields=_position_fields(required=True),
        description="以结构化表达式配置价格、止损止盈和仓位计算。",
    ),
    _mutation(
        key="strategy.position-rule-update",
        label="更新仓位规则",
        endpoint="/api/strategy/position-rules/<int:rule_id>/",
        method="PATCH",
        effect="update",
        sequence=1200,
        fields=[_path_id("rule_id", "仓位规则 ID"), *_position_fields(required=False)],
        description="局部更新仓位规则表达式和启用状态。",
    ),
    _mutation(
        key="strategy.position-rule-delete",
        label="删除仓位规则",
        endpoint="/api/strategy/position-rules/<int:rule_id>/",
        method="DELETE",
        effect="delete",
        sequence=1210,
        fields=[_path_id("rule_id", "仓位规则 ID")],
        description="删除一条仓位管理规则。",
    ),
    {
        "key": "strategy.execution-log-list",
        "label": "查看策略执行日志",
        "endpoint": f"{_STRATEGIES}<int:strategy_id>/execution_logs/",
        "method": "GET",
        "intent": "list_strategy_execution_logs",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "分页查看执行成败、耗时和信号数量。",
        "source": _SOURCE,
        "task_group": "09 策略工作台",
        "sequence": 1220,
        "task_tier": "support",
        "fields": [
            _path_id("strategy_id", "策略 ID"),
            {
                "key": "offset",
                "label": "起始位置",
                "binding": "query",
                "input_type": "hidden",
                "value_type": "integer",
                "required": False,
                "default": 0,
            },
            {
                "key": "limit",
                "label": "每页数量",
                "binding": "query",
                "input_type": "hidden",
                "value_type": "integer",
                "required": False,
                "default": 20,
                "min": 1,
                "max": 200,
            },
        ],
        "pagination": {
            "mode": "offset",
            "offset_param": "offset",
            "limit_param": "limit",
        },
        "view_model": {
            "kind": "datagrid",
            "rows_path": "results",
            "total_path": "total",
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "execution_time", "label": "执行时间"},
                {"key": "is_success", "label": "成功"},
                {"key": "execution_duration_ms", "label": "耗时 ms"},
                {"key": "signals_count", "label": "信号数"},
                {"key": "portfolio_name", "label": "组合"},
            ],
        },
    },
    _mutation(
        key="strategy.execute",
        label="执行策略",
        endpoint=f"{_STRATEGIES}<int:strategy_id>/execute/",
        method="POST",
        effect="execute",
        sequence=1230,
        fields=[
            _path_id("strategy_id", "策略 ID"),
            _body_id("portfolio_id", "组合 ID"),
        ],
        description="对本人组合执行已启用策略，并保留执行日志。",
    ),
    _mutation(
        key="strategy.preview",
        label="预览策略",
        endpoint="/api/strategy/tui/strategies/<int:strategy_id>/preview/",
        method="POST",
        effect="execute",
        sequence=1240,
        fields=[
            _path_id("strategy_id", "策略 ID"),
            _body_id("portfolio_id", "组合 ID"),
        ],
        description="在测试上下文中预览脚本型或混合型策略的信号。",
    ),
)


__all__ = ["RUNTIME_STRATEGY_ACTIONS"]
