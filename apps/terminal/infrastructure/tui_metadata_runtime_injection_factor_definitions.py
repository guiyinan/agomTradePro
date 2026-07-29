"""Runtime TUI metadata for factor-definition governance."""

from __future__ import annotations

from typing import Any

from apps.factor.domain.entities import FactorCategory, FactorDirection

_SCREEN = "research.asset-lab"
_MODULE = "research"
_SOURCE = "approved:runtime-factor-definitions"
_BASE_ENDPOINT = "/api/factor/definitions/"
_UPDATE_FREQUENCIES = ("daily", "weekly", "monthly", "quarterly")


def _factor_id_field() -> dict[str, Any]:
    """Build the factor-definition path identifier."""

    return {
        "key": "factor_id",
        "label": "因子 ID",
        "binding": "path",
        "input_type": "number",
        "value_type": "integer",
        "required": True,
        "min": 1,
    }


def _definition_fields(*, required: bool) -> list[dict[str, Any]]:
    """Build the owner-supported factor-definition form."""

    return [
        {
            "key": "code",
            "label": "因子代码",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": required,
            "max": 50,
        },
        {
            "key": "name",
            "label": "因子名称",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": required,
            "max": 100,
        },
        {
            "key": "category",
            "label": "因子类别",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": required,
            "options": [category.value for category in FactorCategory],
        },
        {
            "key": "description",
            "label": "因子描述",
            "binding": "body",
            "input_type": "textarea",
            "value_type": "string",
            "required": False,
        },
        {
            "key": "data_source",
            "label": "数据来源",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": required,
            "max": 50,
        },
        {
            "key": "data_field",
            "label": "数据字段",
            "binding": "body",
            "input_type": "text",
            "value_type": "string",
            "required": required,
            "max": 100,
        },
        {
            "key": "direction",
            "label": "因子方向",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": False,
            "default": FactorDirection.POSITIVE.value,
            "options": [direction.value for direction in FactorDirection],
        },
        {
            "key": "update_frequency",
            "label": "更新频率",
            "binding": "body",
            "input_type": "select",
            "value_type": "string",
            "required": False,
            "default": "daily",
            "options": list(_UPDATE_FREQUENCIES),
        },
        {
            "key": "is_active",
            "label": "启用因子",
            "binding": "body",
            "input_type": "checkbox",
            "value_type": "boolean",
            "required": False,
            "default": True,
        },
        {
            "key": "min_data_points",
            "label": "最小数据点",
            "binding": "body",
            "input_type": "number",
            "value_type": "integer",
            "required": False,
            "default": 20,
            "min": 1,
        },
        {
            "key": "allow_missing",
            "label": "允许缺失值",
            "binding": "body",
            "input_type": "checkbox",
            "value_type": "boolean",
            "required": False,
            "default": False,
        },
    ]


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
    """Build one authenticated factor-definition mutation."""

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
            "title_path": "code",
            "status_path": "is_active",
        },
    }


RUNTIME_FACTOR_DEFINITION_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "factor.definition-list",
        "label": "查看因子定义",
        "endpoint": _BASE_ENDPOINT,
        "method": "GET",
        "intent": "list_factor_definitions",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "按类别、启用状态或关键字查看因子定义。",
        "source": _SOURCE,
        "task_group": "07 因子研究",
        "sequence": 720,
        "task_tier": "support",
        "fields": [
            {
                "key": "category",
                "label": "因子类别",
                "binding": "query",
                "input_type": "select",
                "value_type": "string",
                "required": False,
                "options": [category.value for category in FactorCategory],
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
                "label": "搜索代码、名称或描述",
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
                {"key": "code", "label": "因子代码"},
                {"key": "name", "label": "因子名称"},
                {"key": "category_display", "label": "类别"},
                {"key": "direction_display", "label": "方向"},
                {"key": "data_source", "label": "数据源"},
                {"key": "update_frequency", "label": "更新频率"},
                {"key": "is_active", "label": "已启用"},
            ],
        },
    },
    {
        "key": "factor.definition-detail",
        "label": "查看因子定义详情",
        "endpoint": f"{_BASE_ENDPOINT}<int:factor_id>/",
        "method": "GET",
        "intent": "read_factor_definition",
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "按 ID 查看完整因子定义和数据质量要求。",
        "source": _SOURCE,
        "task_group": "07 因子研究",
        "sequence": 730,
        "task_tier": "support",
        "fields": [_factor_id_field()],
        "view_model": {
            "kind": "detail",
            "title_path": "code",
            "status_path": "is_active",
        },
    },
    _mutation(
        key="factor.definition-create",
        label="新建因子定义",
        endpoint=_BASE_ENDPOINT,
        method="POST",
        intent="create_factor_definition",
        effect="create",
        sequence=740,
        fields=_definition_fields(required=True),
        description="创建一个具有明确来源、字段、方向和数据质量要求的因子。",
    ),
    _mutation(
        key="factor.definition-update",
        label="更新因子定义",
        endpoint=f"{_BASE_ENDPOINT}<int:factor_id>/",
        method="PATCH",
        intent="update_factor_definition",
        effect="update",
        sequence=750,
        fields=[_factor_id_field(), *_definition_fields(required=False)],
        description="按 ID 局部更新因子定义；未填写字段保持原值。",
    ),
    _mutation(
        key="factor.definition-toggle",
        label="切换因子启用状态",
        endpoint=f"{_BASE_ENDPOINT}<int:factor_id>/toggle-active/",
        method="POST",
        intent="toggle_factor_definition",
        effect="update",
        sequence=760,
        fields=[_factor_id_field()],
        description="按当前状态启用或停用指定因子。",
    ),
    _mutation(
        key="factor.definition-delete",
        label="删除因子定义",
        endpoint=f"{_BASE_ENDPOINT}<int:factor_id>/",
        method="DELETE",
        intent="delete_factor_definition",
        effect="delete",
        sequence=770,
        fields=[_factor_id_field()],
        description="永久删除指定因子定义；执行前必须确认。",
    ),
)
