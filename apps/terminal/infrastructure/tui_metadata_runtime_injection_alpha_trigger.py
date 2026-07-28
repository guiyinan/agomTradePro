"""Curated runtime TUI metadata for Alpha Trigger read workflows."""

from __future__ import annotations

from typing import Any

_SCREEN = "research.alpha-triggers"
_MODULE = "daily-decisions"
_SOURCE = "approved:runtime-alpha-trigger"


def _field(
    key: str,
    label: str,
    *,
    binding: str = "query",
    input_type: str = "text",
    value_type: str = "string",
    required: bool = False,
    default: str | None = None,
    options: list[str] | None = None,
) -> dict[str, Any]:
    """Build one typed Alpha Trigger action field."""

    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "binding": binding,
        "input_type": input_type,
        "value_type": value_type,
        "required": required,
    }
    if default is not None:
        field["default"] = default
    if options is not None:
        field["options"] = options
    return field


def _read_action(
    *,
    key: str,
    label: str,
    endpoint: str,
    intent: str,
    description: str,
    sequence: int,
    fields: list[dict[str, Any]],
    view_model: dict[str, Any],
    view_type: str = "datagrid",
) -> dict[str, Any]:
    """Build one authenticated, read-only Alpha Trigger task."""

    return {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": "GET",
        "intent": intent,
        "risk": "read",
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": "03 Alpha 触发与候选",
        "sequence": sequence,
        "task_tier": "primary",
        "fields": fields,
        "view_model": view_model,
    }


def _mutation_action(
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
    view_type: str = "detail",
) -> dict[str, Any]:
    """Build one confirmed Alpha Trigger mutation task."""

    return {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": "write",
        "effect": effect,
        "confirmation_required": True,
        "audience": "authenticated",
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": "04 Alpha 触发器生命周期",
        "sequence": sequence,
        "task_tier": "support",
        "fields": fields,
        "view_model": {"kind": view_type, "status_path": "success"},
    }


_TRIGGER_COLUMNS = [
    {"key": "trigger_id", "label": "触发器 ID"},
    {"key": "asset_code", "label": "标的代码"},
    {"key": "trigger_type", "label": "触发类型"},
    {"key": "direction", "label": "方向"},
    {"key": "strength", "label": "强度"},
    {"key": "confidence", "label": "置信度"},
    {"key": "status", "label": "状态"},
    {"key": "expires_at", "label": "到期时间"},
]
_CANDIDATE_COLUMNS = [
    {"key": "asset_code", "label": "标的代码"},
    {"key": "direction", "label": "方向"},
    {"key": "strength", "label": "强度"},
    {"key": "confidence", "label": "置信度"},
    {"key": "status", "label": "状态"},
    {"key": "risk_level", "label": "风险等级"},
    {"key": "expected_return", "label": "预期收益"},
    {"key": "is_executed", "label": "已执行"},
]
_STRENGTH_OPTIONS = ["", "very_weak", "weak", "moderate", "strong", "very_strong"]

