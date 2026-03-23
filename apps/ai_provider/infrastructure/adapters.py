"""
OpenAI Compatible API Adapter.

通用 OpenAI 兼容 API 适配器，支持 OpenAI 最新 Responses API，
并保留 chat.completions 回退路径。
"""

import os
import time
from typing import Any, Dict, List, Optional

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OpenAI = None  # type: ignore[misc,assignment]
    OPENAI_AVAILABLE = False


def _infer_provider_name(base_url: str) -> str:
    text = (base_url or "").lower()
    if "openai" in text:
        return "openai"
    if "deepseek" in text:
        return "deepseek"
    if "dashscope" in text or "aliyuncs" in text or "qwen" in text:
        return "qwen"
    if "moonshot" in text:
        return "moonshot"
    return "custom"


class OpenAICompatibleAdapter:
    """
    通用 OpenAI 兼容 API 适配器。

    支持两种调用模式：
    - responses_only: 仅使用 Responses API
    - chat_only: 仅使用 chat.completions
    - dual: 优先 Responses，失败后回退 chat.completions
    """

    VALID_API_MODES = {"dual", "responses_only", "chat_only"}

    def __init__(
        self,
        base_url: str,
        api_key: str,
        default_model: str = "gpt-4o-mini",
        api_mode: str | None = None,
        fallback_enabled: bool | None = None,
    ):
        if not OPENAI_AVAILABLE:
            raise ImportError("需要安装 openai 库。请运行: agomtradepro/Scripts/pip install openai")

        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.default_model = default_model
        self.base_url = base_url
        self.provider_name = _infer_provider_name(base_url)

        resolved_mode = (api_mode or os.getenv("AGOMTRADEPRO_OPENAI_API_MODE", "dual")).strip().lower()
        if resolved_mode not in self.VALID_API_MODES:
            resolved_mode = "dual"
        self.api_mode = resolved_mode

        env_fallback = os.getenv("AGOMTRADEPRO_OPENAI_FALLBACK_ENABLED")
        if fallback_enabled is None:
            if env_fallback is None:
                self.fallback_enabled = True
            else:
                self.fallback_enabled = env_fallback.strip().lower() in {"1", "true", "yes", "y", "on"}
        else:
            self.fallback_enabled = bool(fallback_enabled)

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        统一聊天接口，内部按 api_mode 决定调用 Responses 或 Chat Completions。

        支持 tools / tool_choice / response_format 参数，用于 Agent Runtime
        的工具调用闭环。返回结果中包含 tool_calls 字段。
        """
        model = model or self.default_model
        start_time = time.time()

        if self.api_mode == "chat_only":
            return self._chat_completion_chat(
                messages, model, temperature, max_tokens, stream, start_time,
                tools=tools, tool_choice=tool_choice, response_format=response_format,
            )

        # responses_only / dual
        result = self._chat_completion_responses(
            messages, model, temperature, max_tokens, start_time,
            tools=tools, tool_choice=tool_choice, response_format=response_format,
        )
        if result["status"] == "success":
            return result

        if self.api_mode == "responses_only" or not self.fallback_enabled:
            return result

        # dual 模式且允许回退
        fallback = self._chat_completion_chat(
            messages, model, temperature, max_tokens, stream, start_time,
            tools=tools, tool_choice=tool_choice, response_format=response_format,
        )
        if fallback["status"] == "success":
            fallback["fallback_used"] = True
        else:
            fallback["error_message"] = (
                f"Responses failed: {result.get('error_message')}; "
                f"Chat fallback failed: {fallback.get('error_message')}"
            )
        return fallback

    def _chat_completion_responses(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int | None,
        start_time: float,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "input": messages,
                "temperature": temperature,
            }
            if max_tokens is not None:
                kwargs["max_output_tokens"] = max_tokens
            if tools:
                kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
            if response_format is not None:
                kwargs["text"] = {"format": response_format}

            response = self.client.responses.create(**kwargs)
            content = self._extract_text_from_responses(response)
            tool_calls = self._extract_tool_calls_from_responses(response)
            usage = getattr(response, "usage", None)
            prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            total_tokens = int(
                getattr(usage, "total_tokens", prompt_tokens + completion_tokens)
                or (prompt_tokens + completion_tokens)
            )

            finish_reason = getattr(response, "status", "completed")

            result = self._success_result(
                content=content,
                model=getattr(response, "model", model),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                finish_reason=finish_reason,
                response_time_ms=int((time.time() - start_time) * 1000),
                request_type="responses",
            )
            if tool_calls:
                result["tool_calls"] = tool_calls
                result["finish_reason"] = "tool_calls"
            return result
        except Exception as exc:
            return self._error_result(
                model=model,
                error_msg=str(exc),
                response_time_ms=int((time.time() - start_time) * 1000),
                request_type="responses",
            )

    def _chat_completion_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int | None,
        stream: bool,
        start_time: float,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            create_kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": stream,
            }
            if tools:
                create_kwargs["tools"] = tools
            if tool_choice is not None:
                create_kwargs["tool_choice"] = tool_choice
            if response_format is not None:
                create_kwargs["response_format"] = response_format

            response = self.client.chat.completions.create(**create_kwargs)
            # 不支持在此路径向上层透传 stream generator，统一走非流式数据对象
            if stream:
                return self._error_result(
                    model=model,
                    error_msg="stream=True is not supported in OpenAICompatibleAdapter return format",
                    response_time_ms=int((time.time() - start_time) * 1000),
                    request_type="chat",
                )

            usage = getattr(response, "usage", None)
            message = response.choices[0].message if response.choices else None
            content = (message.content or "") if message else ""
            finish_reason = (response.choices[0].finish_reason if response.choices else None)

            # 提取 tool_calls
            tool_calls = None
            if message and getattr(message, "tool_calls", None):
                tool_calls = []
                for tc in message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "tool_name": tc.function.name,
                        "arguments": tc.function.arguments,
                    })

            result = self._success_result(
                content=content,
                model=getattr(response, "model", model),
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
                finish_reason=finish_reason,
                response_time_ms=int((time.time() - start_time) * 1000),
                request_type="chat",
            )
            if tool_calls:
                result["tool_calls"] = tool_calls
                result["finish_reason"] = "tool_calls"
            return result
        except Exception as exc:
            return self._error_result(
                model=model,
                error_msg=str(exc),
                response_time_ms=int((time.time() - start_time) * 1000),
                request_type="chat",
            )

    @staticmethod
    def _extract_tool_calls_from_responses(response: Any) -> list[dict[str, Any]] | None:
        """从 Responses API 返回中提取 tool_calls。"""
        output = getattr(response, "output", None) or []
        tool_calls: list[dict[str, Any]] = []
        for item in output:
            item_type = getattr(item, "type", None)
            if item_type == "function_call":
                tool_calls.append({
                    "id": getattr(item, "call_id", getattr(item, "id", "")),
                    "tool_name": getattr(item, "name", ""),
                    "arguments": getattr(item, "arguments", "{}"),
                })
        return tool_calls if tool_calls else None

    @staticmethod
    def _extract_text_from_responses(response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if output_text:
            return str(output_text)
        # 兼容不同 SDK 结构
        output = getattr(response, "output", None) or []
        chunks: list[str] = []
        for item in output:
            content_list = getattr(item, "content", None) or []
            for content in content_list:
                text = getattr(content, "text", None)
                if text:
                    chunks.append(str(text))
        return "\n".join(chunks).strip()

    def _success_result(
        self,
        content: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        finish_reason: str | None,
        response_time_ms: int,
        request_type: str,
    ) -> dict[str, Any]:
        return {
            "content": content,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "finish_reason": finish_reason,
            "response_time_ms": response_time_ms,
            "status": "success",
            "error_message": None,
            "estimated_cost": 0.0,
            "provider_used": self.provider_name,
            "request_type": request_type,
            "api_mode_used": self.api_mode,
            "fallback_used": False,
            "tool_calls": None,
        }

    def _error_result(
        self,
        model: str,
        error_msg: str,
        response_time_ms: int,
        request_type: str,
    ) -> dict[str, Any]:
        status = "error"
        lowered = error_msg.lower()
        if "rate" in lowered or "limit" in lowered:
            status = "rate_limited"
        elif "timeout" in lowered:
            status = "timeout"

        return {
            "content": None,
            "model": model,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "finish_reason": None,
            "response_time_ms": response_time_ms,
            "status": status,
            "error_message": error_msg,
            "estimated_cost": 0.0,
            "provider_used": self.provider_name,
            "request_type": request_type,
            "api_mode_used": self.api_mode,
            "fallback_used": False,
            "tool_calls": None,
        }

    def is_available(self) -> bool:
        try:
            self.client.models.list()
            return True
        except Exception:
            return False

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, len(text) // 3)


class AIFailoverHelper:
    """AI 故障转移辅助类，按优先级依次尝试多个提供商。"""

    def __init__(self, providers: list[dict[str, Any]]):
        self.providers = providers
        self.adapters = []

        for provider in providers:
            try:
                adapter = OpenAICompatibleAdapter(
                    base_url=provider["base_url"],
                    api_key=provider.get("api_key_decrypted") or provider["api_key"],
                    default_model=provider.get("default_model", "gpt-4o-mini"),
                    api_mode=provider.get("api_mode"),
                    fallback_enabled=provider.get("fallback_enabled"),
                )
                self.adapters.append(
                    {
                        "adapter": adapter,
                        "name": provider.get("name", "unknown"),
                        "is_available": adapter.is_available(),
                    }
                )
            except Exception:
                # 单个 provider 初始化失败不阻断其余 provider
                continue

    def chat_completion_with_failover(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error = None

        for item in self.adapters:
            if not item["is_available"]:
                continue

            try:
                result = item["adapter"].chat_completion(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    tool_choice=tool_choice,
                    response_format=response_format,
                )
                result["provider_used"] = item["name"]
                if result["status"] == "success":
                    return result

                last_error = result.get("error_message")
            except Exception as exc:
                last_error = str(exc)

        return {
            "content": None,
            "model": model or "unknown",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "finish_reason": None,
            "response_time_ms": 0,
            "status": "error",
            "error_message": f"All providers failed. Last error: {last_error}",
            "provider_used": None,
            "estimated_cost": 0.0,
            "request_type": "chat",
            "api_mode_used": None,
            "fallback_used": False,
            "tool_calls": None,
        }
