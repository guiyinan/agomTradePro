import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.account.infrastructure.models import AccountProfileModel
from apps.account.infrastructure.models import DocumentationModel


def _ensure_account_profile(user: User) -> None:
    AccountProfileModel.objects.get_or_create(
        user=user,
        defaults={
            "display_name": user.username,
            "risk_tolerance": "moderate",
            "approval_status": "approved",
            "user_agreement_accepted": True,
            "risk_warning_acknowledged": True,
        },
    )


@pytest.fixture
def staff_client(db):
    user = User.objects.create_user(username="config_staff", password="pass1234", is_staff=True)
    _ensure_account_profile(user)
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def superuser_client(db):
    user = User.objects.create_user(
        username="config_admin",
        password="pass1234",
        is_staff=True,
        is_superuser=True,
    )
    _ensure_account_profile(user)
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def normal_client(db):
    user = User.objects.create_user(username="config_normal", password="pass1234", is_staff=False)
    _ensure_account_profile(user)
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_config_center_snapshot_requires_staff(normal_client):
    response = normal_client.get("/api/system/config-center/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_config_center_snapshot_returns_sections(staff_client):
    response = staff_client.get("/api/system/config-center/")
    assert response.status_code == 200

    payload = response.json()
    assert payload["success"] is True
    assert "sections" in payload["data"]
    item_keys = {
        item["key"]
        for section in payload["data"]["sections"]
        for item in section["items"]
    }
    assert "agent_runtime_operator" in item_keys
    assert "valuation_repair" in item_keys
    assert "beta_gate" in item_keys
    assert "account_settings" in item_keys
    assert "system_settings" in item_keys


@pytest.mark.django_db
def test_config_capabilities_returns_known_entries(staff_client):
    response = staff_client.get("/api/system/config-capabilities/")
    assert response.status_code == 200

    payload = response.json()
    assert payload["success"] is True
    keys = {item["key"] for item in payload["data"]}
    assert "agent_runtime_operator" in keys
    assert "valuation_repair" in keys
    assert "trading_cost" in keys


@pytest.mark.django_db
def test_config_center_snapshot_includes_market_data_provider_summary(staff_client, monkeypatch):
    monkeypatch.setattr(
        "apps.market_data.interface.page_views.build_provider_dashboard",
        lambda: {
            "provider_count": 2,
            "healthy_provider_count": 1,
            "unhealthy_provider_count": 1,
            "providers": [
                {"name": "eastmoney", "healthy": False},
                {"name": "tushare", "healthy": True},
            ],
        },
    )

    response = staff_client.get("/api/system/config-center/")

    assert response.status_code == 200
    items = {
        item["key"]: item
        for section in response.json()["data"]["sections"]
        for item in section["items"]
    }
    market_data_item = items["market_data_providers"]
    assert market_data_item["status"] == "attention"
    assert market_data_item["summary"]["provider_count"] == 2
    assert market_data_item["summary"]["healthy_provider_count"] == 1


@pytest.mark.django_db
def test_config_center_snapshot_treats_builtin_macro_source_as_configured(staff_client):
    response = staff_client.get("/api/system/config-center/")

    assert response.status_code == 200
    items = {
        item["key"]: item
        for section in response.json()["data"]["sections"]
        for item in section["items"]
    }
    macro_item = items["macro_datasources"]
    assert macro_item["status"] == "configured"
    assert macro_item["summary"]["built_in_source_count"] >= 1
    assert "akshare" in macro_item["summary"]["built_in_sources"]
    assert macro_item["summary"]["default_data_source"] == "akshare"


@pytest.mark.django_db
def test_ops_center_page_is_single_entry_for_normal_user(normal_client):
    response = normal_client.get("/settings/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "设置中心" in content
    assert "统一入口" in content
    assert "账户设置" in content


@pytest.mark.django_db
def test_ops_center_page_shows_system_settings_for_staff(staff_client):
    response = staff_client.get("/settings/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "设置中心" in content
    assert "系统设置" in content


@pytest.mark.django_db
def test_admin_console_requires_superuser(staff_client):
    response = staff_client.get("/admin-console/")

    assert response.status_code == 302


@pytest.mark.django_db
def test_admin_console_page_renders_key_admin_entries(superuser_client):
    response = superuser_client.get("/admin-console/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "管理控制台" in content
    assert "用户管理" in content
    assert "Token 管理" in content
    assert "服务器日志" in content
    assert "Django Admin" in content


@pytest.mark.django_db
def test_base_navigation_exposes_admin_console_for_superuser(superuser_client):
    response = superuser_client.get("/settings/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "管理控制台" in content


@pytest.mark.django_db
def test_base_navigation_uses_platform_help_and_ops_grouping_for_superuser(superuser_client):
    response = superuser_client.get("/settings/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "平台" in content
    assert "帮助" in content
    assert "运维" in content
    assert "MCP 工具" in content
    assert "AI服务" not in content


@pytest.mark.django_db
def test_user_management_page_uses_admin_console_language(superuser_client):
    response = superuser_client.get("/account/admin/users/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "返回管理控制台" in content
    assert "管理控制台是管理员统一入口" in content
    assert "系统设置" in content


@pytest.mark.django_db
def test_token_management_page_uses_admin_console_language(superuser_client):
    response = superuser_client.get("/account/admin/tokens/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "返回管理控制台" in content
    assert "当前页面只负责 Token 与 MCP 开关" in content
    assert "用户管理" in content


@pytest.mark.django_db
def test_system_settings_page_uses_settings_center_language(superuser_client):
    response = superuser_client.get("/account/admin/settings/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "设置中心工作流" in content
    assert "返回设置中心" in content
    assert "不要把配置编辑和管理员值守混在一起" in content


@pytest.mark.django_db
def test_server_logs_page_uses_admin_console_language(superuser_client):
    response = superuser_client.get("/admin/server-logs/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "服务端实时日志" in content
    assert "返回管理控制台" in content
    assert "当前页属于管理控制台中的运维值守入口" in content


@pytest.mark.django_db
def test_docs_manage_page_uses_admin_console_language(superuser_client):
    response = superuser_client.get("/admin/docs/manage/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "文档管理" in content
    assert "返回管理控制台" in content
    assert "当前页属于管理控制台中的内容运维入口" in content


@pytest.mark.django_db
def test_docs_create_page_uses_admin_console_language(superuser_client):
    response = superuser_client.get("/admin/docs/edit/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "新建文档" in content
    assert "返回管理控制台" in content
    assert "当前页属于管理控制台中的内容编辑入口" in content


@pytest.mark.django_db
def test_docs_edit_page_uses_admin_console_language(superuser_client):
    doc = DocumentationModel.objects.create(
        title="系统说明",
        slug="system-overview",
        category="concept",
        content="# 概览",
        summary="摘要",
        order=1,
        is_published=True,
    )

    response = superuser_client.get(f"/admin/docs/edit/{doc.id}/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "编辑文档" in content
    assert "返回文档管理" in content
    assert "删除" in content


@pytest.mark.django_db
def test_ai_provider_manage_page_uses_settings_language(superuser_client):
    response = superuser_client.get("/ai/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "AI接口管理" in content
    assert "返回设置中心" in content
    assert "当前页属于系统级 AI 能力配置入口" in content


@pytest.mark.django_db
def test_prompt_manage_page_uses_settings_language(superuser_client):
    response = superuser_client.get("/prompt/manage/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Prompt 模板管理" in content
    assert "返回设置中心" in content
    assert "当前页属于系统级 AI 模板与执行配置入口" in content


@pytest.mark.django_db
def test_rss_manage_page_uses_module_operations_language(superuser_client):
    response = superuser_client.get("/policy/rss/sources/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "RSS 源管理" in content
    assert "政策工作台" in content
    assert "当前页属于政策摄入链路的运维配置页" in content
