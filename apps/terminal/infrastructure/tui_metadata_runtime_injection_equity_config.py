"""Runtime TUI metadata for valuation-repair configuration governance."""

from __future__ import annotations

from typing import Any

from apps.equity.domain.entities_valuation_repair import (
    DEFAULT_VALUATION_REPAIR_CONFIG,
)

_SCREEN = "research.asset-lab"
_MODULE = "research"
_SOURCE = "approved:runtime-equity-valuation-config"
_BASE_ENDPOINT = "/api/equity/config/valuation-repair/"


def _number_field(
    key: str,
    label: str,
    *,
    default: int | float,
    value_type: str,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
) -> dict[str, Any]:
    """Build one bounded valuation configuration field."""

    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "binding": "body",
        "input_type": "number",
        "value_type": "float" if value_type == "number" else value_type,
        "required": False,
        "default": default,
    }
    if minimum is not None:
        field["min"] = minimum
    if maximum is not None:
        field["max"] = maximum
    return field


def _config_fields() -> list[dict[str, Any]]:
    """Build the full owner-supported valuation-repair parameter form."""

    defaults = DEFAULT_VALUATION_REPAIR_CONFIG
    return [
        {
            "key": "change_reason",
            "label": "变更原因",
            "binding": "body",
            "input_type": "textarea",
            "value_type": "string",
            "required": True,
            "max": 1000,
        },
        _number_field(
            "min_history_points",
            "最小历史样本数",
            default=defaults.min_history_points,
            value_type="integer",
            minimum=60,
        ),
        _number_field(
            "default_lookback_days",
            "默认回看交易日",
            default=defaults.default_lookback_days,
            value_type="integer",
            minimum=252,
        ),
        _number_field(
            "confirm_window",
            "确认窗口",
            default=defaults.confirm_window,
            value_type="integer",
            minimum=5,
        ),
        _number_field(
            "min_rebound",
            "最小反弹幅度",
            default=defaults.min_rebound,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "stall_window",
            "停滞窗口",
            default=defaults.stall_window,
            value_type="integer",
            minimum=10,
        ),
        _number_field(
            "stall_min_progress",
            "停滞最小进展",
            default=defaults.stall_min_progress,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "target_percentile",
            "目标百分位",
            default=defaults.target_percentile,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "undervalued_threshold",
            "低估阈值",
            default=defaults.undervalued_threshold,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "near_target_threshold",
            "接近目标阈值",
            default=defaults.near_target_threshold,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "overvalued_threshold",
            "高估阈值",
            default=defaults.overvalued_threshold,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "pe_weight",
            "PE 权重",
            default=defaults.pe_weight,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "pb_weight",
            "PB 权重",
            default=defaults.pb_weight,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "confidence_base",
            "基础置信度",
            default=defaults.confidence_base,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "confidence_sample_threshold",
            "置信度样本阈值",
            default=defaults.confidence_sample_threshold,
            value_type="integer",
            minimum=1,
        ),
        _number_field(
            "confidence_sample_bonus",
            "样本数奖励",
            default=defaults.confidence_sample_bonus,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "confidence_blend_bonus",
            "Blend 奖励",
            default=defaults.confidence_blend_bonus,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "confidence_repair_start_bonus",
            "修复起点奖励",
            default=defaults.confidence_repair_start_bonus,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "confidence_not_stalled_bonus",
            "非停滞奖励",
            default=defaults.confidence_not_stalled_bonus,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "repairing_threshold",
            "修复中阈值",
            default=defaults.repairing_threshold,
            value_type="number",
            minimum=0,
            maximum=1,
        ),
        _number_field(
            "eta_max_days",
            "ETA 最大天数",
            default=defaults.eta_max_days,
            value_type="integer",
            minimum=1,
        ),
    ]


def _config_id_field() -> dict[str, Any]:
    """Build the configuration version path identifier."""

    return {
        "key": "config_id",
        "label": "配置 ID",
        "binding": "path",
        "input_type": "number",
        "value_type": "integer",
        "required": True,
        "min": 1,
    }


