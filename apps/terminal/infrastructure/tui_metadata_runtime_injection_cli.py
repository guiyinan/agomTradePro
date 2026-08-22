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
    "description": (
        "向服务器端 Agent Runtime 提交一次命令行式自然语言任务；" "用户端不安装或运行 Agent。"
    ),
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
    "description": (
        "向服务器端 Agent Runtime 提交任务，并在支持 SSE 的前端中流式消费结果；"
        "用户端不安装或运行 Agent。"
    ),
    "sequence": 110,
}

RUNTIME_CLI_QUEUED_ACTION: dict[str, Any] = {
    "key": "cli.agent_queue",
    "label": "排队执行助手任务",
    "method": "POST",
    "endpoint": "/api/terminal/runs/",
    "intent": "queue_server_side_terminal_agent_request",
    "screen_key": "cli.terminal",
    "module_key": "cli",
    "view_type": "detail",
    "risk": "ai",
    "effect": "create",
    "audit_required": True,
    "fields": [
        {
            "key": "task_id",
            "label": "已有任务 ID",
            "input_type": "number",
            "required": True,
            "value_type": "integer",
            "min": 1,
            "presentation_semantic": "primary_selector",
            "placeholder": "输入当前账号已有的 Agent 任务 ID",
        },
        {
            "key": "message",
            "label": "任务说明",
            "input_type": "textarea",
            "required": True,
            "value_type": "string",
            "presentation_semantic": "prompt_text",
            "placeholder": "描述希望服务器端助手完成的任务",
        },
    ],
    "description": (
        "把已有任务提交到服务器端排队运行；浏览器只提交请求并读取状态/事件，"
        "不会在本地安装或运行 Agent。"
    ),
    "source": "approved:runtime-cli-queued-entry",
    "task_group": "01 助手交互",
    "sequence": 120,
    "task_tier": "operation",
    "result_semantics": ["primary_status"],
}
