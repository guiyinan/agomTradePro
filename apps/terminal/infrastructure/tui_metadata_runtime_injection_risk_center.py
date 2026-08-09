"""Runtime TUI metadata injection constants for risk-center surfaces."""

from __future__ import annotations

from typing import Any

from .tui_metadata_runtime_injection_risk_center_actions_core import (
    RUNTIME_RISK_CENTER_CORE_ACTIONS,
)
from .tui_metadata_runtime_injection_risk_center_actions_governance import (
    RUNTIME_RISK_CENTER_GOVERNANCE_ACTIONS,
)

RUNTIME_RISK_CENTER_MODULE: dict[str, Any] = {
    "key": "risk-center",
    "label": "风控中心",
    "group": "workflow",
    "summary": "集中查看全局底线、账户策略、有效策略和管理员例外。",
}

RUNTIME_RISK_CENTER_SCREEN: dict[str, Any] = {
    "key": "risk-center.overview",
    "label": "集中风控中心",
    "module_key": "risk-center",
    "group": "workflow",
    "summary": "查看当前情景、数据健康和组合影响，并通过预览与人工确认治理情景版本。",
    "view_type": "detail",
    "dashboard_layout": "task_flow",
    "default_action_key": "risk-center.active-scenario-set",
    "entry_mode": "direct",
    "entry_empty_copy": "当前没有已激活的情景集；管理员可先创建草稿并完成预览和审批。",
    "entry_help_steps": [
        "先查看当前生效情景集和五维市场证据。",
        "选择组合快照并预览各情景影响。",
        "需要调整时先生成差异预览，再交由有权限的人类确认。",
    ],
    "business_context": {
        "objective": "查看并调整未来情景，预览对组合的影响。",
        "decision_output": "情景版本、主情景概率、证据新鲜度、组合影响和明确阻断原因。",
        "checkpoints": [
            "先确认情景版本、证据时间和数据健康。",
            "组合影响必须引用不可变快照和 Allocation Policy 版本。",
            "激活和回滚只允许人类管理员在持久审批后执行。",
        ],
    },
    "user_experience": {
        "journey": "workspace",
        "primary_task": "查看并调整未来情景，预览对组合的影响。",
        "primary_outcome": "形成引用确定情景版本、组合快照和数据证据的可复核预览。",
        "empty_state_hint": "尚无已激活情景集时，先创建草稿并完成影响预览。",
        "next_step_hint": "确认数据健康和组合影响后，再由有权限的人类审批并激活。",
    },
    "dashboard_panels": [
        {
            "key": "active-scenario-set",
            "title": "当前生效情景集",
            "kind": "detail",
            "action_key": "risk-center.active-scenario-set",
            "layout_area": "active_scenarios",
            "target_screen": "risk-center.overview",
            "empty_message": "当前没有已激活情景集，决策入口保持阻断。",
            "error_message": "情景集读取失败，不能用于决策。",
            "stale_message": "情景证据已过期，请复核后再使用。",
            "user_priority": "p0",
            "presentation_semantic": "primary_status",
        },
        {
            "key": "scenario-impact",
            "title": "组合影响预览",
            "kind": "detail",
            "action_key": "risk-center.scenario-impact-preview",
            "layout_area": "portfolio_impact",
            "target_screen": "risk-center.overview",
            "empty_message": "选择情景集版本和组合快照后生成影响预览。",
            "error_message": "组合影响预览失败，不能用于决策。",
            "stale_message": "组合或数据证据已变化，请重新预览。",
            "user_priority": "p0",
            "presentation_semantic": "primary_status",
        },
        {
            "key": "market-state-evidence",
            "title": "五维市场状态与数据健康",
            "kind": "detail",
            "action_key": "risk-center.market-state",
            "layout_area": "market_evidence",
            "target_screen": "risk-center.overview",
            "empty_message": "暂无完整五维证据；缺失项不会按中性值处理。",
            "error_message": "市场证据读取失败，情景调整入口保持阻断。",
            "stale_message": "部分市场证据已过期，请先刷新数据。",
            "user_priority": "p0",
            "presentation_semantic": "primary_status",
        },
        {
            "key": "scenario-catalog",
            "title": "情景版本目录",
            "kind": "datagrid",
            "action_key": "risk-center.scenario-list",
            "layout_area": "scenario_catalog",
            "target_screen": "risk-center.overview",
            "empty_message": "暂无情景定义。",
            "user_priority": "p1",
            "presentation_semantic": "supporting_list",
        },
    ],
}

RUNTIME_RISK_CENTER_ACTIONS: tuple[dict[str, Any], ...] = (
    RUNTIME_RISK_CENTER_CORE_ACTIONS + RUNTIME_RISK_CENTER_GOVERNANCE_ACTIONS
)
