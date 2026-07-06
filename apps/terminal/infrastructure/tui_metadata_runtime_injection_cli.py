"""Runtime TUI metadata injection constants for the CLI surface."""

from __future__ import annotations

from typing import Any


RUNTIME_CLI_GROUP: dict[str, Any] = {
    "key": "ops",
    "label": "AI 助手",
}

RUNTIME_CLI_MODULE: dict[str, Any] = {
    "key": "cli",
    "label": "CLI",
    "group": "ops",
    "summary": "从 TUI 直接进入命令行式 AI 交互、会话和授权指令入口。",
}

RUNTIME_CLI_SCREEN: dict[str, Any] = {
    "key": "cli.terminal",
    "label": "CLI 终端",
    "module_key": "cli",
    "group": "ops",
    "summary": "用命令行式输入询问系统状态、触发授权指令或创建终端会话。",
    "view_type": "detail",
    "default_action_key": "cli.chat_router",
    "business_context": {
        "objective": "在 TUI 内打开 CLI 交互入口，执行已授权的终端任务。",
        "decision_output": "CLI 问答结果、路由建议和需要确认的后续动作。",
        "checkpoints": [
            "先输入自然语言问题或任务。",
            "涉及写入或高风险动作时按确认流程执行。",
            "需要查看指令权限时切换到 AI 能力或终端权限任务。",
        ],
    },
}

RUNTIME_CLI_CHAT_ACTION: dict[str, Any] = {
    "key": "cli.chat_router",
    "label": "打开 CLI 交互",
    "method": "POST",
    "endpoint": "/api/terminal/chat/",
    "intent": "route_cli_natural_language_task",
    "screen_key": "cli.terminal",
    "module_key": "cli",
    "view_type": "detail",
    "risk": "ai",
    "fields": [
        {
            "key": "message",
            "label": "消息",
            "input_type": "textarea",
            "required": True,
            "default": "总结当前系统状态，并列出我可以执行的 CLI 指令。",
            "placeholder": "输入 CLI 问题或任务",
            "value_type": "string",
        }
    ],
    "description": "在 TUI 内打开 CLI 风格 AI 交互入口。",
    "source": "approved:runtime-cli-entry",
    "task_group": "01 CLI 交互",
    "sequence": 100,
    "task_tier": "operation",
}
