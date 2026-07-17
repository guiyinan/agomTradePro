# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: routing."""

from .api_and_use_cases_support import *


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
def test_confirmation_resumes_locked_mcp_capability_across_route_and_web(api_client, staff_user):
    capability = CapabilityCatalogModel.objects.create(
        capability_key="mcp_tool.fund.read.ranking",
        source_type="mcp_tool",
        source_ref="fund.read.ranking",
        name="Fund Ranking",
        summary="Read the canonical fund ranking for one macro regime",
        description="获取基金排名和基金排行",
        route_group="tool",
        category="fund",
        tags=["fund", "ranking", "基金", "排名"],
        examples=["获取基金排名", "fund.read.ranking"],
        input_schema={
            "type": "object",
            "properties": {
                "regime": {"type": "string", "default": "Recovery"},
                "max_count": {"type": "integer", "default": 50},
            },
            "additionalProperties": False,
        },
        execution_target={
            "type": "mcp_capability",
            "tool_name": "agom_capability_call",
            "capability_key": "fund.read.ranking",
        },
        risk_level="low",
        requires_mcp=True,
        requires_confirmation=True,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=True,
        enabled_for_agent=True,
        visibility="public",
        review_status="approved",
    )
    api_client.force_authenticate(user=staff_user)

    first = api_client.post(
        "/api/ai-capability/route/",
        {
            "message": "fund.read.ranking",
            "entrypoint": "agent",
            "context": {
                "params": {"regime": "Recovery", "account_id": 365},
            },
        },
        format="json",
    )

    assert first.status_code == 200
    pending = first.json()
    assert pending["selected_capability_key"] == capability.capability_key
    assert pending["requires_confirmation"] is True
    assert pending["confirmation"]["capability_key"] == capability.capability_key
    assert pending["confirmation"]["normalized_params"] == {"regime": "Recovery"}

    with (
        patch(
            "apps.ai_capability.application.use_cases._call_sdk_mcp_tool",
            return_value={"regime": "Recovery", "funds": [{"fund_code": "000001"}]},
        ) as mock_call,
        patch(
            "apps.ai_capability.application.result_enrichment.resolve_asset_names_read_only",
            return_value={"000001": "华夏成长"},
        ),
    ):
        resumed = api_client.post(
            "/api/chat/web/",
            {
                "message": "Y",
                "session_id": pending["session_id"],
                "context": {
                    "confirmation": {
                        **pending["confirmation"],
                        "approved": True,
                    }
                },
            },
            format="json",
        )

    assert resumed.status_code == 200
    payload = resumed.json()
    assert payload["route_confirmation_required"] is False
    assert payload["selected_capability_key"] == capability.capability_key
    assert payload["result"]["funds"][0] == {
        "fund_code": "000001",
        "fund_name": "华夏成长",
    }
    mock_call.assert_called_once_with(
        "agom_capability_call",
        {
            "capability_key": "fund.read.ranking",
            "arguments": {"regime": "Recovery"},
        },
    )


@pytest.mark.django_db
def test_web_chat_execute_action_runs_selected_capability(
    api_client, staff_user, builtin_status_capability
):
    api_client.force_authenticate(user=staff_user)

    with (
        patch("apps.ai_capability.application.use_cases.run_readiness_checks") as mock_checks,
        patch(
            "apps.ai_capability.application.use_cases.is_healthy",
            return_value=True,
        ),
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
def test_web_chat_route_prefers_api_capability_over_mcp_wrapper(regular_user):
    CapabilityCatalogModel.objects.create(
        capability_key="api.get.api.nebula.summary",
        source_type="api",
        source_ref="GET api/nebula/summary/",
        name="Get Nebula Summary",
        summary="Get nebula summary",
        description="Read nebula summary from canonical API",
        route_group="read_api",
        category="nebula",
        semantic_key="nebula.summary",
        tags=["nebula", "summary", "orion"],
        examples=["nebula orion summary"],
        execution_target={"type": "api", "method": "GET", "path": "api/nebula/summary/"},
        risk_level="low",
        requires_confirmation=False,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=True,
        enabled_for_agent=True,
        visibility="public",
        auto_collected=True,
        review_status="approved",
    )
    CapabilityCatalogModel.objects.create(
        capability_key="mcp_tool.system.read.nebula.summary",
        source_type="mcp_tool",
        source_ref="system.read.nebula.summary",
        name="system.read.nebula.summary",
        summary="Get nebula summary",
        description="Read nebula summary through MCP capability wrapper",
        route_group="tool",
        category="nebula",
        semantic_key="nebula.summary",
        tags=["nebula", "summary", "orion", "mcp"],
        examples=["nebula orion summary"],
        execution_target={
            "type": "mcp_capability",
            "tool_name": "agom_capability_call",
            "capability_key": "system.read.nebula.summary",
        },
        risk_level="low",
        requires_mcp=True,
        requires_confirmation=False,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=True,
        enabled_for_agent=True,
        visibility="public",
        auto_collected=True,
        review_status="approved",
    )

    use_case = RouteMessageUseCase()

    result = use_case.execute(
        RouteRequestDTO(
            message="nebula orion summary",
            entrypoint="web",
            context={
                "user_id": regular_user.id,
                "user_is_admin": False,
                "mcp_enabled": True,
                "answer_chain_enabled": True,
            },
        )
    )

    assert result.selected_capability_key == "api.get.api.nebula.summary"
    assert all(
        item["capability_key"] != "mcp_tool.system.read.nebula.summary"
        for item in result.candidate_capabilities
    )


@pytest.mark.django_db
def test_web_chat_route_does_not_auto_select_mcp_when_it_is_only_candidate(regular_user):
    CapabilityCatalogModel.objects.create(
        capability_key="mcp_tool.system.read.nebula.summary",
        source_type="mcp_tool",
        source_ref="system.read.nebula.summary",
        name="system.read.nebula.summary",
        summary="Get nebula summary",
        description="Read nebula summary through MCP capability wrapper",
        route_group="tool",
        category="nebula",
        semantic_key="nebula.summary",
        tags=["nebula", "summary", "orion", "mcp"],
        examples=["nebula orion summary"],
        execution_target={
            "type": "mcp_capability",
            "tool_name": "agom_capability_call",
            "capability_key": "system.read.nebula.summary",
        },
        risk_level="low",
        requires_mcp=True,
        requires_confirmation=False,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=True,
        enabled_for_agent=True,
        visibility="public",
        auto_collected=True,
        review_status="approved",
    )

    use_case = RouteMessageUseCase()
    with patch("apps.ai_capability.application.use_cases.AIClientFactory") as mock_factory:
        mock_client = mock_factory.return_value.get_client.return_value
        mock_client.chat_completion.return_value = {
            "status": "success",
            "content": "需要更多上下文，请说明你想查看哪个市场摘要。",
        }
        result = use_case.execute(
            RouteRequestDTO(
                message="nebula orion summary",
                entrypoint="web",
                provider_name="openai-main",
                model="gpt-4.1",
                context={
                    "user_id": regular_user.id,
                    "user_is_admin": False,
                    "mcp_enabled": True,
                    "answer_chain_enabled": True,
                },
            )
        )

    assert result.decision == "chat"
    assert result.selected_capability_key is None