RUNTIME_ALPHA_TRIGGER_READ_ACTIONS: tuple[dict[str, Any], ...] = (
    _read_action(
        key="alpha-trigger.trigger-list",
        label="查看 Alpha 触发器",
        endpoint="/api/alpha-triggers/triggers/",
        intent="list_alpha_triggers",
        description="按标的查看当前 Alpha 触发器及其证伪状态。",
        sequence=300,
        fields=[_field("asset_code", "标的代码"), _field("status", "状态")],
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "columns": _TRIGGER_COLUMNS,
        },
    ),
    _read_action(
        key="alpha-trigger.trigger-active",
        label="查看活跃 Alpha 触发器",
        endpoint="/api/alpha-triggers/triggers/active/",
        intent="list_active_alpha_triggers",
        description="筛出仍处于有效期内、等待触发的 Alpha 规则。",
        sequence=310,
        fields=[
            _field("asset_code", "标的代码"),
            _field(
                "min_strength",
                "最低强度",
                input_type="select",
                options=_STRENGTH_OPTIONS,
            ),
        ],
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "columns": _TRIGGER_COLUMNS,
        },
    ),
    _read_action(
        key="alpha-trigger.trigger-detail",
        label="查看 Alpha 触发器详情",
        endpoint="/api/alpha-triggers/triggers/<trigger_id>/",
        intent="read_alpha_trigger",
        description="复核触发条件、证伪条件、投资论点和生命周期状态。",
        sequence=320,
        fields=[
            _field("trigger_id", "触发器 ID", binding="path", required=True)
        ],
        view_model={
            "kind": "detail",
            "title_path": "result.trigger_id",
            "status_path": "result.status",
        },
        view_type="detail",
    ),
    _read_action(
        key="alpha-trigger.candidate-list",
        label="查看 Alpha 候选",
        endpoint="/api/alpha-triggers/candidates/",
        intent="list_alpha_candidates",
        description="按标的或状态查看 Alpha 候选及其执行跟踪信息。",
        sequence=330,
        fields=[
            _field("asset_code", "标的代码"),
            _field(
                "status",
                "候选状态",
                input_type="select",
                options=[
                    "",
                    "WATCH",
                    "CANDIDATE",
                    "ACTIONABLE",
                    "EXECUTED",
                    "CANCELLED",
                ],
            ),
        ],
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "columns": _CANDIDATE_COLUMNS,
        },
    ),
    _read_action(
        key="alpha-trigger.candidate-actionable",
        label="查看可操作 Alpha 候选",
        endpoint="/api/alpha-triggers/candidates/actionable/",
        intent="list_actionable_alpha_candidates",
        description="优先查看已达到行动条件、仍需执行前复核的候选。",
        sequence=340,
        fields=[
            _field(
                "min_strength",
                "最低强度",
                input_type="select",
                options=_STRENGTH_OPTIONS,
            )
        ],
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "columns": _CANDIDATE_COLUMNS,
        },
    ),
    _read_action(
        key="alpha-trigger.candidate-watch-list",
        label="查看 Alpha 观察列表",
        endpoint="/api/alpha-triggers/candidates/watch-list/",
        intent="list_alpha_candidate_watch_list",
        description="查看尚未达到行动条件、需要继续等待验证的候选。",
        sequence=350,
        fields=[],
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "columns": _CANDIDATE_COLUMNS,
        },
    ),
    _read_action(
        key="alpha-trigger.candidate-detail",
        label="查看 Alpha 候选详情",
        endpoint="/api/alpha-triggers/candidates/<candidate_id>/",
        intent="read_alpha_candidate",
        description="复核候选的入场区、退出区、风险等级和决策执行跟踪。",
        sequence=360,
        fields=[
            _field("candidate_id", "候选 ID", binding="path", required=True)
        ],
        view_model={
            "kind": "detail",
            "title_path": "result.candidate_id",
            "status_path": "result.status",
        },
        view_type="detail",
    ),
    _read_action(
        key="alpha-trigger.trigger-statistics",
        label="查看触发器统计",
        endpoint="/api/alpha-triggers/triggers/statistics/",
        intent="read_alpha_trigger_statistics",
        description="查看指定窗口内触发器的类型和状态分布。",
        sequence=370,
        fields=[
            _field(
                "days",
                "统计天数",
                input_type="number",
                value_type="integer",
                default="30",
            )
        ],
        view_model={"kind": "detail", "status_path": "success"},
        view_type="detail",
    ),
    _read_action(
        key="alpha-trigger.candidate-statistics",
        label="查看候选统计",
        endpoint="/api/alpha-triggers/candidates/statistics/",
        intent="read_alpha_candidate_statistics",
        description="查看指定窗口内候选状态和转化概况。",
        sequence=380,
        fields=[
            _field(
                "days",
                "统计天数",
                input_type="number",
                value_type="integer",
                default="30",
            )
        ],
        view_model={"kind": "detail", "status_path": "success"},
        view_type="detail",
    ),
    _read_action(
        key="alpha-trigger.performance",
        label="复核 Alpha 触发绩效",
        endpoint="/api/alpha-triggers/performance/",
        intent="read_alpha_trigger_performance",
        description="按统计窗口或触发器复核候选转化率与证伪率。",
        sequence=390,
        fields=[
            _field(
                "days",
                "统计天数",
                input_type="number",
                value_type="integer",
                default="30",
            ),
            _field("trigger_id", "触发器 ID"),
        ],
        view_model={
            "kind": "datagrid",
            "rows_path": "data",
            "columns": [
                {"key": "trigger_id", "label": "触发器 ID"},
                {"key": "asset_code", "label": "标的代码"},
                {"key": "trigger_type", "label": "触发类型"},
                {"key": "total_candidates", "label": "候选数"},
                {"key": "executed", "label": "已执行"},
                {"key": "invalidated", "label": "已证伪"},
                {"key": "conversion_rate", "label": "转化率"},
                {"key": "invalidation_rate", "label": "证伪率"},
            ],
        },
    ),
)

