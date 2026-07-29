"""Runtime TUI metadata for factor-portfolio configuration governance."""

from __future__ import annotations

from typing import Any

from apps.factor.application.use_cases import (
    FACTOR_REBALANCE_CHOICES,
    FACTOR_UNIVERSE_CHOICES,
    FACTOR_WEIGHT_METHOD_CHOICES,
)

_SCREEN = "research.asset-lab"
_MODULE = "research"
_SOURCE = "approved:runtime-factor-portfolios"
_BASE_ENDPOINT = "/api/factor/configs/"


def _config_id_field() -> dict[str, Any]:
    """Build the portfolio-configuration path identifier."""

    return {
        "key": "config_id",
        "label": "组合配置 ID",
        "binding": "path",
        "input_type": "number",
        "value_type": "integer",
        "required": True,
        "min": 1,
    }


def _number_field(
    key: str,
    label: str,
    *,
    value_type: str = "float",
    minimum: int | float | None = None,
    maximum: int | float | None = None,
    default: int | float | None = None,
) -> dict[str, Any]:
    """Build one bounded optional numeric field."""

    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "binding": "body",
        "input_type": "number",
        "value_type": value_type,
        "required": False,
    }
    if minimum is not None:
        field["min"] = minimum
    if maximum is not None:
        field["max"] = maximum
    if default is not None:
        field["default"] = default
    return field


def _config_fields(*, create: bool) -> list[dict[str, Any]]:
    """Build scalar portfolio configuration fields without raw weight JSON."""

    fields: list[dict[str, Any]] = [
        {
            "key": "name",
            "label": "配置名称",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": create,
            "max": 100,
        },
        {
            "key": "description",
            "label": "配置描述",
            "binding": "body",
            "input_type": "textarea",
            "value_type": "string",
            "required": False,
        },
        {
            "key": "universe",
            "label": "股票池",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": False,
            "default": "all_a",
            "options": list(FACTOR_UNIVERSE_CHOICES),
        },
        _number_field("min_market_cap", "最小市值（亿）", minimum=0),
        _number_field("max_market_cap", "最大市值（亿）", minimum=0),
        _number_field("min_pe", "最小 PE", minimum=0),
        _number_field("max_pe", "最大 PE", minimum=0),
        _number_field("max_pb", "最大 PB", minimum=0),
        _number_field("max_debt_ratio", "最大资产负债率（%）", minimum=0, maximum=100),
        _number_field(
            "top_n",
            "选股数量",
            value_type="integer",
            minimum=1,
            maximum=500,
            default=30,
        ),
        {
            "key": "rebalance_frequency",
            "label": "调仓频率",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": False,
            "default": "monthly",
            "options": list(FACTOR_REBALANCE_CHOICES),
        },
        {
            "key": "weight_method",
            "label": "持仓权重方式",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": False,
            "default": "equal_weight",
            "options": list(FACTOR_WEIGHT_METHOD_CHOICES),
        },
        _number_field(
            "max_sector_weight",
            "最大行业权重",
            minimum=0.000001,
            maximum=1,
            default=0.4,
        ),
        _number_field(
            "max_single_stock_weight",
            "最大单股权重",
            minimum=0.000001,
            maximum=1,
            default=0.05,
        ),
    ]
    if create:
        fields.append(
            {
                "key": "is_active",
                "label": "创建后立即启用",
                "binding": "body",
                "input_type": "checkbox",
                "value_type": "boolean",
                "required": False,
                "default": False,
            }
        )
    return fields


def _mutation(
    *,
    key: str,
    label: str,
    endpoint: str,
    method: str,
    intent: str,
    effect: str,
    sequence: int,
    fields: list[dict[str, Any]],
    description: str,
) -> dict[str, Any]:
    """Build one authenticated factor-portfolio mutation."""

    return {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": "write",
        "audience": "authenticated",
        "effect": effect,
        "confirmation_required": True,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": description,
        "source": _SOURCE,
        "task_group": "07 因子研究",
        "sequence": sequence,
        "task_tier": "support",
        "fields": fields,
        "view_model": {
            "kind": "detail",
            "title_path": "name",
            "status_path": "is_active",
        },
    }


