"""Runtime TUI metadata injection constants for the CLI surface."""

from __future__ import annotations

from typing import Any

RUNTIME_CLI_GROUP: dict[str, Any] = {
    "key": "ops",
    "label": "AI 助手",
}

RUNTIME_CLI_MODULE: dict[str, Any] = {
    "key": "cli",
    "label": "AI 助手",
    "group": "ops",
    "summary": "从 TUI 直接进入命令行式 AI 交互、会话和授权指令入口。",
}

RUNTIME_CLI_SCREEN: dict[str, Any] = {
    "key": "cli.terminal",
    "label": "助手终端",
    "module_key": "cli",
    "group": "ops",
    "summary": "用命令行式输入发起自然语言任务，并查看流式回复与工具进度。",
    "view_type": "detail",
    "default_action_key": "cli.agent_chat",
    "business_context": {
        "objective": "在 TUI 内打开命令行式 AI 助手，发起自然语言任务。",
        "decision_output": "回复正文、工具进度和需要审批的下一步动作。",
        "checkpoints": [
            "先输入自然语言问题或任务。",
            "优先使用默认同步入口，前端专用场景再切到流式入口。",
            "涉及受控 MCP 工具时进入审批流程，不直接自动执行。",
        ],
    },
}

RUNTIME_CLI_CHAT_ACTION: dict[str, Any] = {
    "key": "cli.agent_chat",
    "label": "发送助手请求",
    "method": "POST",
    "endpoint": "/api/terminal/chat/",
    "intent": "run_cli_terminal_agent_request",
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
            "default": "总结当前系统状态，并列出我可以直接交给助手的任务。",
            "placeholder": "输入问题或任务",
            "value_type": "string",
        }
    ],
    "description": "在 TUI 内发起一次命令行式自然语言任务。",
    "source": "approved:runtime-cli-entry",
    "task_group": "01 助手交互",
    "sequence": 100,
    "task_tier": "operation",
}

RUNTIME_CLI_STREAM_ACTION: dict[str, Any] = {
    **RUNTIME_CLI_CHAT_ACTION,
    "key": "cli.agent_stream",
    "label": "流式助手请求",
    "endpoint": "/api/terminal/chat/stream/",
    "intent": "stream_cli_terminal_agent_request",
    "description": "在支持 SSE 的前端中流式消费命令行式自然语言任务。",
    "sequence": 110,
}
