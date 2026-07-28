"""Runtime TUI metadata for privileged Alpha operations."""

from __future__ import annotations

from typing import Any

from apps.alpha.application.pool_resolver import ALPHA_POOL_MODE_CHOICES

_SCREEN = "research.signals"
_MODULE = "daily-decisions"
_SOURCE = "approved:runtime-alpha-ops"
_POOL_MODE_OPTIONS = [
    {"value": value, "label": label} for value, label in ALPHA_POOL_MODE_CHOICES
]


def _hidden_mode(value: str) -> dict[str, Any]:
    """Build the fixed operation-mode field for one curated task."""

    return {
        "key": "mode",
        "label": "任务模式",
        "binding": "body",
        "input_type": "hidden",
        "value_type": "string",
        "required": True,
        "default": value,
    }


def _date_field(key: str, label: str) -> dict[str, Any]:
    """Build a required date field."""

    return {
        "key": key,
        "label": label,
        "binding": "body",
        "input_type": "date",
        "value_type": "date",
        "required": True,
    }


def _top_n_field() -> dict[str, Any]:
    """Build the bounded inference candidate-count field."""

    return {
        "key": "top_n",
        "label": "候选数量",
        "binding": "body",
        "input_type": "number",
        "value_type": "integer",
        "required": False,
        "default": 30,
        "min": 1,
        "max": 500,
    }


def _pool_mode_field() -> dict[str, Any]:
    """Build the shared Alpha pool selector."""

    return {
        "key": "pool_mode",
        "label": "资产池口径",
        "binding": "body",
        "input_type": "select",
        "value_type": "string",
        "required": False,
        "default": "price_covered",
        "options": _POOL_MODE_OPTIONS,
    }


def _base_action(
    *,
    key: str,
    label: str,
    endpoint: str,
    intent: str,
    description: str,
    sequence: int,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one superuser-only, confirmation-required Alpha operation."""

    return {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": "POST",
        "intent": intent,
        "risk": "admin",
        "audience": "admin",
        "effect": "execute",
        "confirmation_required": True,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": "detail",
        "description": description,
        "source": _SOURCE,
        "task_group": "05 Alpha 运维",
        "sequence": sequence,
        "task_tier": "support",
        "fields": fields,
        "view_model": {
            "kind": "detail",
            "title_path": "task_id",
            "status_path": "success",
        },
    }


RUNTIME_ALPHA_OPS_ACTIONS: tuple[dict[str, Any], ...] = (
    _base_action(
        key="alpha.inference.trigger_general",
        label="触发通用 Alpha 推理",
        endpoint="/api/alpha/ops/inference/trigger/",
        intent="trigger_general_alpha_inference",
        description="按交易日和 Universe 异步触发通用 Alpha 推理。",
        sequence=510,
        fields=[
            _hidden_mode("general"),
            _date_field("trade_date", "交易日"),
            _top_n_field(),
            {
                "key": "universe_id",
                "label": "Universe ID",
                "binding": "body",
                "input_type": "text",
                "value_type": "string",
                "required": True,
                "default": "csi300",
            },
        ],
    ),
    _base_action(
        key="alpha.inference.trigger_portfolio",
        label="触发单组合 Alpha 推理",
        endpoint="/api/alpha/ops/inference/trigger/",
        intent="trigger_portfolio_alpha_inference",
        description="按交易日和组合范围异步触发 Scoped Alpha 推理。",
        sequence=520,
        fields=[
            _hidden_mode("portfolio_scoped"),
            _date_field("trade_date", "交易日"),
            _top_n_field(),
            {
                "key": "portfolio_id",
                "label": "组合 ID",
                "binding": "body",
                "input_type": "number",
                "value_type": "integer",
                "required": True,
                "min": 1,
            },
            _pool_mode_field(),
        ],
    ),
    _base_action(
        key="alpha.inference.trigger_batch",
        label="触发 Active Portfolios 批量推理",
        endpoint="/api/alpha/ops/inference/trigger/",
        intent="trigger_alpha_inference_batch",
        description="对全部启用组合异步触发 Alpha 推理任务。",
        sequence=530,
        fields=[
            _hidden_mode("daily_scoped_batch"),
            _top_n_field(),
            _pool_mode_field(),
        ],
    ),
    _base_action(
        key="alpha.qlib_data_refresh_universes",
        label="刷新 Qlib Universe 数据",
        endpoint="/api/alpha/ops/qlib-data/refresh/",
        intent="refresh_qlib_universe_data",
        description="按目标日期、回看窗口和 Universe 列表异步刷新 Qlib 数据。",
        sequence=540,
        fields=[
            _hidden_mode("universes"),
            _date_field("target_date", "目标日期"),
            {
                "key": "lookback_days",
                "label": "回看天数",
                "binding": "body",
                "input_type": "number",
                "value_type": "integer",
                "required": False,
                "default": 400,
                "min": 1,
                "max": 2000,
            },
            {
                "key": "universes",
                "label": "Universe 列表",
                "binding": "body",
                "input_type": "text",
                "value_type": "string",
                "required": True,
                "default": "csi300,csi500",
                "placeholder": "使用英文逗号分隔",
            },
        ],
    ),
    _base_action(
        key="alpha.qlib_data_refresh",
        label="刷新组合范围 Qlib 数据",
        endpoint="/api/alpha/ops/qlib-data/refresh/",
        intent="refresh_qlib_runtime_data",
        description="按组合范围异步刷新 Qlib 数据；可指定组合或选择全部启用组合。",
        sequence=550,
        fields=[
            _hidden_mode("scoped_codes"),
            _date_field("target_date", "目标日期"),
            {
                "key": "lookback_days",
                "label": "回看天数",
                "binding": "body",
                "input_type": "number",
                "value_type": "integer",
                "required": False,
                "default": 120,
                "min": 1,
                "max": 2000,
            },
            {
                "key": "portfolio_ids",
                "label": "组合 ID",
                "binding": "body",
                "input_type": "text",
                "value_type": "string",
                "required": False,
                "placeholder": "使用英文逗号分隔",
            },
            {
                "key": "all_active_portfolios",
                "label": "全部启用组合",
                "binding": "body",
                "input_type": "checkbox",
                "value_type": "boolean",
                "required": False,
                "default": False,
            },
            _pool_mode_field(),
        ],
    ),
)
