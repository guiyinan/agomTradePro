"""
Terminal Application Services.

命令执行服务实现。通过 AgentRuntime 提供基于系统数据的 AI 问答能力。
"""

import json
import logging
import re
from typing import Any

from django.urls import Resolver404, resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.ai_provider.application.client_provider import get_ai_client_factory
from apps.prompt.application.runtime_provider import build_terminal_agent_runtime
from apps.terminal.application.repository_provider import (
    TerminalApiRequestError,
    get_terminal_auth_user,
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
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """
        执行API类型命令

        Returns:
            dict with 'output' and 'metadata' keys
        """
        # 替换URL中的参数占位符
        url = command.api_endpoint or ""
        for key, value in params.items():
            placeholder = f"{{{key}}}"
            url = url.replace(placeholder, str(value))

        # 构建请求参数
        request_params = {}
        for key, value in params.items():
            if f"{{{key}}}" not in (command.api_endpoint or ""):
                request_params[key] = value

        if url.startswith("/"):
            return self._execute_internal_api_command(
                command=command,
                url=url,
                request_params=request_params,
                user_id=user_id,
            )

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

        output = self._filter_and_format_api_output(
            command=command,
            data=data,
            params=params,
        )

        return {
            "output": output,
            "metadata": {
                "api_endpoint": command.api_endpoint,
                "api_method": command.api_method,
                "status_code": status_code,
            },
        }

    def _execute_internal_api_command(
        self,
        *,
        command: TerminalCommand,
        url: str,
        request_params: dict[str, Any],
        user_id: int | None,
    ) -> dict[str, Any]:
        """Execute a relative API endpoint inside Django without external HTTP."""

        method = (command.api_method or "GET").upper()
        factory = APIRequestFactory()
        request_builder = getattr(factory, method.lower())
        request = request_builder(
            url,
            request_params,
            format="json",
        )
        if user_id:
            user = get_terminal_auth_user(user_id)
            if user is not None:
                force_authenticate(request, user=user)

        try:
            match = resolve(url)
        except Resolver404:
            return {
                "output": f"Internal API path not found: {url}",
                "metadata": {
                    "api_endpoint": command.api_endpoint,
                    "api_method": method,
                    "status_code": 404,
                },
            }

        response = match.func(request, **match.kwargs)
        if hasattr(response, "render"):
            response.render()
        payload = getattr(response, "data", None)
        if payload is None:
            payload = response.content.decode("utf-8")
        output = self._filter_and_format_api_output(
            command=command,
            data=payload,
            params=request_params,
        )
        return {
            "output": output,
            "metadata": {
                "api_endpoint": command.api_endpoint,
                "api_method": method,
                "status_code": getattr(response, "status_code", 200),
                "internal_dispatch": True,
            },
        }

    def _filter_and_format_api_output(
        self,
        *,
        command: TerminalCommand,
        data: Any,
        params: dict[str, Any] | None = None,
    ) -> str:
        """Apply optional filters and render a terminal-friendly output string."""

        output = data
        if command.response_jq_filter:
            try:
                output = self._apply_jq_filter(data, command.response_jq_filter)
            except Exception as e:
                logger.warning(f"JQ filter failed: {e}, returning raw data")

        if (
            command.name == "market_temperature"
            and isinstance(output, dict)
            and not bool((params or {}).get("verbose", False))
        ):
            return self._format_market_temperature_output(output)
        if (
            command.name == "advisor_today"
            and isinstance(output, dict)
            and not bool((params or {}).get("verbose", False))
        ):
            return self._format_advisor_today_output(output)

        if isinstance(output, (dict, list)):
            return json.dumps(output, indent=2, ensure_ascii=False)
        return str(output)

    @staticmethod
    def _format_market_temperature_output(payload: dict[str, Any]) -> str:
        """Render a compact textual summary for the market thermometer command."""

        reasons = list(payload.get("trigger_reasons") or [])[:3]
        reason_text = "；".join(reasons) if reasons else "暂无明显升温原因。"
        threshold_source = (
            "个人阈值"
            if str(payload.get("threshold_source") or "") == "user_override"
            else "系统阈值"
        )
        effective_band = str(payload.get("effective_band") or payload.get("band") or "cold")
        avoid_chasing = "是" if effective_band in {"hot", "overheat", "extreme"} else "否"
        degraded = bool(payload.get("must_not_use_for_decision", False))
        lines = [
            f"市场温度分数: {float(payload.get('score', 0.0) or 0.0):.1f}",
            f"温度分段: {effective_band}",
            f"阈值来源: {threshold_source}",
            f"5日变化: {payload.get('change_5d')}",
            f"20日变化: {payload.get('change_20d')}",
            f"主要升温原因: {reason_text}",
            f"是否建议避免追高: {avoid_chasing}",
        ]
        if degraded:
            lines.append(
                f"数据完整性提示: 数据不完整，当前仅供参考。{payload.get('blocked_reason', '')}".strip()
            )
        return "\n".join(lines)

    @staticmethod
    def _format_advisor_today_output(payload: dict[str, Any]) -> str:
        """Render a compact textual summary for the account advisor command."""

        data = payload.get("data") if payload.get("success") is True else payload
        if not isinstance(data, dict):
            return json.dumps(payload, indent=2, ensure_ascii=False)

        account = data.get("account") or {}
        summary = data.get("order_summary") or {}
        risk_policy = data.get("risk_policy") or {}
        data_health = data.get("data_health") or {}
        execution_plan = data.get("execution_plan") or {}
        orders = list(data.get("order_intents") or [])[:5]
        blockers = list(data.get("blockers") or [])[:5]
        next_actions = list(data.get("next_actions") or [])[:5]
        account_name = account.get("account_name") or account.get("account_id") or "-"
        account_type = account.get("account_type_label") or account.get("account_type") or "账户"
        lines = [
            f"账户: {account_name} ({account_type})",
            f"总资产: {account.get('total_asset')}  可用资金: {account.get('available_cash')}",
            f"当前持仓数: {account.get('holding_count')}  基线: {data.get('baseline')}",
            f"今日结论: {data.get('today_conclusion')}",
            f"风险配置: {risk_policy.get('version') or '-'}  数据健康: {data_health.get('status') or '-'}",
            (
                "执行计划: "
                f"{execution_plan.get('execution_mode') or '-'} "
                f"确认={execution_plan.get('confirmation_status') or '-'} "
                f"自动下单={'是' if execution_plan.get('broker_execution_enabled') else '否'}"
            ),
            (
                "建议订单: "
                f"共 {summary.get('total', 0)} 单，"
                f"买入 {summary.get('buy', 0)}，"
                f"加仓 {summary.get('add', 0)}，"
                f"减仓 {summary.get('reduce', 0)}，"
                f"清仓 {summary.get('exit', 0)}，"
                f"阻断 {summary.get('blocked', 0)}"
            ),
        ]
        if orders:
            lines.append("前 5 条订单意图:")
            for order in orders:
                price_band = order.get("price_band") or {}
                data_asof = order.get("data_asof") or {}
                confirmation = order.get("confirmation") or {}
                lines.append(
                    "- "
                    f"{order.get('side')} {order.get('asset_code')} "
                    f"{order.get('asset_name')} "
                    f"delta={order.get('delta_quantity')} "
                    f"amount={order.get('estimated_amount')} "
                    f"price={price_band.get('label') or order.get('estimated_price')} "
                    f"status={order.get('blocking_status')} "
                    f"risk_gate={order.get('risk_gate_status') or '-'} "
                    f"asof={data_asof.get('quote_freshness_status') or '-'} "
                    f"confirm={confirmation.get('status') or '-'}"
                )
        else:
            lines.append("前 5 条订单意图: 暂无")

        if blockers:
            lines.append("阻断项:")
            for blocker in blockers:
                lines.append(
                    f"- {blocker.get('asset_code') or '-'} {blocker.get('type')}: {blocker.get('message')}"
                )
        if next_actions:
            lines.append("下一步命令:")
            for action in next_actions:
                lines.append(f"- {action.get('label')}: {action.get('hint')}")
        return "\n".join(lines)

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
