"""Runtime screen patches for research-oriented TUI surfaces."""

from __future__ import annotations

from typing import Any

RUNTIME_SCREEN_PATCHES_RESEARCH: dict[str, dict[str, Any]] = {
    "research.asset-lab": {
        "view_type": "detail",
        "dashboard_panels": [
            {
                "key": "asset-pool-summary",
                "title": "一、资产池概览",
                "kind": "detail",
                "action_key": "auto.api.get.api.asset-analysis.pool-summary",
                "max_rows": 6,
                "layout_area": "pool_summary",
                "target_screen": "research.asset-lab",
            },
            {
                "key": "asset-current-weight",
                "title": "二、当前资产权重",
                "kind": "detail",
                "action_key": "auto.api.get.api.asset-analysis.current-weight",
                "max_rows": 6,
                "layout_area": "current_weight",
                "target_screen": "research.asset-lab",
            },
            {
                "key": "asset-weight-configs",
                "title": "三、权重配置状态",
                "kind": "detail",
                "action_key": "auto.api.get.api.asset-analysis.weight-configs",
                "max_rows": 6,
                "layout_area": "weight_configs",
                "target_screen": "research.asset-lab",
            },
        ],
    },
    "research.alpha-triggers": {
        "default_action_key": "auto.api.get.api.alpha-triggers.candidates.actionable",
        "business_context": {
            "objective": "先看可操作候选，再核对活跃触发器和观察列表，判断今天应该推进哪些研究动作。",
            "decision_output": "Alpha " "触发结论：立即跟进、继续观察、等待触发或复核绩效。",
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
                "action_key": "auto.api.get.api.alpha-triggers.candidates.actionable",
                "max_rows": 8,
                "layout_area": "actionable",
                "target_screen": "research.alpha-triggers",
            },
            {
                "key": "alpha-triggers-active",
                "title": "二、活跃触发器",
                "kind": "datagrid",
                "action_key": "auto.api.get.api.alpha-triggers.triggers.active",
                "max_rows": 6,
                "layout_area": "triggers",
                "target_screen": "research.alpha-triggers",
            },
            {
                "key": "alpha-triggers-watch-list",
                "title": "三、观察列表",
                "kind": "datagrid",
                "action_key": "auto.api.get.api.alpha-triggers.candidates.watch-list",
                "max_rows": 6,
                "layout_area": "watch_list",
                "target_screen": "research.alpha-triggers",
            },
        ],
    },
}

RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS_RESEARCH: dict[str, set[str]] = {
    "research.alpha-triggers": {"auto.api.get.api.alpha-triggers"}
}
