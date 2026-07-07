"""Runtime screen patch metadata for operations-only TUI cleanup rules."""

from __future__ import annotations

from typing import Any

RUNTIME_SCREEN_PATCHES_OPS: dict[str, dict[str, Any]] = {
    "api-library.runtime": {
        "default_action_key": "operator.governance.runtime_summary",
        "workflow": {
            "name": "系统治理流程",
            "step": 1,
            "total": 6,
            "label": "运行时治理",
            "role": "先看 runtime、readiness 和 operator surface 摘要，再决定进入健康或任务明细。",
            "previous": {},
            "next": {"key": "api-library.data-center", "label": "数据治理"},
        },
        "business_context": {
            "objective": "从 runtime summary 开始判断当前系统是否适合继续投研和执行。",
            "decision_output": "运行时治理结论：readiness、系统面、任务面是否存在阻断。",
            "checkpoints": [
                "先看治理摘要，确认 runtime、readiness 和 operator surface 是否异常。",
                "再看系统健康、就绪检查和 Celery 健康。",
                "需要查具体任务时，再进入系统任务列表或统计。",
            ],
        },
        "dashboard_panels": [
            {
                "key": "runtime-governance-summary",
                "title": "一、Runtime / Readiness 异常",
                "kind": "datagrid",
                "action_key": "operator.governance.runtime_summary",
                "max_rows": 8,
                "layout_area": "governance_summary",
                "target_screen": "api-library.runtime",
                "columns": [
                    {"key": "severity", "label": "级别"},
                    {"key": "title", "label": "异常项"},
                    {"key": "status", "label": "状态"},
                    {"key": "blocking_reason", "label": "原因"},
                    {"key": "next_action", "label": "下一步"},
                ],
            },
            {
                "key": "runtime-health",
                "title": "二、系统健康",
                "kind": "detail",
                "action_key": "auto.api.get.api.health",
                "layout_area": "health",
                "target_screen": "api-library.runtime",
            },
            {
                "key": "runtime-ready",
                "title": "三、系统就绪检查",
                "kind": "detail",
                "action_key": "auto.api.get.api.ready",
                "layout_area": "readiness",
                "target_screen": "api-library.runtime",
            },
        ],
    },
    "ai-ops.providers": {
        "default_action_key": "operator.governance.ai_provider_summary",
        "workflow": {
            "name": "系统治理流程",
            "step": 3,
            "total": 6,
            "label": "AI 服务商治理",
            "role": "先看可用性、quota 和失败日志，再进入服务商或模型目录。",
            "previous": {"key": "api-library.data-center", "label": "数据治理"},
            "next": {"key": "ai-ops.agent-runtime", "label": "Agent 运行时治理"},
        },
        "business_context": {
            "objective": "先确认 AI 服务商、配额和失败日志是否支持当前 AI 辅助工作流。",
            "decision_output": "AI 服务商结论：可用、失败升高、配额受限或 MCP/能力目录不完整。",
            "checkpoints": [
                "先看治理摘要，确认当前阻断是否来自服务商、失败日志或配额。",
                "再看服务商和模型目录，确认当前可用路由。",
                "AI 不可用时，不把解释型 AI 结果当成唯一推进条件。",
            ],
        },
        "dashboard_panels": [
            {
                "key": "ai-provider-governance-summary",
                "title": "一、Provider / Quota / 失败异常",
                "kind": "datagrid",
                "action_key": "operator.governance.ai_provider_summary",
                "max_rows": 8,
                "layout_area": "governance_summary",
                "target_screen": "ai-ops.providers",
                "columns": [
                    {"key": "severity", "label": "级别"},
                    {"key": "title", "label": "异常项"},
                    {"key": "status", "label": "状态"},
                    {"key": "blocking_reason", "label": "原因"},
                    {"key": "next_action", "label": "下一步"},
                ],
            },
            {
                "key": "ai-provider-list",
                "title": "二、对话服务商",
                "kind": "datagrid",
                "action_key": "auto.api.get.api.prompt.chat.providers",
                "max_rows": 6,
                "layout_area": "providers",
                "target_screen": "ai-ops.providers",
            },
            {
                "key": "ai-provider-logs",
                "title": '三、最近 AI 日志',
                "kind": "datagrid",
                "action_key": "auto.api.get.api.ai.me.logs",
                "max_rows": 6,
                "layout_area": "logs",
                "target_screen": "ai-ops.providers",
            },
        ],
    },
    "ai-ops.agent-runtime": {
        "default_action_key": "operator.governance.agent_runtime_summary",
        "workflow": {
            "name": "系统治理流程",
            "step": 4,
            "total": 6,
            "label": "Agent 运行时治理",
            "role": "先看待处理与失败任务，再进入队列和时间线明细。",
            "previous": {"key": "ai-ops.providers", "label": "AI 服务商治理"},
            "next": {"key": "execution.account-settings", "label": "执行参数"},
        },
        "business_context": {
            "objective": "先确认待处理任务、失败任务和 runtime blockage，再决定进入任务、产物或时间线明细。",
            "decision_output": "Agent 运行时结论：队列正常、需人工处理、失败堆积或需要人工回收。",
            "checkpoints": [
                "先看治理摘要，确认待人工处理和失败任务数量。",
                "再看任务队列和需要关注任务。",
                "需要定位单任务时，再进入详情、产物或时间线。",
            ],
        },
        "dashboard_panels": [
            {
                "key": "agent-runtime-governance-summary",
                "title": "一、待处理 / 失败任务",
                "kind": "datagrid",
                "action_key": "operator.governance.agent_runtime_summary",
                "max_rows": 8,
                "layout_area": "governance_summary",
                "target_screen": "ai-ops.agent-runtime",
                "columns": [
                    {"key": "severity", "label": "级别"},
                    {"key": "title", "label": "异常项"},
                    {"key": "status", "label": "状态"},
                    {"key": "blocking_reason", "label": "原因"},
                    {"key": "next_action", "label": "下一步"},
                ],
            },
            {
                "key": "agent-runtime-needs-attention",
                "title": "二、需处理任务",
                "kind": "datagrid",
                "action_key": "agent_runtime.needs_attention",
                "max_rows": 6,
                "layout_area": "needs_attention",
                "target_screen": "ai-ops.agent-runtime",
            },
            {
                "key": "agent-runtime-tasks",
                "title": "三、任务队列",
                "kind": "datagrid",
                "action_key": "auto.api.get.api.agent-runtime.tasks",
                "max_rows": 8,
                "layout_area": "tasks",
                "target_screen": "ai-ops.agent-runtime",
            },
        ],
    },
    "api-library.config-center": {
        "default_action_key": "operator.governance.config_center_summary",
        "workflow": {
            "name": "系统治理流程",
            "step": 6,
            "total": 6,
            "label": "配置中心治理",
            "role": "在治理流末端承接训练与 runtime 配置异常。",
            "previous": {"key": "execution.account-settings", "label": "执行参数"},
            "next": {},
        },
        "business_context": {
            "objective": "先看 Qlib runtime、训练记录和本地数据异常，再进入配置修改或训练动作。",
            "decision_output": "配置中心结论：Qlib runtime 是否可用、训练是否有记录、本地数据是否滞后。",
            "checkpoints": [
                "先看治理摘要，确认是否存在 runtime、模型或训练记录异常。",
                "再看 Qlib 运行配置和训练记录。",
                "所有写操作继续走确认和管理员权限约束。",
            ],
        },
        "dashboard_panels": [
            {
                "key": "config-center-governance-summary",
                "title": "一、Qlib / 训练异常",
                "kind": "datagrid",
                "action_key": "operator.governance.config_center_summary",
                "max_rows": 8,
                "layout_area": "governance_summary",
                "target_screen": "api-library.config-center",
                "columns": [
                    {"key": "severity", "label": "级别"},
                    {"key": "title", "label": "异常项"},
                    {"key": "status", "label": "状态"},
                    {"key": "blocking_reason", "label": "原因"},
                    {"key": "next_action", "label": "下一步"},
                ],
            },
            {
                "key": "config-center-runtime",
                "title": "二、Qlib 运行配置",
                "kind": "detail",
                "action_key": "config_center.qlib_runtime",
                "layout_area": "runtime",
                "target_screen": "api-library.config-center",
            },
            {
                "key": "config-center-training-runs",
                "title": "三、训练运行记录",
                "kind": "datagrid",
                "action_key": "config_center.training_runs",
                "max_rows": 6,
                "layout_area": "training_runs",
                "target_screen": "api-library.config-center",
            },
        ],
        "view_type": "detail",
    },
}

RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS_OPS: dict[str, set[str]] = {
    "ai-ops.capabilities": {"param.api.get.api.ai-capability.capabilities.pk"}
}
