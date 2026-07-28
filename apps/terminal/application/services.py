"""
Terminal Application Services.

命令执行服务实现。通过 AgentRuntime 提供基于系统数据的 AI 问答能力。
"""

import json
import logging
import math
import re
from collections.abc import Mapping
from typing import Any, Protocol, cast
from urllib.parse import quote, unquote, urlsplit

from django.urls import Resolver404, resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.ai_provider.application.chat_completion import AIClientFactoryProtocol
from apps.ai_provider.application.client_provider import get_ai_client_factory
from apps.prompt.application.agent_runtime import AgentRuntime
from apps.prompt.application.runtime_provider import build_terminal_agent_runtime
from apps.terminal.application.repository_provider import (
    TerminalApiRequestError,
    get_terminal_auth_user,
    get_terminal_command_http_client,
    get_terminal_runtime_settings_repository,
)
from apps.terminal.domain.exceptions import TerminalCommandExecutionError

from ..domain.entities import TerminalCommand

logger = logging.getLogger(__name__)

_ALLOWED_API_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_PARAMETER_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_MAX_API_PAYLOAD_BYTES = 1_048_576
_TERMINAL_RUNTIME_EXCEPTIONS = (
    ArithmeticError,
    AttributeError,
    ConnectionError,
    ImportError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


class TerminalSettingsUser(Protocol):
    """Authenticated user flags needed by Terminal settings services."""

    @property
    def is_staff(self) -> bool:
        """Return whether the user may access staff-only settings."""
        ...

    @property
    def is_superuser(self) -> bool:
        """Return whether the user has unrestricted settings access."""
        ...


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

    def __init__(self) -> None:
        self._ai_client_factory: AIClientFactoryProtocol | None = None
        self._agent_runtime: AgentRuntime | None = None

    @property
    def ai_client_factory(self) -> AIClientFactoryProtocol:
        """延迟加载AI客户端工厂"""
        if self._ai_client_factory is None:
            self._ai_client_factory = get_ai_client_factory()
        return self._ai_client_factory

    def _get_agent_runtime(self) -> AgentRuntime:
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
        if not response.success:
            logger.warning("Terminal prompt execution returned a failed response")
            raise TerminalCommandExecutionError("terminal_prompt_execution_failed")

        # 构建 trace 摘要
        trace_summary: dict[str, object] = {}
        if response.tool_calls:
            trace_summary["tools_used"] = [tc.tool_name for tc in response.tool_calls]
        if response.used_context:
            trace_summary["context_domains"] = response.used_context
        trace_summary["turn_count"] = response.turn_count

        return {
            "output": response.final_answer or "",
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
        method = _api_method(command.api_method)
        endpoint = _api_endpoint(command.api_endpoint)
        url = _substitute_endpoint_params(endpoint, params)
        request_params = _request_params(endpoint, params)
        timeout = _api_timeout(command.timeout)

        if url.startswith("/"):
            return self._execute_internal_api_command(
                command=command,
                url=url,
                request_params=request_params,
                user_id=user_id,
            )

        _validate_external_url(url)

        try:
            status_code, data = get_terminal_command_http_client().request_json(
                method=method,
                url=url,
                params=request_params,
                timeout=timeout,
            )
        except TerminalApiRequestError as exc:
            logger.warning(
                "Terminal external API request failed; exception_type=%s",
                type(exc).__name__,
            )
            raise TerminalCommandExecutionError("terminal_external_api_failed") from exc

        normalized_status = _http_status(status_code)
        if normalized_status >= 400:
            raise TerminalCommandExecutionError("terminal_external_api_failed")

        output = self._filter_and_format_api_output(
            command=command,
            data=data,
            params=params,
        )

        return {
            "output": output,
            "metadata": {
                "status_code": normalized_status,
                "structured_output": _detached_json_value(data),
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

        method = _api_method(command.api_method)
        _validate_internal_url(url)
        normalized_user_id = _positive_user_id(user_id)
        user = get_terminal_auth_user(normalized_user_id)
        if user is None:
            raise TerminalCommandExecutionError("terminal_internal_user_not_found")

        factory = APIRequestFactory()
        if method == "GET":
            request = factory.get(url, request_params, format="json")
        elif method == "POST":
            request = factory.post(url, request_params, format="json")
        elif method == "PUT":
            request = factory.put(url, request_params, format="json")
        elif method == "PATCH":
            request = factory.patch(url, request_params, format="json")
        else:
            request = factory.delete(url, request_params, format="json")
        force_authenticate(request, user=user)

        try:
            match = resolve(url)
        except Resolver404:
            raise TerminalCommandExecutionError("terminal_internal_api_not_found") from None

        response = match.func(request, **match.kwargs)
        if hasattr(response, "render"):
            response.render()
        status_code = _http_status(getattr(response, "status_code", None))
        if status_code >= 400:
            raise TerminalCommandExecutionError("terminal_internal_api_failed")
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
                "status_code": status_code,
                "internal_dispatch": True,
                "structured_output": _detached_json_value(payload),
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

        output = _detached_json_value(data)
        if command.response_jq_filter:
            try:
                output = self._apply_jq_filter(output, command.response_jq_filter)
            except _TERMINAL_RUNTIME_EXCEPTIONS as exc:
                logger.warning(
                    "Terminal output filter failed; exception_type=%s",
                    type(exc).__name__,
                )
                raise TerminalCommandExecutionError("terminal_output_filter_failed") from exc

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
        if (
            command.name == "advisor_query"
            and isinstance(output, dict)
            and not bool((params or {}).get("verbose", False))
        ):
            return self._format_advisor_query_output(output)

        if isinstance(output, dict | list):
            return json.dumps(
                output,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            )
        rendered = str(output)
        if len(rendered.encode("utf-8")) > _MAX_API_PAYLOAD_BYTES:
            raise TerminalCommandExecutionError("terminal_api_payload_too_large")
        return rendered

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
            f"数据时间: {payload.get('observed_at') or '-'}",
            f"阈值来源: {threshold_source}",
            f"5日变化: {payload.get('change_5d')}",
            f"20日变化: {payload.get('change_20d')}",
            f"主要升温原因: {reason_text}",
            f"是否建议避免追高: {avoid_chasing}",
            f"过热风险: {'是' if payload.get('overheating_risk') else '否'}",
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

    @staticmethod
    def _format_advisor_query_output(payload: dict[str, Any]) -> str:
        """Render a compact textual answer for the auto-advisor query command."""

        data = payload.get("data") if payload.get("success") is True else payload
        if not isinstance(data, dict):
            return json.dumps(payload, indent=2, ensure_ascii=False)

        account = data.get("account") or {}
        query = data.get("query") or {}
        answer = str(data.get("answer") or "")
        highlights = list(data.get("highlights") or [])[:5]
        evidence = data.get("evidence") or {}
        account_name = account.get("account_name") or account.get("account_id") or "-"
        lines = [
            f"账户: {account_name}",
            f"问题: {query.get('question') or '-'}",
            f"识别意图: {query.get('intent') or '-'}",
            f"回答: {answer or '-'}",
        ]
        if highlights:
            lines.append("关键证据:")
            for item in highlights:
                if isinstance(item, dict):
                    asset = item.get("asset_code") or item.get("code") or item.get("type") or "-"
                    message = item.get("message") or item.get("reason") or item.get("summary") or ""
                    lines.append(f"- {asset}: {message}")
                else:
                    lines.append(f"- {item}")
        if evidence:
            fields = ", ".join(sorted(str(key) for key in evidence.keys())[:8])
            lines.append(f"证据字段: {fields}")
        return "\n".join(lines)

    def _apply_jq_filter(self, data: Any, filter_expr: str) -> Any:
        """
        应用简单的JQ-like过滤器

        支持基本的路径访问: .key, .key[0], .key.subkey
        """
        if (
            not isinstance(filter_expr, str)
            or not filter_expr.startswith(".")
            or len(filter_expr) > 512
            or any(ord(character) < 32 for character in filter_expr)
        ):
            raise ValueError("invalid terminal output filter")

        path = filter_expr[1:].split(".")
        if len(path) > 16:
            raise ValueError("terminal output filter is too deep")
        result = data

        for part in path:
            if not part:
                continue

            # 处理数组索引: key[0]
            match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]", part)
            if match:
                key, index = match.groups()
                normalized_index = int(index)
                if normalized_index > 10_000 or not isinstance(result, Mapping):
                    raise ValueError("invalid terminal output filter index")
                collection = result.get(key)
                if not isinstance(collection, list) or normalized_index >= len(collection):
                    raise ValueError("terminal output filter index is unavailable")
                result = collection[normalized_index]
            elif part.isdigit():
                normalized_index = int(part)
                if (
                    normalized_index > 10_000
                    or not isinstance(result, list)
                    or normalized_index >= len(result)
                ):
                    raise ValueError("terminal output filter index is unavailable")
                result = result[normalized_index]
            elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) and isinstance(result, Mapping):
                result = result.get(part)
            else:
                raise ValueError("invalid terminal output filter path")

        return result


def _api_method(value: object) -> str:
    """Return one supported HTTP method for Terminal command dispatch."""

    if not isinstance(value, str):
        raise TerminalCommandExecutionError("terminal_api_method_invalid")
    normalized = value.strip().upper()
    if normalized not in _ALLOWED_API_METHODS:
        raise TerminalCommandExecutionError("terminal_api_method_invalid")
    return normalized


def _api_endpoint(value: object) -> str:
    """Return a bounded API endpoint template without control characters."""

    if not isinstance(value, str):
        raise TerminalCommandExecutionError("terminal_api_endpoint_invalid")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 2_048
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise TerminalCommandExecutionError("terminal_api_endpoint_invalid")
    return normalized


def _substitute_endpoint_params(endpoint: str, params: Mapping[str, object]) -> str:
    """Substitute path placeholders using encoded scalar parameter values."""

    rendered = endpoint
    for key, value in params.items():
        normalized_key = _parameter_name(key)
        placeholder = f"{{{normalized_key}}}"
        if placeholder in rendered:
            rendered = rendered.replace(placeholder, quote(_path_value(value), safe=""))
    if "{" in rendered or "}" in rendered:
        raise TerminalCommandExecutionError("terminal_api_path_params_missing")
    return rendered


def _request_params(
    endpoint: str,
    params: Mapping[str, object],
) -> dict[str, Any]:
    """Return detached non-path parameters within the JSON payload boundary."""

    values: dict[str, object] = {}
    for key, value in params.items():
        normalized_key = _parameter_name(key)
        if f"{{{normalized_key}}}" not in endpoint:
            values[normalized_key] = value
    normalized = _detached_json_value(values)
    if not isinstance(normalized, dict):
        raise TerminalCommandExecutionError("terminal_api_params_invalid")
    return cast(dict[str, Any], normalized)


def _parameter_name(value: object) -> str:
    """Return one governed command parameter name."""

    if not isinstance(value, str) or _PARAMETER_NAME_PATTERN.fullmatch(value) is None:
        raise TerminalCommandExecutionError("terminal_api_param_name_invalid")
    return value


def _path_value(value: object) -> str:
    """Return one bounded scalar suitable for URL path encoding."""

    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise TerminalCommandExecutionError("terminal_api_path_param_invalid")
    if isinstance(value, float) and not math.isfinite(value):
        raise TerminalCommandExecutionError("terminal_api_path_param_invalid")
    normalized = str(value).strip()
    if (
        not normalized
        or len(normalized) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise TerminalCommandExecutionError("terminal_api_path_param_invalid")
    return normalized


def _validate_internal_url(url: str) -> None:
    """Require one canonical internal API path without query or traversal."""

    parsed = urlsplit(url)
    decoded_path = unquote(parsed.path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/api/")
        or "\\" in decoded_path
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    ):
        raise TerminalCommandExecutionError("terminal_internal_api_url_invalid")


def _validate_external_url(url: str) -> None:
    """Require a credential-free HTTP(S) endpoint for legacy external commands."""

    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise TerminalCommandExecutionError("terminal_external_api_url_invalid")


def _positive_user_id(value: object) -> int:
    """Return one strict positive authenticated user ID."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TerminalCommandExecutionError("terminal_internal_user_invalid")
    return value


def _api_timeout(value: object) -> int:
    """Return a bounded external HTTP timeout in seconds."""

    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 120:
        raise TerminalCommandExecutionError("terminal_api_timeout_invalid")
    return value


def _http_status(value: object) -> int:
    """Return one valid HTTP response status code."""

    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
        raise TerminalCommandExecutionError("terminal_api_status_invalid")
    return value


def _detached_json_value(value: object) -> object:
    """Return finite bounded JSON data detached from provider-owned objects."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise TerminalCommandExecutionError("terminal_api_payload_invalid") from exc
    if len(encoded.encode("utf-8")) > _MAX_API_PAYLOAD_BYTES:
        raise TerminalCommandExecutionError("terminal_api_payload_too_large")
    return cast(object, json.loads(encoded))


class AnswerChainSettingsService:
    """Read terminal answer-chain settings without coupling interface to ORM imports."""

    @staticmethod
    def get_config(user: TerminalSettingsUser | None) -> dict[str, Any]:
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