def _mutation(
    *,
    key: str,
    label: str,
    endpoint: str,
    method: str,
    intent: str,
    description: str,
    sequence: int,
    fields: list[dict[str, Any]],
    effect: str,
) -> dict[str, Any]:
    """Build one admin-only valuation configuration mutation."""

    return {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": "admin",
        "audience": "admin",
        "effect": effect,
        "confirmation_required": True,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": description,
        "source": _SOURCE,
        "task_group": "06 估值修复配置",
        "sequence": sequence,
        "task_tier": "support",
        "fields": fields,
        "view_model": {
            "kind": "detail",
            "title_path": "version",
            "status_path": "success",
        },
    }


RUNTIME_EQUITY_CONFIG_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "equity.valuation-config-list",
        "label": "查看估值修复配置版本",
        "endpoint": _BASE_ENDPOINT,
        "method": "GET",
        "intent": "list_valuation_repair_configs",
        "risk": "read",
        "audience": "admin",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "datagrid",
        "description": "查看全部配置版本、激活状态、变更原因和审计时间。",
        "source": _SOURCE,
        "task_group": "06 估值修复配置",
        "sequence": 600,
        "task_tier": "support",
        "fields": [],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "",
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "version", "label": "版本"},
                {"key": "is_active", "label": "已激活"},
                {"key": "change_reason", "label": "变更原因"},
                {"key": "created_by", "label": "创建人"},
                {"key": "created_at", "label": "创建时间"},
            ],
        },
    },
    {
        "key": "equity.valuation-config-active",
        "label": "查看当前估值修复配置",
        "endpoint": f"{_BASE_ENDPOINT}active/",
        "method": "GET",
        "intent": "read_active_valuation_repair_config",
        "risk": "read",
        "audience": "admin",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": "查看当前生效配置及其数据库或默认配置来源。",
        "source": _SOURCE,
        "task_group": "06 估值修复配置",
        "sequence": 610,
        "task_tier": "support",
        "fields": [],
        "view_model": {
            "kind": "detail",
            "title_path": "data.version",
            "status_path": "source",
        },
    },
    _mutation(
        key="equity.valuation-config-create",
        label="创建估值修复配置",
        endpoint=_BASE_ENDPOINT,
        method="POST",
        intent="create_valuation_repair_config",
        description="创建不可变的新配置版本；保存后仍需显式激活。",
        sequence=620,
        fields=_config_fields(),
        effect="create",
    ),
    _mutation(
        key="equity.valuation-config-update",
        label="更新未激活估值修复配置",
        endpoint=f"{_BASE_ENDPOINT}<int:config_id>/",
        method="PATCH",
        intent="update_valuation_repair_config",
        description="按配置 ID 更新参数；owner API 拒绝修改已激活版本。",
        sequence=630,
        fields=[_config_id_field(), *_config_fields()],
        effect="update",
    ),
    _mutation(
        key="equity.valuation-config-activate",
        label="激活估值修复配置",
        endpoint=f"{_BASE_ENDPOINT}<int:config_id>/activate/",
        method="POST",
        intent="activate_valuation_repair_config",
        description="激活指定版本并停用其他版本。",
        sequence=640,
        fields=[_config_id_field()],
        effect="update",
    ),
    _mutation(
        key="equity.valuation-config-rollback",
        label="回滚估值修复配置",
        endpoint=f"{_BASE_ENDPOINT}<int:config_id>/rollback/",
        method="POST",
        intent="rollback_valuation_repair_config",
        description="将指定历史版本重新设为当前激活版本。",
        sequence=650,
        fields=[_config_id_field()],
        effect="update",
    ),
    _mutation(
        key="equity.valuation-config-delete",
        label="删除未激活估值修复配置",
        endpoint=f"{_BASE_ENDPOINT}<int:config_id>/",
        method="DELETE",
        intent="delete_valuation_repair_config",
        description="删除未激活的配置版本；owner API 保护当前激活版本。",
        sequence=660,
        fields=[_config_id_field()],
        effect="delete",
    ),
    _mutation(
        key="equity.valuation-config-clear-cache",
        label="清除估值修复配置缓存",
        endpoint=f"{_BASE_ENDPOINT}clear_cache/",
        method="POST",
        intent="clear_valuation_repair_config_cache",
        description="清除运行时配置缓存，使下一次读取重新解析当前配置。",
        sequence=670,
        fields=[],
        effect="execute",
    ),
)
