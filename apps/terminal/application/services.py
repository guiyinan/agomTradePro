"""
Terminal Application Services.

命令执行服务实现。通过 AgentRuntime 提供基于系统数据的 AI 问答能力。
"""

import json
import logging
import re
from typing import Any

from apps.ai_provider.application.client_provider import get_ai_client_factory
from apps.prompt.application.runtime_provider import build_terminal_agent_runtime
from apps.terminal.application.repository_provider import (
    TerminalApiRequestError,
    get_terminal_command_http_client,
    get_terminal_runtime_settings_repository,
)

from ..domain.entities import TerminalCommand

logger = logging.getLogger(__name__)


# Terminal 默认允许的上下文域和工具
_DEFAULT_CONTEXT_SCOPE = ["macro", "regime"]
_DEFAULT_TOOL_NAMES = [
    "get_macro_summary",
    "get_macro_indicator",
    "get_regime_status",
    "get_regime_distribution",
]


class CommandExecutionService:
    """命令执行服务"""

    def __init__(self):
        self._ai_client_factory = None
        self._agent_runtime = None

    @property
    def ai_client_factory(self):
        """延迟加载AI客户端工厂"""
        if self._ai_client_factory is None:
            self._ai_client_factory = get_ai_client_factory()
        return self._ai_client_factory

    def _get_agent_runtime(self):
        """延迟构建 AgentRuntime 实例。"""
        if self._agent_runtime is not None:
            return self._agent_runtime

        self._agent_runtime = build_terminal_agent_runtime(self.ai_client_factory)
        return self._agent_runtime

    def execute_prompt_command(
        self,
        command: TerminalCommand,
        params: dict[str, Any],
        session_id: str | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        """
        执行Prompt类型命令 - 通过 AgentRuntime 执行。

        支持系统数据注入和工具调用，AI 可以按需查询宏观、Regime 等数据。

        Returns:
            dict with 'output' and 'metadata' keys
        """
        from apps.prompt.domain.agent_entities import AgentExecutionRequest

        # 构建用户提示
        user_prompt = command.user_prompt_template
        for key, value in params.items():
            placeholder = f"{{{key}}}"
            user_prompt = user_prompt.replace(placeholder, str(value))

        # 通过 AgentRuntime 执行
        runtime = self._get_agent_runtime()

        agent_request = AgentExecutionRequest(
            task_type="terminal",
            user_input=user_prompt,
            provider_ref=provider_name,
            model=model_name,
            system_prompt=command.system_prompt,
            context_scope=_DEFAULT_CONTEXT_SCOPE,
            tool_names=_DEFAULT_TOOL_NAMES,
            max_rounds=4,
            session_id=session_id,
        )

        response = runtime.execute(agent_request)

        # 构建 trace 摘要
        trace_summary = {}
        if response.tool_calls:
            trace_summary["tools_used"] = [tc.tool_name for tc in response.tool_calls]
        if response.used_context:
            trace_summary["context_domains"] = response.used_context
        trace_summary["turn_count"] = response.turn_count

        return {
            "output": response.final_answer or response.error_message or "",
            "metadata": {
                "provider": response.provider_used or provider_name or "default",
                "model": response.model_used or model_name or "default",
                "tokens": response.total_tokens,
                "session_id": session_id,
                "execution_id": response.execution_id,
                "trace": trace_summary,
            },
        }

    def execute_api_command(
        self,
        command: TerminalCommand,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        执行API类型命令

        Returns:
            dict with 'output' and 'metadata' keys
        """
        # 替换URL中的参数占位符
        url = command.api_endpoint
        for key, value in params.items():
            placeholder = f"{{{key}}}"
            url = url.replace(placeholder, str(value))

        # 构建请求参数
        request_params = {}
        for key, value in params.items():
            if f"{{{key}}}" not in command.api_endpoint:
                request_params[key] = value

        try:
            status_code, data = get_terminal_command_http_client().request_json(
                method=command.api_method,
                url=url,
                params=request_params,
                timeout=command.timeout,
            )
        except TerminalApiRequestError as e:
            logger.error(f"API request failed: {e}")
            return {"output": f"API request failed: {e}", "metadata": {"error": str(e)}}

        # 应用JQ过滤
        output = data
        if command.response_jq_filter:
            try:
                output = self._apply_jq_filter(data, command.response_jq_filter)
            except Exception as e:
                logger.warning(f"JQ filter failed: {e}, returning raw data")

        # 格式化输出
        if isinstance(output, (dict, list)):
            output_str = json.dumps(output, indent=2, ensure_ascii=False)
        else:
            output_str = str(output)

        return {
            "output": output_str,
            "metadata": {
                "api_endpoint": command.api_endpoint,
                "api_method": command.api_method,
                "status_code": status_code,
            },
        }

    def _apply_jq_filter(self, data: Any, filter_expr: str) -> Any:
        """
        应用简单的JQ-like过滤器

        支持基本的路径访问: .key, .key[0], .key.subkey
        """
        # 简化实现，支持基本的点语法路径
        if not filter_expr.startswith("."):
            return data

        path = filter_expr[1:].split(".")
        result = data

        for part in path:
            if not part:
                continue

            # 处理数组索引: key[0]
            match = re.match(r"(\w+)\[(\d+)\]", part)
            if match:
                key, index = match.groups()
                result = result[key][int(index)]
            elif part.isdigit():
                result = result[int(part)]
            elif isinstance(result, dict):
                result = result.get(part)
            else:
                return None

        return result


class AnswerChainSettingsService:
    """Read terminal answer-chain settings without coupling interface to ORM imports."""

    @staticmethod
    def get_config(user) -> dict[str, Any]:
        settings_data = get_terminal_runtime_settings_repository().get_settings()
        is_admin = bool(user and (user.is_staff or user.is_superuser))
        return {
            "enabled": settings_data["answer_chain_enabled"],
            "visibility": "technical" if is_admin else "masked",
            "is_admin": is_admin,
        }


class ChatScopeSettingsService:
    """Read shared fallback chat scope settings from terminal runtime settings."""

    DEFAULT_FALLBACK_CHAT_SYSTEM_PROMPT = (
        "You are the AgomTradePro system assistant for an investment decision platform. "
        "Prioritize answers within AgomTradePro operational context, including system status, "
        "macro environment, market regime, policy level, portfolio, positions, signals, "
        "backtest, audit, AI provider configuration, terminal commands, RSS ingestion, "
        "policy news, hotspot events, and other system modules already present in the platform. "
        "If the user asks an ambiguous question such as recommendations, interpret it in this platform context first. "
        "Do not drift into unrelated lifestyle topics like fitness, travel, entertainment, or generic life coaching. "
        "If the request is underspecified, ask a short clarifying question tied to the platform context, "
        "or provide the most relevant system-oriented answer."
    )

    @staticmethod
    def get_fallback_chat_system_prompt() -> str:
        settings_data = get_terminal_runtime_settings_repository().get_settings()
        custom_prompt = settings_data["fallback_chat_system_prompt"].strip()
        return custom_prompt or ChatScopeSettingsService.DEFAULT_FALLBACK_CHAT_SYSTEM_PROMPT
