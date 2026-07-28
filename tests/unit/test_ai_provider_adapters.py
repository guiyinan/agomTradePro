import types

import pytest

from apps.ai_provider.infrastructure.adapters import OpenAICompatibleAdapter


class _FakeUsage:
    def __init__(self, input_tokens=11, output_tokens=7, total_tokens=18):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        self.prompt_tokens = input_tokens
        self.completion_tokens = output_tokens


class _FakeResponsesObj:
    def __init__(self, text="ok", status="completed", model="gpt-test"):
        self.output_text = text
        self.status = status
        self.model = model
        self.usage = _FakeUsage()


class _FakeChatMsg:
    def __init__(self, content="ok"):
        self.content = content


class _FakeChoice:
    def __init__(self, content="ok", finish_reason="stop"):
        self.message = _FakeChatMsg(content)
        self.finish_reason = finish_reason


class _FakeChatObj:
    def __init__(self, content="ok", model="gpt-test"):
        self.model = model
        self.choices = [_FakeChoice(content=content)]
        self.usage = _FakeUsage()


class _FakeOpenAI:
    def __init__(self, base_url=None, api_key=None):
        self.base_url = base_url
        self.api_key = api_key
        self.models = types.SimpleNamespace(list=lambda: [{"id": "gpt-test"}])

        self.responses = types.SimpleNamespace(
            create=lambda **kwargs: _FakeResponsesObj(text="resp-ok")
        )
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(
                create=lambda **kwargs: _FakeChatObj(content="chat-ok")
            )
        )


def test_openai_adapter_dual_mode_prefers_responses(monkeypatch):
    monkeypatch.setattr("apps.ai_provider.infrastructure.adapters.OPENAI_AVAILABLE", True)
    monkeypatch.setattr("apps.ai_provider.infrastructure.adapters.OpenAI", _FakeOpenAI)

    adapter = OpenAICompatibleAdapter(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        default_model="gpt-test",
        api_mode="dual",
        fallback_enabled=True,
    )
    result = adapter.chat_completion(messages=[{"role": "user", "content": "hello"}])

    assert result["status"] == "success"
    assert result["content"] == "resp-ok"
    assert result["request_type"] == "responses"
    assert result["fallback_used"] is False


def test_openai_adapter_dual_mode_fallback_to_chat(monkeypatch):
    class _FallbackOpenAI(_FakeOpenAI):
        def __init__(self, base_url=None, api_key=None):
            super().__init__(base_url=base_url, api_key=api_key)

            def _fail(**kwargs):
                raise RuntimeError("responses down")

            self.responses = types.SimpleNamespace(create=_fail)

    monkeypatch.setattr("apps.ai_provider.infrastructure.adapters.OPENAI_AVAILABLE", True)
    monkeypatch.setattr("apps.ai_provider.infrastructure.adapters.OpenAI", _FallbackOpenAI)

    adapter = OpenAICompatibleAdapter(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        default_model="gpt-test",
        api_mode="dual",
        fallback_enabled=True,
    )
    result = adapter.chat_completion(messages=[{"role": "user", "content": "hello"}])

    assert result["status"] == "success"
    assert result["content"] == "chat-ok"
    assert result["request_type"] == "chat"
    assert result["fallback_used"] is True


def test_openai_adapter_responses_only_no_fallback(monkeypatch):
    class _FailOpenAI(_FakeOpenAI):
        def __init__(self, base_url=None, api_key=None):
            super().__init__(base_url=base_url, api_key=api_key)

            def _fail(**kwargs):
                raise RuntimeError("responses only failure")

            self.responses = types.SimpleNamespace(create=_fail)

    monkeypatch.setattr("apps.ai_provider.infrastructure.adapters.OPENAI_AVAILABLE", True)
    monkeypatch.setattr("apps.ai_provider.infrastructure.adapters.OpenAI", _FailOpenAI)

    adapter = OpenAICompatibleAdapter(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        default_model="gpt-test",
        api_mode="responses_only",
        fallback_enabled=False,
    )
    result = adapter.chat_completion(messages=[{"role": "user", "content": "hello"}])

    assert result["status"] in {"error", "rate_limited", "timeout"}
    assert result["request_type"] == "responses"
    assert result["error_message"] == "ai_provider_request_failed"


def test_openai_adapter_dual_failure_redacts_both_sdk_errors(monkeypatch):
    class _FailBothOpenAI(_FakeOpenAI):
        def __init__(self, base_url=None, api_key=None):
            super().__init__(base_url=base_url, api_key=api_key)

            def _fail_responses(**kwargs):
                raise RuntimeError("https://admin:responses-secret@example.test/v1")

            def _fail_chat(**kwargs):
                raise RuntimeError("api_key=chat-secret")

            self.responses = types.SimpleNamespace(create=_fail_responses)
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=_fail_chat))

    monkeypatch.setattr("apps.ai_provider.infrastructure.adapters.OPENAI_AVAILABLE", True)
    monkeypatch.setattr(
        "apps.ai_provider.infrastructure.adapters.OpenAI",
        _FailBothOpenAI,
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        api_mode="dual",
        fallback_enabled=True,
    )

    result = adapter.chat_completion(messages=[{"role": "user", "content": "hello"}])

    assert result["status"] == "error"
    assert result["error_message"] == "ai_provider_fallback_failed"
    assert "responses-secret" not in str(result)
    assert "chat-secret" not in str(result)


def test_openai_adapter_classifies_timeout_without_returning_exception(monkeypatch):
    class _TimeoutOpenAI(_FakeOpenAI):
        def __init__(self, base_url=None, api_key=None):
            super().__init__(base_url=base_url, api_key=api_key)

            def _timeout(**kwargs):
                raise TimeoutError("proxy=https://admin:timeout-secret@example.test")

            self.responses = types.SimpleNamespace(create=_timeout)

    monkeypatch.setattr("apps.ai_provider.infrastructure.adapters.OPENAI_AVAILABLE", True)
    monkeypatch.setattr(
        "apps.ai_provider.infrastructure.adapters.OpenAI",
        _TimeoutOpenAI,
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        api_mode="responses_only",
    )

    result = adapter.chat_completion(messages=[{"role": "user", "content": "hello"}])

    assert result["status"] == "timeout"
    assert result["error_message"] == "ai_provider_timeout"
    assert "timeout-secret" not in str(result)


def test_openai_adapter_rejects_credentialed_url_and_invalid_sampling(monkeypatch):
    monkeypatch.setattr("apps.ai_provider.infrastructure.adapters.OPENAI_AVAILABLE", True)
    monkeypatch.setattr("apps.ai_provider.infrastructure.adapters.OpenAI", _FakeOpenAI)

    with pytest.raises(ValueError, match="ai_provider_base_url_invalid"):
        OpenAICompatibleAdapter(
            base_url="https://admin:secret@example.test/v1",
            api_key="sk-test",
        )

    adapter = OpenAICompatibleAdapter(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
    )
    result = adapter.chat_completion(
        messages=[{"role": "user", "content": "hello"}],
        temperature=float("inf"),
    )

    assert result["status"] == "error"
    assert result["error_message"] == "ai_provider_request_invalid"
    assert result["request_type"] == "validation"