_TRIGGER_ID_PATH = _field(
    "trigger_id",
    "触发器 ID",
    binding="path",
    required=True,
)
_TRIGGER_TYPE_OPTIONS = [
    "threshold_cross",
    "momentum_signal",
    "regime_transition",
    "policy_change",
    "manual_override",
    "structural_misalignment",
    "supply_shock",
    "credit_spread",
]
_DIRECTION_OPTIONS = ["LONG", "SHORT", "NEUTRAL"]
_EDIT_FIELDS = [
    _field("asset_class", "资产类别", binding="body"),
    _field(
        "direction",
        "方向",
        binding="body",
        input_type="select",
        options=_DIRECTION_OPTIONS,
    ),
    _field(
        "trigger_condition",
        "触发条件（JSON）",
        binding="body",
        input_type="textarea",
        value_type="object",
    ),
    _field(
        "invalidation_conditions",
        "证伪条件（JSON 数组）",
        binding="body",
        input_type="textarea",
        value_type="list",
    ),
    _field(
        "confidence",
        "置信度",
        binding="body",
        input_type="number",
        value_type="float",
    ),
    _field("thesis", "投资论点", binding="body", input_type="textarea"),
    _field("related_regime", "相关 Regime", binding="body"),
    _field(
        "related_policy_level",
        "相关政策档位",
        binding="body",
        input_type="number",
        value_type="integer",
    ),
]

