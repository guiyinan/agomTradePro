import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.ai_capability.infrastructure.models import CapabilityCatalogModel


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def admin_user(db):
    user = User.objects.create_user(username="mcp_admin_page", password="test123", is_staff=True, is_superuser=True)
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
        input_schema={"type": "object", "properties": {}},
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


@pytest.mark.django_db
def test_toggle_mcp_tool_flag_updates_model(client, admin_user, mcp_tool):
    client.force_login(admin_user)
    response = client.post(f"/settings/mcp-tools/{mcp_tool.capability_key}/toggle/enabled_for_terminal/")
    assert response.status_code == 302
    mcp_tool.refresh_from_db()
    assert mcp_tool.enabled_for_terminal is False
