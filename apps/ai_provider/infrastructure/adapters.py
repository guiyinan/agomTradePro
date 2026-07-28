"""
OpenAI Compatible API Adapter.

通用 OpenAI 兼容 API 适配器，支持 OpenAI 最新 Responses API，
并保留 chat.completions 回退路径。
"""

import importlib
import logging
import math
import os
import time
from typing import Any, Protocol, TypedDict
from urllib.parse import urlsplit


def _load_openai_client() -> Any | None:
    try:
        module = importlib.import_module("openai")
    except ImportError:
        return None
    return getattr(module, "OpenAI", None)


OpenAI: Any = _load_openai_client()
OPENAI_AVAILABLE = OpenAI is not None

logger = logging.getLogger(__name__)

_MAX_PROVIDER_COUNT = 100


class _AIAdapterProtocol(Protocol):
    def is_available(self) -> bool:
        """Return whether the provider health check succeeds."""
        ...

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
        """Return one normalized provider result."""
        ...


class _AIAdapterEntry(TypedDict):
    adapter: _AIAdapterProtocol
    name: str
    is_available: bool


def _normalize_base_url(base_url: str) -> str:
    normalized = str(base_url).strip()
    if (
        not normalized
        or len(normalized) > 2048
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ValueError("ai_provider_base_url_invalid")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("ai_provider_base_url_invalid")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("ai_provider_base_url_invalid")
    return normalized.rstrip("/")


def _bounded_text(value: object, *, fallback: str, max_length: int) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > max_length
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        return fallback
    return normalized


def _provider_error_code(exc: Exception) -> tuple[str, str]:
    marker = f"{type(exc).__name__} {exc}".casefold()
    if "rate" in marker or "limit" in marker:
        return "rate_limited", "ai_provider_rate_limited"
    if "timeout" in marker or "timed out" in marker:
        return "timeout", "ai_provider_timeout"
    return "error", "ai_provider_request_failed"


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
    ) -> None:
        if not OPENAI_AVAILABLE:
            raise ImportError("需要安装 openai 库。请运行: agomtradepro/Scripts/pip install openai")

        self.base_url = _normalize_base_url(base_url)
        normalized_api_key = _bounded_text(api_key, fallback="", max_length=10000)
        if not normalized_api_key:
            raise ValueError("ai_provider_api_key_invalid")
        self.default_model = _bounded_text(
            default_model,
            fallback="gpt-4o-mini",
            max_length=200,
        )
        self.client = OpenAI(base_url=self.base_url, api_key=normalized_api_key)
        self.provider_name = _infer_provider_name(self.base_url)

        raw_mode = api_mode or os.getenv("AGOMTRADEPRO_OPENAI_API_MODE") or "dual"
        resolved_mode = raw_mode.strip().lower()
        if resolved_mode not in self.VALID_API_MODES:
            resolved_mode = "dual"
        self.api_mode = resolved_mode

        env_fallback = os.getenv("AGOMTRADEPRO_OPENAI_FALLBACK_ENABLED")
        if fallback_enabled is None:
            if env_fallback is None:
                self.fallback_enabled = True
            else:
                self.fallback_enabled = env_fallback.strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "y",
                    "on",
                }
        else:
            if not isinstance(fallback_enabled, bool):
                raise TypeError("ai_provider_fallback_flag_invalid")
            self.fallback_enabled = fallback_enabled

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
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            return self._input_error_result(model or self.default_model)
        if not math.isfinite(temperature) or not 0 <= temperature <= 2:
            return self._input_error_result(model or self.default_model)
        if max_tokens is not None and (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 1 <= max_tokens <= 1_000_000
        ):
            return self._input_error_result(model or self.default_model)
        model = _bounded_text(model, fallback=self.default_model, max_length=200)
        start_time = time.monotonic()

        if self.api_mode == "chat_only":
            return self._chat_completion_chat(
                messages,
                model,
                temperature,
                max_tokens,
                stream,
                start_time,
                tools=tools,
                tool_choice=tool_choice,
                response_format=response_format,
            )

        # responses_only / dual
        result = self._chat_completion_responses(
            messages,
            model,
            temperature,
            max_tokens,
            start_time,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
        )
        if result["status"] == "success":
            return result

        if self.api_mode == "responses_only" or not self.fallback_enabled:
            return result

        # dual 模式且允许回退
        fallback = self._chat_completion_chat(
            messages,
            model,
            temperature,
            max_tokens,
            stream,
            start_time,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
        )
        if fallback["status"] == "success":
            fallback["fallback_used"] = True
        else:
            fallback["error_message"] = "ai_provider_fallback_failed"
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
                response_time_ms=int((time.monotonic() - start_time) * 1000),
                request_type="responses",
            )
            if tool_calls:
                result["tool_calls"] = tool_calls
                result["finish_reason"] = "tool_calls"
            return result
        except Exception as exc:
            error_status, error_code = _provider_error_code(exc)
            return self._error_result(
                model=model,
                error_code=error_code,
                error_status=error_status,
                response_time_ms=int((time.monotonic() - start_time) * 1000),
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
                    error_code="ai_provider_stream_unsupported",
                    error_status="error",
                    response_time_ms=int((time.monotonic() - start_time) * 1000),
                    request_type="chat",
                )

            usage = getattr(response, "usage", None)
            message = response.choices[0].message if response.choices else None
            content = (message.content or "") if message else ""
            finish_reason = response.choices[0].finish_reason if response.choices else None

            # 提取 tool_calls
            tool_calls = None
            if message and getattr(message, "tool_calls", None):
                tool_calls = []
                for tc in message.tool_calls:
                    tool_calls.append(
                        {
                            "id": tc.id,
                            "tool_name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    )

            result = self._success_result(
                content=content,
                model=getattr(response, "model", model),
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
                finish_reason=finish_reason,
                response_time_ms=int((time.monotonic() - start_time) * 1000),
                request_type="chat",
            )
            if tool_calls:
                result["tool_calls"] = tool_calls
                result["finish_reason"] = "tool_calls"
            return result
        except Exception as exc:
            error_status, error_code = _provider_error_code(exc)
            return self._error_result(
                model=model,
                error_code=error_code,
                error_status=error_status,
                response_time_ms=int((time.monotonic() - start_time) * 1000),
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
                tool_calls.append(
                    {
                        "id": getattr(item, "call_id", getattr(item, "id", "")),
                        "tool_name": getattr(item, "name", ""),
                        "arguments": getattr(item, "arguments", "{}"),
                    }
                )
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
        error_code: str,
        error_status: str,
        response_time_ms: int,
        request_type: str,
    ) -> dict[str, Any]:
        return {
            "content": None,
            "model": model,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "finish_reason": None,
            "response_time_ms": response_time_ms,
            "status": error_status,
            "error_message": error_code,
            "estimated_cost": 0.0,
            "provider_used": self.provider_name,
            "request_type": request_type,
            "api_mode_used": self.api_mode,
            "fallback_used": False,
            "tool_calls": None,
        }

    def _input_error_result(self, model: str) -> dict[str, Any]:
        return self._error_result(
            model=model,
            error_code="ai_provider_request_invalid",
            error_status="error",
            response_time_ms=0,
            request_type="validation",
        )

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

    def __init__(self, providers: list[dict[str, Any]]) -> None:
        if len(providers) > _MAX_PROVIDER_COUNT:
            raise ValueError("ai_provider_count_exceeded")
        self.providers = list(providers)
        self.adapters: list[_AIAdapterEntry] = []
        self.unavailable_providers: list[dict[str, str]] = []

        for provider in providers:
            provider_name = _bounded_text(
                provider.get("name"),
                fallback="unknown",
                max_length=100,
            )
            try:
                base_url = provider.get("base_url")
                api_key = provider.get("api_key_decrypted") or provider.get("api_key")
                if not isinstance(base_url, str) or not isinstance(api_key, str):
                    raise ValueError("ai_provider_config_invalid")
                default_model = _bounded_text(
                    provider.get("default_model"),
                    fallback="gpt-4o-mini",
                    max_length=200,
                )
                api_mode = provider.get("api_mode")
                fallback_enabled = provider.get("fallback_enabled")
                if api_mode is not None and not isinstance(api_mode, str):
                    raise TypeError("ai_provider_api_mode_invalid")
                if fallback_enabled is not None and not isinstance(fallback_enabled, bool):
                    raise TypeError("ai_provider_fallback_flag_invalid")
                adapter = OpenAICompatibleAdapter(
                    base_url=base_url,
                    api_key=api_key,
                    default_model=default_model,
                    api_mode=api_mode,
                    fallback_enabled=fallback_enabled,
                )
                is_available = adapter.is_available()
                self.adapters.append(
                    {
                        "adapter": adapter,
                        "name": provider_name,
                        "is_available": is_available,
                    }
                )
                if not is_available:
                    self.unavailable_providers.append(
                        {
                            "name": provider_name,
                            "reason": "provider health check failed",
                        }
                    )
            except Exception as exc:
                # 单个 provider 初始化失败不阻断其余 provider
                logger.warning(
                    "AI provider initialization failed; provider=%s; exception_type=%s",
                    provider_name,
                    type(exc).__name__,
                )
                self.unavailable_providers.append(
                    {
                        "name": provider_name,
                        "reason": "provider initialization failed",
                    }
                )
                continue

    @property
    def has_available_adapters(self) -> bool:
        """Whether at least one provider passed initialization and health check."""
        return any(item["is_available"] for item in self.adapters)

    def describe_unavailable_providers(self) -> str:
        """Return a compact description of providers skipped by failover."""
        if not self.unavailable_providers:
            return "no providers configured"

        return "; ".join(f"{item['name']}: {item['reason']}" for item in self.unavailable_providers)

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
        if not self.has_available_adapters:
            return {
                "content": None,
                "model": model or "unknown",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "finish_reason": None,
                "response_time_ms": 0,
                "status": "error",
                "error_message": "no_healthy_ai_providers",
                "provider_used": None,
                "estimated_cost": 0.0,
                "request_type": "chat",
                "api_mode_used": None,
                "fallback_used": False,
                "tool_calls": None,
            }

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
            except Exception as exc:
                logger.warning(
                    "AI provider failover call failed; provider=%s; exception_type=%s",
                    item["name"],
                    type(exc).__name__,
                )

        return {
            "content": None,
            "model": model or "unknown",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "finish_reason": None,
            "response_time_ms": 0,
            "status": "error",
            "error_message": "all_ai_providers_failed",
            "provider_used": None,
            "estimated_cost": 0.0,
            "request_type": "chat",
            "api_mode_used": None,
            "fallback_used": False,
            "tool_calls": None,
        }
