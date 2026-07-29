"""T5 edge contracts for OpenAI-compatible and provider failover adapters."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.ai_provider.infrastructure import adapters
from apps.ai_provider.infrastructure.adapters import (
    AIFailoverHelper,
    OpenAICompatibleAdapter,
    _infer_provider_name,
)


def _adapter(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> OpenAICompatibleAdapter:
    """Build an adapter with a fully controlled OpenAI client."""
    client = MagicMock()
    monkeypatch.setattr(adapters, "OPENAI_AVAILABLE", True)
    monkeypatch.setattr(adapters, "OpenAI", MagicMock(return_value=client))
    adapter = OpenAICompatibleAdapter(
        base_url=str(kwargs.pop("base_url", "https://api.example.test/v1")),
        api_key="secret",
        **kwargs,
    )
    adapter.client = client
    return adapter


def test_provider_inference_and_initialization_environment_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider names, invalid modes, fallback env, and missing dependency are stable."""
    assert _infer_provider_name("https://api.openai.com") == "openai"
    assert _infer_provider_name("https://api.deepseek.com") == "deepseek"
    assert _infer_provider_name("https://dashscope.aliyuncs.com") == "qwen"
    assert _infer_provider_name("https://api.moonshot.cn") == "moonshot"
    assert _infer_provider_name("https://example.test") == "custom"

    monkeypatch.setenv("AGOMTRADEPRO_OPENAI_FALLBACK_ENABLED", "off")
    adapter = _adapter(monkeypatch, api_mode="INVALID", fallback_enabled=None)
    assert adapter.api_mode == "dual"
    assert adapter.fallback_enabled is False

    monkeypatch.delenv("AGOMTRADEPRO_OPENAI_FALLBACK_ENABLED")
    assert _adapter(monkeypatch, fallback_enabled=None).fallback_enabled is True
    assert _adapter(monkeypatch, fallback_enabled=0).fallback_enabled is False

    monkeypatch.setattr(adapters, "OPENAI_AVAILABLE", False)
    with pytest.raises(ImportError, match="openai"):
        OpenAICompatibleAdapter("https://example.test", "secret")


def test_responses_and_chat_paths_forward_optional_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both API styles must forward tools, formats, usage, and tool calls."""
    adapter = _adapter(monkeypatch, api_mode="responses_only")
    response_tool = SimpleNamespace(
        type="function_call",
        call_id="call-1",
        name="lookup",
        arguments='{"code":"A"}',
    )
    response_text = SimpleNamespace(
        type="message",
        content=[SimpleNamespace(text="fallback text")],
    )
    adapter.client.responses.create.return_value = SimpleNamespace(
        output_text="",
        output=[response_text, response_tool],
        usage=SimpleNamespace(input_tokens=3, output_tokens=2, total_tokens=None),
        status="completed",
        model="responses-model",
    )
    result = adapter.chat_completion(
        [{"role": "user", "content": "hello"}],
        max_tokens=10,
        tools=[{"type": "function"}],
        tool_choice="auto",
        response_format={"type": "json_object"},
    )
    assert result["content"] == "fallback text"
    assert result["total_tokens"] == 5
    assert result["finish_reason"] == "tool_calls"
    assert result["tool_calls"][0]["tool_name"] == "lookup"
    kwargs = adapter.client.responses.create.call_args.kwargs
    assert kwargs["max_output_tokens"] == 10
    assert kwargs["text"] == {"format": {"type": "json_object"}}

    chat_adapter = _adapter(monkeypatch, api_mode="chat_only")
    tool_call = SimpleNamespace(
        id="call-2",
        function=SimpleNamespace(name="trade", arguments="{}"),
    )
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    chat_adapter.client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=4, completion_tokens=1, total_tokens=5),
        model="chat-model",
    )
    chat_result = chat_adapter.chat_completion(
        [{"role": "user", "content": "hello"}],
        tools=[{"type": "function"}],
        tool_choice="auto",
        response_format={"type": "json_object"},
    )
    assert chat_result["finish_reason"] == "tool_calls"
    assert chat_result["tool_calls"][0]["tool_name"] == "trade"

    stream_result = chat_adapter.chat_completion(
        [{"role": "user", "content": "hello"}],
        stream=True,
    )
    assert stream_result["status"] == "error"
    assert "stream=True" in stream_result["error_message"]


def test_adapter_error_classification_availability_and_extractors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failures must classify rate limits/timeouts and health checks must fail closed."""
    adapter = _adapter(monkeypatch, api_mode="chat_only")
    adapter.client.chat.completions.create.side_effect = RuntimeError("rate limit")
    assert adapter.chat_completion([])["status"] == "rate_limited"
    adapter.client.chat.completions.create.side_effect = RuntimeError("request timeout")
    assert adapter.chat_completion([])["status"] == "timeout"

    adapter.client.models.list.return_value = []
    assert adapter.is_available() is True
    adapter.client.models.list.side_effect = RuntimeError("offline")
    assert adapter.is_available() is False
    assert adapter.estimate_tokens("") == 1
    assert adapter.estimate_tokens("123456") == 2

    assert (
        adapter._extract_text_from_responses(SimpleNamespace(output_text="direct"))
        == "direct"
    )
    assert adapter._extract_text_from_responses(SimpleNamespace(output=[])) == ""
    assert adapter._extract_tool_calls_from_responses(SimpleNamespace(output=[])) is None


