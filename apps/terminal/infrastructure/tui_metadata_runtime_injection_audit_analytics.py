"""Runtime TUI metadata for Audit analytical charts and threshold workflows."""

from __future__ import annotations

from typing import Any

_SCREEN = "execution.audit"
_MODULE = "execution"
_SOURCE = "approved:runtime-audit-analytics"


def _field(
    key: str,
    label: str,
    *,
    binding: str = "body",
    input_type: str = "text",
    value_type: str = "string",
    required: bool = False,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
) -> dict[str, Any]:
    """Build one typed analytical action field."""

    field: dict[str, Any] = {
        "key": key,
        "label": label,
        "binding": binding,
        "input_type": input_type,
        "value_type": value_type,
        "required": required,
    }
    if minimum is not None:
        field["min"] = minimum
    if maximum is not None:
        field["max"] = maximum
    return field


def _action(
    *,
    key: str,
    label: str,
    endpoint: str,
    intent: str,
    view_type: str,
    description: str,
    task_group: str,
    sequence: int,
    fields: list[dict[str, Any]],
    view_model: dict[str, Any],
    method: str = "GET",
    audience: str = "authenticated",
    effect: str = "read",
    confirmation_required: bool = False,
    audit_required: bool = False,
) -> dict[str, Any]:
    """Build one Audit analytics action with explicit result projection."""

    action: dict[str, Any] = {
        "key": key,
        "label": label,
        "endpoint": endpoint,
        "method": method,
        "intent": intent,
        "risk": "admin" if audience == "admin" else "read",
        "audience": audience,
        "effect": effect,
        "screen_key": _SCREEN,
        "module_key": _MODULE,
        "view_type": view_type,
        "description": description,
        "source": _SOURCE,
        "task_group": task_group,
        "sequence": sequence,
        "task_tier": "operation",
        "fields": fields,
        "view_model": view_model,
    }
    if confirmation_required:
        action["confirmation_required"] = True
    if audit_required:
        action["audit_required"] = True
    return action


_REPORT_ID_FIELD = _field(
    "report_id",
    "报告 ID",
    binding="path",
    input_type="number",
    value_type="integer",
    required=True,
    minimum=1,
)

_THRESHOLD_FIELDS: list[dict[str, Any]] = [
    _field("indicator_code", "指标代码", required=True, maximum=50),
    _field(
        "level_low",
        "低阈值",
        input_type="number",
        value_type="float",
        required=True,
    ),
    _field(
        "level_high",
        "高阈值",
        input_type="number",
        value_type="float",
        required=True,
    ),
]

_VALIDATION_FIELDS: list[dict[str, Any]] = [
    _field(
        "start_date",
        "开始日期",
        input_type="date",
        value_type="date",
        required=True,
    ),
    _field(
        "end_date",
        "结束日期",
        input_type="date",
        value_type="date",
        required=True,
    ),
]


