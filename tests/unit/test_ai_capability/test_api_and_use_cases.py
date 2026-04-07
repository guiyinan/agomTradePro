"""API and use-case regression tests for AI capability routing."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.ai_capability.application.dtos import RouteRequestDTO
from apps.ai_capability.application.use_cases import (
    CapabilityExecutionDispatcher,
    RouteMessageUseCase,
    SyncCapabilitiesUseCase,
)
from apps.ai_capability.infrastructure.models import CapabilityCatalogModel
from apps.terminal.infrastructure.models import TerminalRuntimeSettingsORM


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="cap_staff",
        password="test123",
        is_staff=True,
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="cap_regular",
        password="test123",
        is_staff=False,
    )


@pytest.fixture
def write_capability(db):
    return CapabilityCatalogModel.objects.create(
        capability_key="api.post.api.runtime.reset",
        source_type="api",
        source_ref="POST api/runtime/reset/",
        name="Runtime Reset",
        summary="Reset runtime state",
        description="Reset runtime state for the system",
        route_group="write_api",
        category="runtime",
        execution_target={"type": "api", "method": "POST", "path": "api/runtime/reset/"},
        risk_level="high",
        requires_confirmation=True,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=False,
        enabled_for_agent=True,
        visibility="public",
        auto_collected=True,
        review_status="auto",
    )


@pytest.fixture
def builtin_status_capability(db):
    return CapabilityCatalogModel.objects.create(
        capability_key="builtin.system_status",
        source_type="builtin",
        source_ref="builtin://system_status",
        name="System Status",
        summary="Read system readiness",
        description="Return the current system readiness summary",
        route_group="builtin",
        category="system",
        execution_target={"handler": "system_status"},
        risk_level="safe",
        requires_confirmation=True,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=True,
        enabled_for_agent=True,
        visibility="public",
        auto_collected=False,
        review_status="approved",
    )


@pytest.mark.django_db
def test_ai_capability_root_exposes_endpoint_directory(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)

    response = api_client.get("/api/ai-capability/")

    assert response.status_code == 200
    data = response.json()
    assert data["module"] == "ai-capability"
    assert data["endpoints"]["capabilities"] == "/api/ai-capability/capabilities/"


@pytest.mark.django_db
def test_non_admin_capability_detail_hides_technical_fields(api_client, regular_user, write_capability):
    api_client.force_authenticate(user=regular_user)

    response = api_client.get(f"/api/ai-capability/capabilities/{write_capability.capability_key}/")

    assert response.status_code == 200
    data = response.json()
    assert "source_ref" not in data
    assert "execution_target" not in data
    assert data["capability_key"] == write_capability.capability_key


@pytest.mark.django_db
def test_sync_capabilities_disables_missing_source_entries():
    CapabilityCatalogModel.objects.create(
        capability_key="api.get.api.legacy.status",
        source_type="api",
        source_ref="GET api/legacy/status/",
        name="Legacy Status",
        summary="Legacy endpoint",
        route_group="read_api",
        category="legacy",
        execution_target={"type": "api", "method": "GET", "path": "api/legacy/status/"},
        enabled_for_routing=True,
    )

    use_case = SyncCapabilitiesUseCase()
    with patch.object(SyncCapabilitiesUseCase, "_sync_apis", return_value=[]):
        result = use_case.execute(sync_type="incremental", source="api")

    assert result.disabled_count == 1
    assert CapabilityCatalogModel.objects.get(
        capability_key="api.get.api.legacy.status"
    ).enabled_for_routing is False


@pytest.mark.django_db
def test_route_message_requires_confirmation_for_write_capability(write_capability, regular_user):
    use_case = RouteMessageUseCase()

    response = use_case.execute(
        RouteRequestDTO(
            message="请帮我 reset runtime state",
            entrypoint="terminal",
            context={
                "user_id": regular_user.id,
                "user_is_admin": False,
                "mcp_enabled": True,
                "answer_chain_enabled": True,
            },
        )
    )

    assert response.decision == "ask_confirmation"
    assert response.selected_capability_key == write_capability.capability_key
    assert response.requires_confirmation is True


@pytest.mark.django_db
def test_non_admin_answer_chain_masks_technical_fields(write_capability, regular_user):
    use_case = RouteMessageUseCase()

    response = use_case.execute(
        RouteRequestDTO(
            message="runtime reset",
            entrypoint="terminal",
            context={
                "user_id": regular_user.id,
                "user_is_admin": False,
                "mcp_enabled": True,
                "answer_chain_enabled": True,
            },
        )
    )

    assert response.answer_chain["visibility"] == "masked"
    steps = response.answer_chain["steps"]
    assert all("technical_details" not in step for step in steps)
    assert write_capability.capability_key not in steps[1]["summary"]
    assert write_capability.name in steps[1]["summary"]


@pytest.mark.django_db
def test_capability_list_endpoint_still_works(api_client, regular_user, write_capability):
    api_client.force_authenticate(user=regular_user)

    response = api_client.get("/api/ai-capability/capabilities/")

    assert response.status_code == 200
    data = response.json()
    assert any(item["capability_key"] == write_capability.capability_key for item in data)


@pytest.mark.django_db
def test_web_chat_execute_action_runs_selected_capability(api_client, staff_user, builtin_status_capability):
    api_client.force_authenticate(user=staff_user)

    with patch("apps.ai_capability.application.use_cases.run_readiness_checks") as mock_checks, patch(
        "apps.ai_capability.application.use_cases.is_healthy",
        return_value=True,
    ):
        mock_checks.return_value = {
            "database": {"status": "ok"},
            "redis": {"status": "ok"},
            "celery": {"status": "ok"},
            "critical_data": {"status": "ok"},
        }

        response = api_client.post(
            "/api/chat/web/",
            {
                "message": "/status",
                "context": {
                    "execute_capability": builtin_status_capability.capability_key,
                    "action_type": "execute_capability",
                },
            },
            format="json",
        )

    assert response.status_code == 200
    data = response.json()
    assert data["route_confirmation_required"] is False
    assert "System Readiness" in data["reply"]
    assert data["metadata"]["provider"] == "capability-router"


@pytest.mark.django_db
def test_web_chat_execute_action_rejects_mcp_for_user_without_mcp_access(api_client, regular_user):
    profile = regular_user.account_profile
    profile.mcp_enabled = False
    profile.save(update_fields=["mcp_enabled"])

    capability = CapabilityCatalogModel.objects.create(
        capability_key="mcp_tool.get_macro_summary",
        source_type="mcp_tool",
        source_ref="get_macro_summary",
        name="get_macro_summary",
        summary="Read macro summary",
        description="Read macro summary",
        route_group="tool",
        category="mcp",
        execution_target={"type": "mcp_tool", "tool_name": "get_macro_summary"},
        risk_level="low",
        requires_mcp=True,
        requires_confirmation=True,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=True,
        enabled_for_agent=True,
        visibility="public",
        auto_collected=True,
        review_status="auto",
    )

    api_client.force_authenticate(user=regular_user)
    response = api_client.post(
        "/api/chat/web/",
        {
            "message": "执行 get_macro_summary",
            "context": {
                "execute_capability": capability.capability_key,
                "action_type": "execute_capability",
            },
        },
        format="json",
    )

    assert response.status_code == 403
    assert "not available" in response.json()["error"]


@pytest.mark.django_db
def test_chat_fallback_uses_admin_configured_system_prompt(regular_user):
    use_case = RouteMessageUseCase()
    settings_obj = TerminalRuntimeSettingsORM.get_solo()
    settings_obj.fallback_chat_system_prompt = (
        "你是 AgomTradePro 平台助手。请优先回答系统状态、Regime、政策、RSS 新闻与热点相关问题。"
    )
    settings_obj.save(update_fields=["fallback_chat_system_prompt"])

    with patch("apps.ai_capability.application.use_cases.AIClientFactory") as mock_factory:
        mock_client = mock_factory.return_value.get_client.return_value
        mock_client.chat_completion.return_value = {
            "status": "success",
            "content": "建议先查看当前 Regime、系统状态或投资组合配置。",
        }

        response = use_case.execute(
            RouteRequestDTO(
                message="系统推荐什么",
                entrypoint="terminal",
                provider_name="openai-main",
                model="gpt-4.1",
                context={
                    "user_id": regular_user.id,
                    "user_is_admin": False,
                    "mcp_enabled": True,
                    "answer_chain_enabled": True,
                    "history": [{"role": "user", "content": "你好"}],
                },
            )
        )

    assert response.decision == "chat"
    sent_messages = mock_client.chat_completion.call_args.kwargs["messages"]
    assert sent_messages[0]["role"] == "system"
    assert sent_messages[0]["content"] == settings_obj.fallback_chat_system_prompt
    assert sent_messages[-1] == {"role": "user", "content": "系统推荐什么"}


@pytest.mark.django_db
def test_api_dispatcher_rejects_non_integer_path_param():
    dispatcher = CapabilityExecutionDispatcher()
    capability = CapabilityCatalogModel.objects.create(
        capability_key="api.get.api.simulated_trading.positions",
        source_type="api",
        source_ref="GET api/simulated-trading/accounts/<int:account_id>/positions/",
        name="Get Simulated-Trading Accounts Positions",
        summary="Read positions for an account",
        route_group="read_api",
        category="simulated-trading",
        execution_target={
            "type": "api",
            "method": "GET",
            "path": "api/simulated-trading/accounts/<int:account_id>/positions/",
        },
        risk_level="low",
        requires_confirmation=False,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=True,
        enabled_for_agent=True,
        visibility="public",
        auto_collected=True,
        review_status="auto",
    ).to_entity()

    result = dispatcher._execute_api(
        capability,
        context=type(
            "Ctx",
            (),
            {
                "context": {"params": {"account_id": "查询account id"}},
                "user_id": None,
            },
        )(),
    )

    assert "account_id" in result["reply"]
    assert "整数" in result["reply"]


@pytest.mark.django_db
def test_sync_mcp_tools_discovers_builtin_registry_tools():
    pytest.importorskip("mcp")

    use_case = SyncCapabilitiesUseCase()

    result = use_case.execute(sync_type="incremental", source="mcp_tool")

    assert result.total_discovered >= 200
    assert CapabilityCatalogModel.objects.filter(source_type="mcp_tool").exists()


def test_sync_mcp_tools_marks_mutating_tools_high_risk_and_non_routable():
    use_case = SyncCapabilitiesUseCase()

    with patch(
        "apps.ai_capability.application.use_cases._list_sdk_mcp_tools",
        return_value=[
            SimpleNamespace(name="update_portfolio_config", description="update", inputSchema={}),
            SimpleNamespace(name="get_portfolio_status", description="get", inputSchema={}),
        ],
    ):
        capabilities = use_case._sync_mcp_tools()

    by_key = {cap.capability_key: cap for cap in capabilities}

    mutating = by_key["mcp_tool.update_portfolio_config"]
    assert mutating.risk_level.value == "high"
    assert mutating.requires_confirmation is True
    assert mutating.enabled_for_routing is False
    assert mutating.visibility.value == "admin"

    readonly = by_key["mcp_tool.get_portfolio_status"]
    assert readonly.risk_level.value == "low"
    assert readonly.requires_confirmation is True
    assert readonly.enabled_for_routing is True
    assert readonly.visibility.value == "admin"
