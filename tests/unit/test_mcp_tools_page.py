import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.account.infrastructure.models import SystemSettingsModel, UserAccessTokenModel
from apps.ai_capability.infrastructure.models import CapabilityCatalogModel


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def admin_user(db):
    user = User.objects.create_user(
        username="mcp_admin_page", password="test123", is_staff=True, is_superuser=True
    )
    profile = user.account_profile
    profile.approval_status = "approved"
    profile.rbac_role = "admin"
    profile.mcp_enabled = True
    profile.save(update_fields=["approval_status", "rbac_role", "mcp_enabled", "updated_at"])
    return user


@pytest.fixture
def regular_user(db):
    user = User.objects.create_user(username="mcp_regular_page", password="test123", is_staff=False)
    profile = user.account_profile
    profile.approval_status = "approved"
    profile.rbac_role = "read_only"
    profile.save(update_fields=["approval_status", "rbac_role", "updated_at"])
    return user


@pytest.fixture
def mcp_tool(db):
    return CapabilityCatalogModel.objects.create(
        capability_key="mcp_tool.list_signals",
        source_type="mcp_tool",
        source_ref="list_signals",
        name="list_signals",
        summary="List signal records",
        route_group="tool",
        category="mcp",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum rows",
                }
            },
        },
        execution_target={"type": "mcp_tool", "tool_name": "list_signals"},
        risk_level="safe",
        requires_mcp=True,
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=True,
        enabled_for_agent=True,
        auto_collected=True,
        review_status="auto",
    )


@pytest.mark.django_db
def test_mcp_tools_page_requires_admin(client, regular_user):
    client.force_login(regular_user)
    response = client.get("/settings/mcp-tools/")
    assert response.status_code == 302


@pytest.mark.django_db
def test_mcp_tools_page_renders_for_admin(client, admin_user, mcp_tool):
    client.force_login(admin_user)
    response = client.get("/settings/mcp-tools/")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "MCP 工具管理" in content
    assert "list_signals" in content
    assert "返回设置中心" in content
    assert "当前页属于系统级能力治理与开关配置" in content
    assert '"type": "object"' in content
    assert '"limit"' in content
    assert "已启用" in content


@pytest.mark.django_db
def test_capability_gateway_page_renders_for_regular_user(client, regular_user, mcp_tool):
    client.force_login(regular_user)

    response = client.get("/settings/capability-gateway/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "能力路由接入" in content
    assert "/api/ai-capability/route/" in content
    assert "测试统一路由" not in content
    assert "MCP 接入说明" in content
    assert "Capability Router" in content
    assert "发给 Agent 的启动 Prompt" in content
    assert "Token access level" in content


@pytest.mark.django_db
def test_capability_gateway_page_includes_copy_ready_agent_prompt_with_visible_token(
    client, regular_user
):
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.allow_token_plaintext_view = True
    settings_obj.save(update_fields=["allow_token_plaintext_view"])
    _, raw_key = UserAccessTokenModel.create_token(
        user=regular_user,
        name="gateway-codex",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    client.force_login(regular_user)
    response = client.get("/settings/capability-gateway/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert raw_key in content
    assert "复制 Prompt" in content
    assert "gateway-codex" in content
    assert "当前 prompt 已包含可用 Token" in content


@pytest.mark.django_db
def test_toggle_mcp_tool_flag_updates_model(client, admin_user, mcp_tool):
    client.force_login(admin_user)
    response = client.post(
        f"/settings/mcp-tools/{mcp_tool.capability_key}/toggle/enabled_for_terminal/"
    )
    assert response.status_code == 302
    mcp_tool.refresh_from_db()
    assert mcp_tool.enabled_for_terminal is False
