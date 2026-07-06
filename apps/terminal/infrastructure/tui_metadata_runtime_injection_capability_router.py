"""Runtime TUI metadata injection constants for capability routing."""

from __future__ import annotations

from typing import Any


RUNTIME_CAPABILITY_ROUTER_MODULE: dict[str, Any] = {
    "key": "capability-router",
    "label": "能力路由",
    "group": "ops",
    "summary": "统一接入 AI Capability Catalog、路由 API、MCP 工具和内部能力。",
}

RUNTIME_CAPABILITY_ROUTER_SCREEN: dict[str, Any] = {
    "key": "capability-router.gateway",
    "label": "能力路由接入",
    "module_key": "capability-router",
    "group": "ops",
    "summary": "验证自然语言请求如何通过统一路由层选择能力，并检查目录覆盖状态。",
    "view_type": "detail",
    "default_action_key": "capability-router.route-message",
    "business_context": {
        "objective": "把 AI/TUI/Terminal 请求先送入统一路由层，再由后端选择 MCP、Terminal、内置能力或内部 API。",
        "decision_output": "路由结果、候选能力、是否需要确认、缺失参数和回答链摘要。",
        "checkpoints": [
            "先运行目录统计，确认 MCP、Terminal、API 能力已同步。",
            "再用路由测试输入自然语言问题，观察 selected_capability_key 和 requires_confirmation。",
            "若能力未命中，回到 MCP 工具治理页打开 enabled_for_routing 或补充能力描述。",
        ],
    },
}

RUNTIME_CAPABILITY_ROUTER_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "capability-router.route-message",
        "label": "测试统一路由",
        "endpoint": "/api/ai-capability/route/",
        "method": "POST",
        "intent": "test_capability_router_entrypoint",
        "risk": "ai",
        "screen_key": "capability-router.gateway",
        "module_key": "capability-router",
        "view_type": "detail",
        "description": "输入自然语言，由 Capability Router 返回候选能力、选中能力、确认状态和回复。",
        "source": "approved:runtime-capability-router",
        "task_group": "01 路由验证",
        "sequence": 100,
        "task_tier": "primary",
        "fields": [
            {
                "key": "message",
                "label": "消息",
                "input_type": "textarea",
                "required": True,
                "default": "现在系统状态如何？",
                "placeholder": "输入希望 AI 执行或查询的任务",
                "binding": "body",
                "value_type": "string",
            },
            {
                "key": "entrypoint",
                "label": "入口",
                "input_type": "hidden",
                "required": True,
                "default": "tui",
                "binding": "body",
                "value_type": "string",
            },
            {
                "key": "context",
                "label": "上下文",
                "input_type": "textarea",
                "required": False,
                "default": '{"answer_chain_enabled": true, "params": {}}',
                "placeholder": '{"params": {}}',
                "binding": "body",
                "value_type": "object",
            },
        ],
        "view_model": {
            "kind": "detail",
            "title_path": "selected_capability_key",
            "status_path": "decision",
        },
    },
    {
        "key": "capability-router.catalog-stats",
        "label": "能力目录统计",
        "endpoint": "/api/ai-capability/stats/",
        "method": "GET",
        "intent": "inspect_capability_catalog_stats",
        "risk": "read",
        "screen_key": "capability-router.gateway",
        "module_key": "capability-router",
        "view_type": "detail",
        "description": "查看 Capability Catalog 总量、启用量、来源分布和路由组分布。",
        "source": "approved:runtime-capability-router",
        "task_group": "02 目录检查",
        "sequence": 110,
        "task_tier": "support",
        "view_model": {
            "kind": "detail",
            "title_path": "total",
            "status_path": "enabled",
        },
    },
    {
        "key": "capability-router.list-capabilities",
        "label": "能力列表",
        "endpoint": "/api/ai-capability/capabilities/",
        "method": "GET",
        "intent": "list_routable_capabilities",
        "risk": "read",
        "screen_key": "capability-router.gateway",
        "module_key": "capability-router",
        "view_type": "datagrid",
        "description": "按来源、分类或关键词查看当前进入能力目录的能力。",
        "source": "approved:runtime-capability-router",
        "task_group": "02 目录检查",
        "sequence": 120,
        "task_tier": "support",
        "fields": [
            {
                "key": "source_type",
                "label": "来源类型",
                "input_type": "select",
                "required": False,
                "default": "",
                "placeholder": "全部",
                "binding": "query",
                "value_type": "string",
                "options": ["", "builtin", "terminal_command", "mcp_tool", "api"],
            },
            {
                "key": "q",
                "label": "关键词",
                "input_type": "text",
                "required": False,
                "default": "",
                "placeholder": "搜索能力名称或说明",
                "binding": "query",
                "value_type": "string",
            },
        ],
        "view_model": {
            "kind": "datagrid",
            "rows_path": "",
        },
    },
)