RUNTIME_FACTOR_PORTFOLIO_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "factor.portfolio-config-list",
        "label": "查看因子组合配置",
        "endpoint": _BASE_ENDPOINT,
        "method": "GET",
        "intent": "list_factor_portfolio_configs",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "按状态、股票池、调仓频率和关键字查看组合配置。",
        "source": _SOURCE,
        "task_group": "07 因子研究",
        "sequence": 780,
        "task_tier": "support",
        "fields": [
            {
                "key": "is_active",
                "label": "仅看启用状态",
                "binding": "query",
                "input_type": "checkbox",
                "value_type": "boolean",
                "required": False,
            },
            {
                "key": "universe",
                "label": "股票池",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "options": list(FACTOR_UNIVERSE_CHOICES),
            },
            {
                "key": "rebalance_frequency",
                "label": "调仓频率",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "options": list(FACTOR_REBALANCE_CHOICES),
            },
            {
                "key": "search",
                "label": "搜索名称或描述",
                "binding": "query",
                "input_type": "text",
                "value_type": "string",
                "required": False,
            },
        ],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "",
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "name", "label": "配置名称"},
                {"key": "universe", "label": "股票池"},
                {"key": "top_n", "label": "选股数量"},
                {"key": "rebalance_frequency", "label": "调仓频率"},
                {"key": "weight_method", "label": "持仓权重"},
                {"key": "factor_weights", "label": "因子权重"},
                {"key": "is_active", "label": "已启用"},
            ],
        },
    },
    {
        "key": "factor.portfolio-config-detail",
        "label": "查看因子组合配置详情",
        "endpoint": f"{_BASE_ENDPOINT}<int:config_id>/",
        "method": "GET",
        "intent": "read_factor_portfolio_config",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "按 ID 查看配置、筛选条件、风险限制和当前因子权重。",
        "source": _SOURCE,
        "task_group": "07 因子研究",
        "sequence": 790,
        "task_tier": "support",
        "fields": [_config_id_field()],
        "view_model": {
            "kind": "detail",
            "title_path": "name",
            "status_path": "is_active",
        },
    },
    _mutation(
        key="factor.portfolio-config-create",
        label="新建因子组合配置",
        endpoint=_BASE_ENDPOINT,
        method="POST",
        intent="create_factor_portfolio_config",
        effect="create",
        sequence=800,
        fields=_config_fields(create=True),
        description="先创建标量配置，再逐项设置因子权重；无需编辑原始 JSON。",
    ),
    _mutation(
        key="factor.portfolio-config-update",
        label="更新因子组合配置",
        endpoint=f"{_BASE_ENDPOINT}<int:config_id>/",
        method="PATCH",
        intent="update_factor_portfolio_config",
        effect="update",
        sequence=810,
        fields=[_config_id_field(), *_config_fields(create=False)],
        description="局部更新组合、筛选和风险参数；启停与因子权重使用独立动作。",
    ),
    _mutation(
        key="factor.portfolio-factor-weight-set",
        label="设置单个因子权重",
        endpoint=f"{_BASE_ENDPOINT}<int:config_id>/factor-weight/",
        method="PATCH",
        intent="set_factor_portfolio_weight",
        effect="update",
        sequence=820,
        fields=[
            _config_id_field(),
            {
                "key": "factor_code",
                "label": "因子代码",
                "binding": "body",
                "input_type": "text",
                "value_type": "string",
                "required": True,
                "max": 50,
            },
            _number_field(
                "weight",
                "因子权重",
                minimum=-1,
                maximum=1,
            )
            | {"required": True},
        ],
        description="按因子代码设置 -1 到 1 的单项权重；代码必须来自因子定义。",
    ),
    _mutation(
        key="factor.portfolio-factor-weight-remove",
        label="移除单个因子权重",
        endpoint=f"{_BASE_ENDPOINT}<int:config_id>/remove-factor-weight/",
        method="POST",
        intent="remove_factor_portfolio_weight",
        effect="update",
        sequence=830,
        fields=[
            _config_id_field(),
            {
                "key": "factor_code",
                "label": "因子代码",
                "binding": "body",
                "input_type": "text",
                "value_type": "string",
                "required": True,
                "max": 50,
            },
        ],
        description="按代码移除一个权重项，也可清理已删除因子的陈旧配置。",
    ),
    _mutation(
        key="factor.portfolio-config-activate",
        label="启用因子组合配置",
        endpoint=f"{_BASE_ENDPOINT}<int:config_id>/activate/",
        method="POST",
        intent="activate_factor_portfolio_config",
        effect="update",
        sequence=840,
        fields=[_config_id_field()],
        description="启用指定组合配置。",
    ),
    _mutation(
        key="factor.portfolio-config-deactivate",
        label="停用因子组合配置",
        endpoint=f"{_BASE_ENDPOINT}<int:config_id>/deactivate/",
        method="POST",
        intent="deactivate_factor_portfolio_config",
        effect="update",
        sequence=850,
        fields=[_config_id_field()],
        description="停用指定组合配置。",
    ),
    _mutation(
        key="factor.portfolio-config-generate",
        label="生成因子组合",
        endpoint=f"{_BASE_ENDPOINT}<int:config_id>/generate_portfolio/",
        method="POST",
        intent="generate_factor_portfolio",
        effect="execute",
        sequence=860,
        fields=[_config_id_field()],
        description="使用当前配置和因子权重计算并生成组合持仓。",
    ),
    _mutation(
        key="factor.portfolio-config-delete",
        label="删除因子组合配置",
        endpoint=f"{_BASE_ENDPOINT}<int:config_id>/",
        method="DELETE",
        intent="delete_factor_portfolio_config",
        effect="delete",
        sequence=870,
        fields=[_config_id_field()],
        description="永久删除指定组合配置；执行前必须确认。",
    ),
)
