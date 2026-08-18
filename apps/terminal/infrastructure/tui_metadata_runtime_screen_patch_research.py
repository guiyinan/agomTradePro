"""Runtime screen patches for research-oriented TUI surfaces."""

from __future__ import annotations

from typing import Any

RUNTIME_SCREEN_PATCHES_RESEARCH: dict[str, dict[str, Any]] = {
    "research.asset-lab": {
        "view_type": "detail",
        "default_action_key": "auto.api.get.api.asset-analysis.pool-summary",
        "user_experience": {
            "journey": "dashboard",
            "primary_task": "先看资产池和当前权重结论，再决定是否继续调整权重配置。",
            "primary_outcome": "明确当前资产池结构、当前权重状态，以及权重配置是否需要继续复核。",
            "empty_state_hint": "先看资产池概览，再看当前资产权重和权重配置状态。",
            "next_step_hint": "若资产池或权重状态异常，继续进入基金、板块和筛选器研究补证据。",
        },
        "business_context": {
            "objective": "先读资产池和当前权重，再决定今天研究应围绕哪些资产和配置问题展开。",
            "decision_output": "资产研究结论：当前资产池结构、配置倾向，以及是否需要进一步复核权重规则。",
            "checkpoints": [
                "先看资产池概览，确认当前可研究对象和结构分布。",
                "再看当前资产权重，确认配置是否偏离预期。",
                "最后看权重配置状态，确认规则层是否需要调整或继续复核。",
            ],
        },
        "dashboard_panels": [
            {
                "key": "asset-pool-summary",
                "title": "一、资产池概览",
                "kind": "detail",
                "action_key": "auto.api.get.api.asset-analysis.pool-summary",
                "max_rows": 6,
                "layout_area": "pool_summary",
                "target_screen": "research.asset-lab",
                "user_priority": "p0",
                "presentation_semantic": "primary_status",
            },
            {
                "key": "asset-current-weight",
                "title": "二、当前资产权重",
                "kind": "detail",
                "action_key": "auto.api.get.api.asset-analysis.current-weight",
                "max_rows": 6,
                "layout_area": "current_weight",
                "target_screen": "research.asset-lab",
                "user_priority": "p1",
                "presentation_semantic": "supporting_detail",
            },
            {
                "key": "asset-weight-configs",
                "title": "三、权重配置状态",
                "kind": "detail",
                "action_key": "auto.api.get.api.asset-analysis.weight-configs",
                "max_rows": 6,
                "layout_area": "weight_configs",
                "target_screen": "research.asset-lab",
                "user_priority": "p2",
                "presentation_semantic": "supporting_detail",
            },
        ],
    },
    "research.alpha-triggers": {
        "default_action_key": "alpha-trigger.candidate-actionable",
        "user_experience": {
            "journey": "dashboard",
            "primary_task": "先筛出今天最值得推进的候选，再决定继续跟进活跃触发器还是观察列表。",
            "primary_outcome": "明确今天应优先推进的候选，以及哪些触发器仍在延续或需要继续观察。",
            "empty_state_hint": "先看可操作候选，再核对活跃触发器和观察列表。",
            "next_step_hint": "若存在高优先级候选，继续进入标的研究、绩效复核或执行前检查。",
        },
        "business_context": {
            "objective": "先看可操作候选，再核对活跃触发器和观察列表，判断今天应该推进哪些研究动作。",
            "decision_output": "Alpha 触发结论：立即跟进、继续观察、等待触发或复核绩效。",
            "checkpoints": [
                "先看可操作候选，确认今天最值得推进的标的。",
                "再看活跃触发器和观察列表，确认触发背景是否延续。",
                "需要复核历史效果时再看触发器绩效。",
            ],
        },
        "dashboard_panels": [
            {
                "key": "alpha-triggers-actionable",
                "title": "一、可操作候选",
                "kind": "datagrid",
                "action_key": "alpha-trigger.candidate-actionable",
                "max_rows": 8,
                "layout_area": "actionable",
                "target_screen": "research.alpha-triggers",
                "user_priority": "p0",
                "presentation_semantic": "primary_list",
            },
            {
                "key": "alpha-triggers-active",
                "title": "二、活跃触发器",
                "kind": "datagrid",
                "action_key": "alpha-trigger.trigger-active",
                "max_rows": 6,
                "layout_area": "triggers",
                "target_screen": "research.alpha-triggers",
                "user_priority": "p1",
                "presentation_semantic": "supporting_list",
            },
            {
                "key": "alpha-triggers-watch-list",
                "title": "三、观察列表",
                "kind": "datagrid",
                "action_key": "alpha-trigger.candidate-watch-list",
                "max_rows": 6,
                "layout_area": "watch_list",
                "target_screen": "research.alpha-triggers",
                "user_priority": "p2",
                "presentation_semantic": "supporting_list",
            },
        ],
    },
}

RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS_RESEARCH: dict[str, set[str]] = {
    "research.alpha-triggers": {"auto.api.get.api.alpha-triggers"},
    "research.signals": {
        "auto.api.get.api.filter",
        "auto.api.get.api.filter.indicators",
        "auto.api.get.api.filter.health",
        "param.api.get.api.filter.config.indicator_code",
        "param.api.get.api.filter.config.str.indicator_code",
    },
}