def test_dual_mode_reports_both_failures_and_disabled_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dual-mode errors must retain both upstream failure reasons."""
    adapter = _adapter(monkeypatch, api_mode="dual", fallback_enabled=True)
    adapter.client.responses.create.side_effect = RuntimeError("responses offline")
    adapter.client.chat.completions.create.side_effect = RuntimeError("chat offline")
    result = adapter.chat_completion([])
    assert result["status"] == "error"
    assert "Responses failed" in result["error_message"]
    assert "Chat fallback failed" in result["error_message"]

    adapter.fallback_enabled = False
    disabled = adapter.chat_completion([])
    assert disabled["request_type"] == "responses"


def test_failover_helper_handles_initialization_success_and_provider_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failover must skip unhealthy adapters, return first success, and summarize errors."""
    unhealthy = MagicMock()
    unhealthy.is_available.return_value = False
    healthy = MagicMock()
    healthy.is_available.return_value = True
    healthy.chat_completion.return_value = {"status": "success", "content": "ok"}
    failing = MagicMock()
    failing.is_available.return_value = True
    failing.chat_completion.side_effect = RuntimeError("provider failed")
    factory = MagicMock(side_effect=[unhealthy, healthy])
    monkeypatch.setattr(adapters, "OpenAICompatibleAdapter", factory)

    helper = AIFailoverHelper(
        [
            {"name": "unhealthy", "base_url": "one", "api_key": "a"},
            {
                "name": "healthy",
                "base_url": "two",
                "api_key": "b",
                "api_key_decrypted": "decrypted",
            },
        ]
    )
    assert helper.has_available_adapters is True
    assert helper.chat_completion_with_failover([])["content"] == "ok"

    helper.adapters = [
        {"adapter": failing, "name": "failing", "is_available": True},
        {"adapter": unhealthy, "name": "skipped", "is_available": False},
    ]
    result = helper.chat_completion_with_failover([])
    assert result["status"] == "error"
    assert "Attempted: failing" in result["error_message"]
    assert "provider failed" in result["error_message"]

    monkeypatch.setattr(
        adapters,
        "OpenAICompatibleAdapter",
        MagicMock(side_effect=RuntimeError("bad configuration")),
    )
    broken = AIFailoverHelper(
        [{"name": "broken", "base_url": "bad", "api_key": "secret"}]
    )
    assert broken.has_available_adapters is False
    assert "bad configuration" in broken.describe_unavailable_providers()
    empty = AIFailoverHelper([])
    assert empty.describe_unavailable_providers() == "no providers configured"
