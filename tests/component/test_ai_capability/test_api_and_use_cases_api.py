# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: api."""

from .api_and_use_cases_support import *


@pytest.mark.django_db
def test_ai_capability_root_exposes_endpoint_directory(api_client, regular_user):
    api_client.force_authenticate(user=regular_user)

    response = api_client.get("/api/ai-capability/")

    assert response.status_code == 200
    data = response.json()
    assert data["module"] == "ai-capability"
    assert data["endpoints"]["capabilities"] == "/api/ai-capability/capabilities/"
    assert data["endpoints"]["mcp_tools"] == "/api/ai-capability/mcp-tools/"


@pytest.mark.django_db
def test_non_admin_capability_detail_hides_technical_fields(
    api_client, regular_user, write_capability
):
    api_client.force_authenticate(user=regular_user)

    response = api_client.get(f"/api/ai-capability/capabilities/{write_capability.capability_key}/")

    assert response.status_code == 200
    data = response.json()
    assert "source_ref" not in data
    assert "execution_target" not in data
    assert data["capability_key"] == write_capability.capability_key


@pytest.mark.django_db
def test_capability_list_endpoint_still_works(api_client, regular_user, write_capability):
    api_client.force_authenticate(user=regular_user)

    response = api_client.get("/api/ai-capability/capabilities/")

    assert response.status_code == 200
    data = response.json()
    assert any(item["capability_key"] == write_capability.capability_key for item in data)


@pytest.mark.django_db
def test_admin_mcp_tools_endpoint_returns_governance_rows(
    api_client, staff_user, mcp_tool_capability
):
    api_client.force_authenticate(user=staff_user)

    response = api_client.get("/api/ai-capability/mcp-tools/?status=routing_on&limit=10")

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 1
    assert data["module_choices"] == ["get"]
    assert data["tools"][0]["capability_key"] == mcp_tool_capability.capability_key
    assert data["tools"][0]["enabled_for_routing"] is True
    assert data["tools"][0]["enabled_for_terminal"] is False


@pytest.mark.django_db
def test_regular_user_cannot_access_mcp_governance_endpoints(
    api_client, regular_user, mcp_tool_capability
):
    api_client.force_authenticate(user=regular_user)

    list_response = api_client.get("/api/ai-capability/mcp-tools/")
    stats_response = api_client.get("/api/ai-capability/mcp-tools/stats/")

    assert list_response.status_code == 403
    assert stats_response.status_code == 403


@pytest.mark.django_db
def test_admin_toggle_mcp_tool_endpoint_updates_model(api_client, staff_user, mcp_tool_capability):
    api_client.force_authenticate(user=staff_user)

    response = api_client.post(
        f"/api/ai-capability/mcp-tools/{mcp_tool_capability.capability_key}/toggle/enabled_for_terminal/",
        {},
        format="json",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["changed_flag"] == "enabled_for_terminal"
    assert data["changed_value"] is True
    mcp_tool_capability.refresh_from_db()
    assert mcp_tool_capability.enabled_for_terminal is True


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
def test_api_dispatcher_filters_default_account_from_public_fund_ranking(regular_user):
    dispatcher = CapabilityExecutionDispatcher()
    capability = CapabilityCatalogModel.objects.update_or_create(
        capability_key="api.get.api.fund.rank",
        defaults={
            "source_type": "api",
            "source_ref": "GET api/fund/rank/",
            "name": "Get Fund Rank",
            "summary": "获取基金排名",
            "route_group": "read_api",
            "category": "fund",
            "input_schema": {
                "type": "object",
                "properties": {
                    "regime": {"type": "string"},
                    "max_count": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            "execution_target": {
                "type": "api",
                "method": "GET",
                "path": "api/fund/rank/",
            },
            "risk_level": "safe",
            "requires_confirmation": False,
            "enabled_for_routing": True,
            "enabled_for_terminal": True,
            "enabled_for_chat": False,
            "enabled_for_agent": True,
            "visibility": "internal",
        },
    )[0].to_entity()
    context = type(
        "Ctx",
        (),
        {
            "context": {
                "params": {"regime": "Recovery", "account_id": 365},
                "default_account_id": 365,
            },
            "user_id": regular_user.id,
        },
    )()

    with patch(
        "apps.fund.application.interface_services.rank_funds",
        return_value=[],
    ):
        result = dispatcher._execute_api(capability, context=context)

    assert result["metadata"]["status_code"] == 200
    assert result["result"] == {
        "success": True,
        "regime": "Recovery",
        "count": 0,
        "funds": [],
    }
    assert context.context["params"] == {"regime": "Recovery"}
