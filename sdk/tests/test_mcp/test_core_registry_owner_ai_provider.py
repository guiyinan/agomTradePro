# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_ai_provider."""

from .core_registry_support import *


def test_agom_capability_call_reads_ai_provider_catalog_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "list_ai_providers",
        lambda **kwargs: {
            "providers": [
                {
                    "id": 3,
                    "name": "openai-main",
                    "provider_type": "openai",
                    "default_model": "gpt-5",
                    "is_active": True,
                }
            ],
            "total_count": 1,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "ai_provider.read.provider_catalog",
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert "ai_provider.read.provider_catalog" in rendered
    assert "openai-main" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_ai_provider_detail_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_ai_provider",
        lambda provider_id: {
            "id": provider_id,
            "name": "openai-main",
            "scope": "system",
            "provider_type": "openai",
            "default_model": "gpt-5",
            "is_active": True,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "ai_provider.read.provider_detail",
                "arguments": {"provider_id": 3},
            },
        )
    )

    rendered = str(result)
    assert "ai_provider.read.provider_detail" in rendered
    assert "openai-main" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_ai_provider_usage_logs_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "list_ai_usage_logs",
        lambda **kwargs: {
            "logs": [
                {
                    "id": 11,
                    "provider_id": 3,
                    "provider_name": "openai-main",
                    "model": "gpt-5",
                    "status": "success",
                }
            ],
            "total_count": 1,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "ai_provider.read.usage_logs",
                "arguments": {"provider_id": 3, "status": "success"},
            },
        )
    )

    rendered = str(result)
    assert "ai_provider.read.usage_logs" in rendered
    assert "openai-main" in rendered
    assert "core-only-fallback" in rendered


def test_ai_provider_update_provider_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAIProviderModule:
        @staticmethod
        def get_provider(provider_id):
            assert provider_id == 7
            return {
                "id": provider_id,
                "name": "system-main",
                "provider_type": "openai",
                "scope": "system",
                "is_active": True,
                "priority": 10,
                "base_url": "https://example.invalid/system",
                "default_model": "gpt-4o-mini",
                "api_mode": "dual",
                "fallback_enabled": True,
                "daily_budget_limit": 20.0,
                "monthly_budget_limit": 200.0,
                "extra_config": {"timeout": 30, "region": "global"},
                "description": "system provider",
            }

    class _FakeClient:
        ai_provider = _FakeAIProviderModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_update_ai_provider(**kwargs):
        captured_calls.append(dict(kwargs))
        payload = kwargs["payload"]
        return {
            "id": kwargs["provider_id"],
            "name": payload["name"],
            "provider_type": payload["provider_type"],
            "base_url": payload["base_url"],
            "default_model": payload["default_model"],
            "api_mode": payload["api_mode"],
            "fallback_enabled": payload["fallback_enabled"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "update_ai_provider",
        fake_update_ai_provider,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="ai_provider.update.provider",
        arguments={
            "provider_id": 7,
            "name": "system-main-v2",
            "provider_type": "openai",
            "base_url": "https://example.invalid/system-v2",
            "default_model": "gpt-4.1-mini",
            "api_mode": "responses_only",
            "fallback_enabled": False,
            "idempotency_key": "idem-ai-provider-update",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["provider_summary"]["name"] == "system-main"
    assert preview_response["preview_result"]["provider_summary"]["extra_config_keys"] == [
        "region",
        "timeout",
    ]
    assert preview_response["preview_result"]["update_summary"]["field_count"] == 6
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 7
    assert resume_response["result"]["name"] == "system-main-v2"
    assert captured_calls[0]["provider_id"] == 7
    assert captured_calls[0]["payload"]["default_model"] == "gpt-4.1-mini"
    assert captured_calls[0]["payload"]["fallback_enabled"] is False
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["provider_id"] == 7
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_ai_provider_create_provider_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    def fake_create_ai_provider(**kwargs):
        captured_calls.append(dict(kwargs))
        payload = kwargs["payload"]
        return {
            "id": 11,
            "name": payload["name"],
            "provider_type": payload["provider_type"],
            "scope": "system",
            "is_active": payload.get("is_active", True),
            "priority": payload.get("priority", 10),
            "base_url": payload["base_url"],
            "default_model": payload.get("default_model", "gpt-3.5-turbo"),
            "api_mode": payload.get("api_mode", "dual"),
            "fallback_enabled": payload.get("fallback_enabled", True),
            "extra_config": payload.get("extra_config", {}),
            "description": payload.get("description", ""),
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "create_ai_provider",
        fake_create_ai_provider,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="ai_provider.create.provider",
        arguments={
            "name": "deepseek-main",
            "provider_type": "deepseek",
            "api_key": "sk-secret",
            "default_model": "deepseek-chat",
            "extra_config": {"timeout": 20, "region": "cn"},
            "idempotency_key": "idem-ai-provider-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["create_summary"]["name"] == "deepseek-main"
    assert preview_response["preview_result"]["create_summary"]["provider_type"] == "deepseek"
    assert preview_response["preview_result"]["create_summary"]["base_url"] == (
        "https://api.deepseek.com/v1"
    )
    assert preview_response["preview_result"]["create_summary"]["has_api_key"] is True
    assert preview_response["preview_result"]["create_summary"]["extra_config_keys"] == [
        "region",
        "timeout",
    ]
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 11
    assert resume_response["result"]["name"] == "deepseek-main"
    assert captured_calls[0]["payload"]["base_url"] == "https://api.deepseek.com/v1"
    assert captured_calls[0]["payload"]["default_model"] == "deepseek-chat"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["name"] == "deepseek-main"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_ai_provider_toggle_provider_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAIProviderModule:
        @staticmethod
        def get_provider(provider_id):
            assert provider_id == 7
            return {
                "id": provider_id,
                "name": "system-main",
                "provider_type": "openai",
                "scope": "system",
                "is_active": True,
                "priority": 10,
                "base_url": "https://example.invalid/system",
                "default_model": "gpt-4o-mini",
                "api_mode": "dual",
                "fallback_enabled": True,
                "daily_budget_limit": 20.0,
                "monthly_budget_limit": 200.0,
                "extra_config": {"timeout": 30},
                "description": "system provider",
            }

    class _FakeClient:
        ai_provider = _FakeAIProviderModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    captured_calls = []

    def fake_toggle_ai_provider(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": kwargs["provider_id"],
            "name": "system-main",
            "provider_type": "openai",
            "scope": "system",
            "is_active": False,
            "priority": 10,
            "base_url": "https://example.invalid/system",
            "default_model": "gpt-4o-mini",
            "api_mode": "dual",
            "fallback_enabled": True,
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "toggle_ai_provider",
        fake_toggle_ai_provider,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="ai_provider.toggle.provider",
        arguments={
            "provider_id": 7,
            "idempotency_key": "idem-ai-provider-toggle",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["provider_summary"]["is_active"] is True
    assert preview_response["preview_result"]["target_is_active"] is False
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 7
    assert resume_response["result"]["is_active"] is False
    assert captured_calls[0]["provider_id"] == 7
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["provider_id"] == 7
    assert audit_events[1]["event_type"] == "confirmation_completed"