RUNTIME_ALPHA_TRIGGER_MUTATION_ACTIONS: tuple[dict[str, Any], ...] = (
    _mutation_action(
        key="alpha-trigger.create",
        label="创建 Alpha 触发器",
        endpoint="/api/alpha-triggers/create/",
        method="POST",
        intent="create_alpha_trigger",
        description="创建包含明确触发条件和证伪条件的 Alpha 触发器。",
        sequence=400,
        effect="create",
        fields=[
            _field(
                "trigger_type",
                "触发器类型",
                binding="body",
                input_type="select",
                required=True,
                options=_TRIGGER_TYPE_OPTIONS,
            ),
            _field("asset_code", "资产代码", binding="body", required=True),
            _field("asset_class", "资产类别", binding="body", required=True),
            _field(
                "direction",
                "方向",
                binding="body",
                input_type="select",
                required=True,
                options=_DIRECTION_OPTIONS,
            ),
            _field(
                "trigger_condition",
                "触发条件（JSON）",
                binding="body",
                input_type="textarea",
                value_type="object",
                required=True,
            ),
            _field(
                "invalidation_conditions",
                "证伪条件（JSON 数组）",
                binding="body",
                input_type="textarea",
                value_type="list",
                required=True,
            ),
            _field(
                "confidence",
                "置信度",
                binding="body",
                input_type="number",
                value_type="float",
                required=True,
            ),
            _field("thesis", "投资论点", binding="body", input_type="textarea"),
            _field(
                "expires_in_days",
                "有效天数",
                binding="body",
                input_type="number",
                value_type="integer",
            ),
            _field("related_regime", "相关 Regime", binding="body"),
            _field(
                "related_policy_level",
                "相关政策档位",
                binding="body",
                input_type="number",
                value_type="integer",
            ),
            _field("source_signal_id", "来源信号 ID", binding="body"),
        ],
    ),
    _mutation_action(
        key="alpha-trigger.update",
        label="编辑 Alpha 触发器",
        endpoint="/api/alpha-triggers/triggers/<trigger_id>/",
        method="PATCH",
        intent="update_alpha_trigger",
        description="更新触发规则、证伪条件、置信度和投资论点。",
        sequence=410,
        effect="update",
        fields=[_TRIGGER_ID_PATH, *_EDIT_FIELDS],
    ),
    *[
        _mutation_action(
            key=f"alpha-trigger.{operation}",
            label=label,
            endpoint=endpoint,
            method=method,
            intent=f"{operation}_alpha_trigger",
            description=description,
            sequence=sequence,
            effect=effect,
            fields=[_TRIGGER_ID_PATH],
        )
        for operation, label, endpoint, method, description, sequence, effect in (
            (
                "pause",
                "暂停 Alpha 触发器",
                "/api/alpha-triggers/triggers/<trigger_id>/pause/",
                "POST",
                "暂停活跃触发器并保留规则和审计记录。",
                420,
                "update",
            ),
            (
                "resume",
                "恢复 Alpha 触发器",
                "/api/alpha-triggers/triggers/<trigger_id>/resume/",
                "POST",
                "把已暂停触发器恢复为活跃状态。",
                430,
                "update",
            ),
            (
                "cancel",
                "取消 Alpha 触发器",
                "/api/alpha-triggers/triggers/<trigger_id>/",
                "DELETE",
                "软取消触发器并保留历史证据。",
                440,
                "delete",
            ),
        )
    ],
    _mutation_action(
        key="alpha-trigger.check-invalidation",
        label="检查 Alpha 触发器证伪条件",
        endpoint="/api/alpha-triggers/check-invalidation/",
        method="POST",
        intent="check_alpha_trigger_invalidation",
        description="用当前指标值检查触发器是否已满足证伪条件。",
        sequence=450,
        effect="execute",
        fields=[
            _field("trigger_id", "触发器 ID", binding="body", required=True),
            _field(
                "current_indicator_values",
                "当前指标值（JSON）",
                binding="body",
                input_type="textarea",
                value_type="object",
                required=True,
            ),
            _field("current_regime", "当前 Regime", binding="body"),
        ],
    ),
    _mutation_action(
        key="alpha-trigger.evaluate",
        label="评估 Alpha 触发器",
        endpoint="/api/alpha-triggers/evaluate/",
        method="POST",
        intent="evaluate_alpha_trigger",
        description="用当前数据评估一个活跃触发器是否达到触发条件。",
        sequence=460,
        effect="execute",
        fields=[
            _field("trigger_id", "触发器 ID", binding="body", required=True),
            _field(
                "current_data",
                "当前数据（JSON）",
                binding="body",
                input_type="textarea",
                value_type="object",
                required=True,
            ),
        ],
    ),
    _mutation_action(
        key="alpha-trigger.generate-candidate",
        label="从触发器生成候选",
        endpoint="/api/alpha-triggers/generate-candidate/",
        method="POST",
        intent="generate_alpha_candidate",
        description="从已触发规则生成带入场、退出和风险信息的候选。",
        sequence=470,
        effect="create",
        fields=[
            _field("trigger_id", "触发器 ID", binding="body", required=True),
            _field(
                "time_window_days",
                "时间窗口天数",
                binding="body",
                input_type="number",
                value_type="integer",
                default="90",
            ),
        ],
    ),
    _mutation_action(
        key="alpha-trigger.candidate-update-status",
        label="更新 Alpha 候选状态",
        endpoint="/api/alpha-triggers/candidates/<candidate_id>/update-status/",
        method="POST",
        intent="update_alpha_candidate_status",
        description="显式更新候选状态并保留状态变更时间。",
        sequence=480,
        effect="update",
        fields=[
            _field(
                "candidate_id",
                "候选 ID",
                binding="path",
                required=True,
            ),
            _field(
                "status",
                "新状态",
                binding="body",
                input_type="select",
                required=True,
                options=["WATCH", "CANDIDATE", "ACTIONABLE", "EXECUTED", "CANCELLED"],
            ),
        ],
    ),
)