RUNTIME_AUDIT_ANALYTICS_ACTIONS: tuple[dict[str, Any], ...] = (
    _action(
        key="audit.attribution-detail",
        label="归因报告详情",
        endpoint="/api/audit/tui/attribution/{report_id}/",
        intent="inspect_attribution_report_evidence",
        view_type="detail",
        description="查看一份归因报告的收益、准确率、损失项和经验证据。",
        task_group="05 归因分析",
        sequence=110,
        fields=[_REPORT_ID_FIELD],
        view_model={"kind": "detail"},
    ),
    _action(
        key="audit.attribution-contribution-chart",
        label="归因贡献图",
        endpoint="/api/audit/tui/attribution/{report_id}/",
        intent="chart_attribution_contributions",
        view_type="chart",
        description="以百分比柱状图比较择时、资产选择、交互效应和总收益。",
        task_group="05 归因分析",
        sequence=120,
        fields=[_REPORT_ID_FIELD],
        view_model={
            "kind": "chart",
            "chart_type": "bar",
            "rows_path": "contributions",
            "columns": [
                {"key": "component", "label": "归因项"},
                {"key": "value_percent", "label": "收益贡献（%）"},
            ],
        },
    ),
    _action(
        key="audit.indicator-performance-list",
        label="指标表现",
        endpoint="/api/audit/tui/indicator-performance/",
        intent="list_indicator_performance",
        view_type="datagrid",
        description="查看最近验证批次的 F1、稳定性、领先期与建议动作。",
        task_group="06 指标表现",
        sequence=130,
        fields=[],
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "total_path": "total_count",
            "columns": [
                {"key": "indicator_code", "label": "指标"},
                {"key": "indicator_name", "label": "名称"},
                {"key": "category", "label": "类别"},
                {"key": "f1_percent", "label": "F1（%）"},
                {"key": "stability_percent", "label": "稳定性（%）"},
                {"key": "lead_time_mean", "label": "领先期（月）"},
                {"key": "recommended_action", "label": "建议"},
                {"key": "recommended_weight", "label": "建议权重"},
            ],
        },
    ),
    _action(
        key="audit.indicator-performance-chart",
        label="指标 F1 与稳定性图",
        endpoint="/api/audit/tui/indicator-performance/",
        intent="chart_indicator_performance",
        view_type="chart",
        description="比较各指标的 F1 与稳定性百分比。",
        task_group="06 指标表现",
        sequence=140,
        fields=[],
        view_model={
            "kind": "chart",
            "chart_type": "bar",
            "rows_path": "results",
            "columns": [
                {"key": "indicator_code", "label": "指标"},
                {"key": "f1_percent", "label": "F1（%）"},
                {"key": "stability_percent", "label": "稳定性（%）"},
            ],
        },
    ),
    _action(
        key="audit.indicator-performance-detail",
        label="单指标表现详情",
        endpoint="/api/audit/indicator-performance/{indicator_code}/",
        intent="inspect_indicator_performance_detail",
        view_type="detail",
        description="查看单个指标的最新混淆矩阵、领先期和建议。",
        task_group="06 指标表现",
        sequence=150,
        fields=[
            _field(
                "indicator_code",
                "指标代码",
                binding="path",
                required=True,
                maximum=50,
            )
        ],
        view_model={"kind": "detail"},
    ),
    _action(
        key="audit.threshold-list",
        label="指标阈值",
        endpoint="/api/audit/tui/thresholds/",
        intent="list_indicator_thresholds",
        view_type="datagrid",
        description="查看活动指标的当前阈值和最近验证状态。",
        task_group="07 阈值验证",
        sequence=160,
        fields=[],
        view_model={
            "kind": "datagrid",
            "rows_path": "results",
            "total_path": "total_count",
            "columns": [
                {"key": "indicator_code", "label": "指标"},
                {"key": "indicator_name", "label": "名称"},
                {"key": "category", "label": "类别"},
                {"key": "level_low", "label": "低阈值"},
                {"key": "level_high", "label": "高阈值"},
            ],
        },
    ),
    _action(
        key="audit.threshold-history-chart",
        label="阈值验证历史",
        endpoint="/api/audit/tui/thresholds/",
        intent="chart_threshold_validation_history",
        view_type="chart",
        description="按指标和日期查看最近 F1 与稳定性变化。",
        task_group="07 阈值验证",
        sequence=170,
        fields=[],
        view_model={
            "kind": "chart",
            "chart_type": "line",
            "rows_path": "history",
            "columns": [
                {"key": "observation", "label": "指标 · 日期"},
                {"key": "f1_percent", "label": "F1（%）"},
                {"key": "stability_percent", "label": "稳定性（%）"},
            ],
        },
    ),
    _action(
        key="audit.threshold-update-preview",
        label="预览阈值更新",
        endpoint="/api/audit/update-threshold/preview/",
        method="POST",
        intent="preview_indicator_threshold_update",
        view_type="detail",
        description="检查阈值顺序和现值，不写入配置。",
        task_group="07 阈值验证",
        sequence=180,
        fields=_THRESHOLD_FIELDS,
        view_model={"kind": "detail"},
        audience="admin",
    ),
    _action(
        key="audit.threshold-update",
        label="更新指标阈值",
        endpoint="/api/audit/update-threshold/",
        method="POST",
        intent="update_indicator_threshold",
        view_type="detail",
        description="确认后更新一个活动指标的上下阈值。",
        task_group="07 阈值验证",
        sequence=190,
        fields=_THRESHOLD_FIELDS,
        view_model={"kind": "detail"},
        audience="admin",
        effect="update",
        confirmation_required=True,
        audit_required=True,
    ),
    _action(
        key="audit.validation-preview",
        label="预览指标验证",
        endpoint="/api/audit/run-validation/preview/",
        method="POST",
        intent="preview_threshold_validation",
        view_type="detail",
        description="检查验证区间、目标和写入影响，不运行验证。",
        task_group="07 阈值验证",
        sequence=200,
        fields=_VALIDATION_FIELDS,
        view_model={"kind": "detail"},
        audience="admin",
    ),
    _action(
        key="audit.validation-run",
        label="运行指标验证",
        endpoint="/api/audit/run-validation/",
        method="POST",
        intent="run_threshold_validation",
        view_type="detail",
        description="确认后运行并持久化一轮指标阈值验证。",
        task_group="07 阈值验证",
        sequence=210,
        fields=_VALIDATION_FIELDS,
        view_model={"kind": "detail"},
        audience="admin",
        effect="create",
        confirmation_required=True,
        audit_required=True,
    ),
    _action(
        key="audit.validation-detail",
        label="验证批次详情",
        endpoint="/api/audit/threshold-validation-data/{summary_id}/",
        intent="inspect_threshold_validation_summary",
        view_type="detail",
        description="按摘要 ID 查看一次验证的完整结果。",
        task_group="07 阈值验证",
        sequence=220,
        fields=[
            _field(
                "summary_id",
                "摘要 ID",
                binding="path",
                input_type="number",
                value_type="integer",
                required=True,
                minimum=1,
            )
        ],
        view_model={"kind": "detail"},
    ),
)
