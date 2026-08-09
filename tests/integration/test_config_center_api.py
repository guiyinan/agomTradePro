import json

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.account.infrastructure.models import (
    AccountProfileModel,
    DocumentationModel,
    UserAccessTokenModel,
)
from apps.config_center.infrastructure.repositories import ConfigCenterSettingsRepository
from apps.data_center.application.interface_services import save_provider_settings_payload
from apps.data_center.infrastructure.models import ProviderConfigModel
from tests.support.runtime_config import configure_account_runtime


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


def _response_text(response) -> str:
    return response.content.decode("utf-8")


def _assert_html_contract(response, *fragments: str) -> str:
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")

    content = _response_text(response)
    for fragment in fragments:
        assert fragment in content
    return content


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
@pytest.mark.parametrize(
    "path",
    (
        "/api/system/config-capabilities/",
        "/api/system/config-center/qlib/runtime/",
        "/api/system/config-center/qlib/training-profiles/",
        "/api/system/config-center/qlib/alpha-universes/",
        "/api/system/config-center/qlib/alpha-universes/example/members/",
        "/api/system/config-center/qlib/training-runs/",
        "/api/system/config-center/qlib/training-runs/example/",
    ),
)
def test_config_center_governed_read_candidates_require_staff(normal_client, path):
    response = normal_client.get(path)

    assert response.status_code == 403


@pytest.mark.django_db
def test_config_center_snapshot_returns_sections(staff_client):
    response = staff_client.get("/api/system/config-center/")
    assert response.status_code == 200

    payload = response.json()
    assert payload["success"] is True
    assert "sections" in payload["data"]
    item_keys = {
        item["key"] for section in payload["data"]["sections"] for item in section["items"]
    }
    assert "agent_runtime_operator" in item_keys
    assert "valuation_repair" in item_keys
    assert "beta_gate" in item_keys
    assert "account_settings" in item_keys
    assert "mcp_guide" in item_keys
    assert "system_settings" in item_keys
    assert "data_center_providers" in item_keys
    assert "data_center_runtime" in item_keys


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
    assert "mcp_guide" in keys
    assert "data_center_providers" in keys
    assert "data_center_runtime" in keys


@pytest.mark.django_db
def test_config_center_snapshot_includes_data_center_runtime_summary(staff_client, monkeypatch):
    ProviderConfigModel.objects.create(
        name="eastmoney-main",
        source_type="eastmoney",
        is_active=True,
        priority=1,
    )
    ProviderConfigModel.objects.create(
        name="tushare-main",
        source_type="tushare",
        is_active=True,
        priority=2,
    )

    class _Snapshot:
        def __init__(self, provider_name, status):
            self.provider_name = provider_name
            self.status = status

        def to_dict(self):
            return {
                "provider_name": self.provider_name,
                "capability": "realtime_quote",
                "status": self.status,
                "consecutive_failures": 0,
                "last_success_at": None,
                "avg_latency_ms": None,
            }

    class _Registry:
        def get_all_statuses(self):
            return [_Snapshot("eastmoney-main", "degraded"), _Snapshot("tushare-main", "healthy")]

    monkeypatch.setattr("apps.data_center.provider_runtime.get_registry", lambda: _Registry())

    response = staff_client.get("/api/system/config-center/")

    assert response.status_code == 200
    items = {
        item["key"]: item
        for section in response.json()["data"]["sections"]
        for item in section["items"]
    }
    runtime_item = items["data_center_runtime"]
    assert runtime_item["status"] == "attention"
    assert runtime_item["summary"]["configured_provider_count"] == 2
    assert runtime_item["summary"]["runtime_provider_count"] == 2
    assert runtime_item["summary"]["healthy_snapshot_count"] == 1


@pytest.mark.django_db
def test_config_center_snapshot_treats_data_center_provider_config_as_configured(staff_client):
    ProviderConfigModel.objects.create(
        name="akshare-main",
        source_type="akshare",
        is_active=True,
        priority=1,
    )
    save_provider_settings_payload(
        default_source="akshare",
        enable_failover=True,
        failover_tolerance=0.01,
        actor="config-center-integration-test",
    )

    response = staff_client.get("/api/system/config-center/")

    assert response.status_code == 200
    items = {
        item["key"]: item
        for section in response.json()["data"]["sections"]
        for item in section["items"]
    }
    provider_item = items["data_center_providers"]
    assert provider_item["status"] == "configured"
    assert provider_item["summary"]["total_providers"] >= 1
    assert "akshare" in provider_item["summary"]["source_types"]
    assert provider_item["summary"]["default_source"] == "akshare"


@pytest.mark.django_db
def test_ops_center_page_is_single_entry_for_normal_user(normal_client):
    response = normal_client.get("/settings/")

    _assert_html_contract(
        response,
        "设置中心 - AgomTradePro",
        "设置中心",
        "统一入口",
        "账户设置",
        "MCP 接入说明",
    )


@pytest.mark.django_db
def test_ops_center_page_shows_system_settings_for_staff(staff_client):
    response = staff_client.get("/settings/")

    _assert_html_contract(
        response,
        "设置中心 - AgomTradePro",
        "设置中心",
        "统一入口",
        "系统设置",
    )


@pytest.mark.django_db
def test_admin_console_requires_superuser(staff_client):
    response = staff_client.get("/admin-console/")

    assert response.status_code == 302


@pytest.mark.django_db
def test_admin_console_page_renders_key_admin_entries(superuser_client):
    response = superuser_client.get("/admin-console/")

    _assert_html_contract(
        response,
        "管理控制台",
        "用户管理",
        "Token 管理",
        "Alpha 推理管理",
        "Qlib 基础数据管理",
        "集中风控中心",
        "Agent 任务中心",
        "Agent 提案审批",
        "能力路由接入",
        "Qlib 配置与训练",
        "生产就绪监视器",
        "计划任务中心",
        "服务器日志",
        "Django Admin",
    )


@pytest.mark.django_db
def test_settings_center_features_recent_staff_surfaces(staff_client):
    response = staff_client.get("/settings/")

    assert response.status_code == 200
    featured_keys = [item["key"] for item in response.context["featured_items"]]
    assert "risk_center" in featured_keys
    assert "agent_runtime_operator" in featured_keys
    assert "ai_provider" in featured_keys


@pytest.mark.django_db
def test_base_navigation_exposes_admin_console_for_superuser(superuser_client):
    response = superuser_client.get("/settings/")

    _assert_html_contract(response, "设置中心 - AgomTradePro", "管理控制台")


@pytest.mark.django_db
def test_base_navigation_uses_platform_help_and_ops_grouping_for_superuser(superuser_client):
    response = superuser_client.get("/settings/")

    content = _assert_html_contract(response, "设置中心 - AgomTradePro")
    assert "平台" in content
    assert "帮助" in content
    assert "运维" in content
    assert "MCP 工具" in content
    assert "AI服务" not in content


@pytest.mark.django_db
def test_base_navigation_exposes_alpha_ops_for_staff(staff_client):
    response = staff_client.get("/settings/")

    _assert_html_contract(
        response,
        "设置中心 - AgomTradePro",
        "Alpha 推理管理",
        "Qlib 基础数据管理",
    )


@pytest.mark.django_db
def test_base_navigation_exposes_recent_operations_only_to_staff(staff_client, normal_client):
    staff_response = staff_client.get("/settings/")
    normal_response = normal_client.get("/settings/")

    staff_content = _assert_html_contract(
        staff_response,
        "集中风控中心",
        "实时监控工作台",
        "Agent 任务中心",
        "Agent 提案审批",
        "Qlib 配置与训练",
    )
    normal_content = _response_text(normal_response)

    assert "集中风控中心" in staff_content
    assert "集中风控中心" not in normal_content
    assert 'href="/settings/mcp-tools/"' not in normal_content


@pytest.mark.django_db
def test_alpha_ops_pages_require_staff(normal_client):
    response = normal_client.get("/alpha/ops/inference/")
    assert response.status_code == 403

    response = normal_client.get("/alpha/ops/qlib-data/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_alpha_ops_pages_render_for_staff(staff_client):
    response = staff_client.get("/alpha/ops/inference/")
    _assert_html_contract(response, "Alpha 推理管理", "Qlib Model Registry", "当前激活模型")

    response = staff_client.get("/alpha/ops/qlib-data/")
    _assert_html_contract(response, "Qlib 基础数据管理", "本地数据状态", "刷新 Universe 数据")


@pytest.mark.django_db
def test_user_management_page_uses_admin_console_language(superuser_client):
    response = superuser_client.get("/account/admin/users/")

    content = _assert_html_contract(response, "用户管理", "返回管理控制台")
    assert "返回管理控制台" in content
    assert "/tui/?screen=identity-access.user-governance" in content
    assert "当前 Classic 页面仅在兼容期内保留" in content
    assert "系统设置" in content


@pytest.mark.django_db
def test_token_management_page_uses_admin_console_language(superuser_client):
    response = superuser_client.get("/account/admin/tokens/")

    content = _assert_html_contract(response, "Token 管理", "返回管理控制台")
    assert "/tui/?screen=capability-router.admin-access" in content
    assert "当前 Classic 页面仅在兼容期内保留" in content
    assert "返回管理控制台" in content
    assert "MCP 用户、令牌与开关治理已迁入 TUI" in content
    assert "用户管理" in content


@pytest.mark.django_db
def test_token_management_page_shows_recoverable_tokens_and_mobile_card_labels(
    superuser_client,
):
    user = User.objects.get(username="config_admin")
    configure_account_runtime(allow_token_plaintext_view=True)
    _, raw_key = UserAccessTokenModel.create_token(
        user=user,
        name="classic-visible-token",
        created_by=user,
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )

    response = superuser_client.get("/account/admin/tokens/")

    content = _assert_html_contract(response, "classic-visible-token", raw_key)
    assert "data-token-secret" in content
    assert 'data-label="有效 Token"' in content
    assert "overflow-x: auto" in content
    assert "@media (max-width: 760px)" in content


@pytest.mark.django_db
def test_system_settings_page_uses_settings_center_language(superuser_client):
    response = superuser_client.get("/account/admin/settings/")

    content = _assert_html_contract(response, "系统设置", "返回设置中心")
    assert "设置中心工作流" in content
    assert "返回设置中心" in content
    assert "/tui/?screen=system.settings" in content
    assert "当前 Classic 页面仅在兼容期内保留" in content


@pytest.mark.django_db
def test_system_governance_settings_api_is_admin_only_and_updates_allowlist(
    normal_client,
    staff_client,
):
    forbidden = normal_client.get("/api/system/config-center/settings/")
    assert forbidden.status_code == 403

    configure_account_runtime()
    ConfigCenterSettingsRepository().update_runtime_config(
        {"alpha_fixed_provider": "cache"},
        actor="config-center-integration-test",
    )

    current = staff_client.get("/api/system/config-center/settings/")
    assert current.status_code == 200
    assert current["Content-Type"].startswith("application/json")
    assert "require_user_approval" in current.json()
    assert "benchmark_code_map" in current.json()

    updated = staff_client.put(
        "/api/system/config-center/settings/",
        data=json.dumps(
            {
                "require_user_approval": False,
                "market_color_convention": "us_market",
                "alpha_pool_mode": "market",
                "benchmark_code_map": {"equity_default_index": "000300.SH"},
                "asset_proxy_code_map": {"equity": "510300.SH"},
                "notes": "M2 system settings contract",
            }
        ),
        content_type="application/json",
    )

    assert updated.status_code == 200
    payload = updated.json()
    assert payload["require_user_approval"] is False
    assert payload["market_color_convention"] == "us_market"
    assert payload["market_color_label"] == "美股绿涨红跌"
    assert payload["benchmark_code_map"] == {"equity_default_index": "000300.SH"}
    assert payload["asset_proxy_code_map"] == {"equity": "510300.SH"}


@pytest.mark.django_db
def test_system_settings_tui_screen_exposes_read_and_confirmed_update(
    superuser_client,
):
    response = superuser_client.get("/api/tui/screens/system.settings/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["key"] == "system.settings"
    assert payload["screen"]["audience"] == "admin"
    actions = {action["key"]: action for action in payload["actions"]}
    assert set(actions) == {"system-settings.read", "system-settings.update"}
    assert actions["system-settings.update"]["confirmation_required"] is True
    field_by_key = {field["key"]: field for field in actions["system-settings.update"]["fields"]}
    assert field_by_key["benchmark_code_map"]["value_type"] == "object"
    assert field_by_key["asset_proxy_code_map"]["input_type"] == "textarea"


@pytest.mark.django_db
def test_server_logs_page_uses_admin_console_language(superuser_client):
    response = superuser_client.get("/admin/server-logs/")

    content = _assert_html_contract(response, "服务端实时日志", "返回管理控制台")
    assert "服务端实时日志" in content
    assert "返回管理控制台" in content
    assert "当前页属于管理控制台中的运维值守入口" in content


@pytest.mark.django_db
def test_docs_manage_page_uses_admin_console_language(superuser_client):
    response = superuser_client.get("/admin/docs/manage/")

    content = _assert_html_contract(response, "文档管理", "返回管理控制台")
    assert "文档管理" in content
    assert "返回管理控制台" in content
    assert "当前页属于管理控制台中的内容运维入口" in content


@pytest.mark.django_db
def test_docs_create_page_uses_admin_console_language(superuser_client):
    response = superuser_client.get("/admin/docs/edit/")

    content = _assert_html_contract(response, "新建文档", "返回管理控制台")
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

    content = _assert_html_contract(response, "编辑文档", "返回文档管理")
    assert "编辑文档" in content
    assert "返回文档管理" in content
    assert "删除" in content


@pytest.mark.django_db
def test_public_docs_list_uses_documentation_service():
    DocumentationModel.objects.create(
        title="公开文档",
        slug="public-doc",
        category="user_guide",
        content="# 文档",
        summary="公开摘要",
        order=1,
        is_published=True,
    )

    response = Client().get("/docs/")

    content = _assert_html_contract(response, "公开文档")
    assert "/docs/public-doc/" in content


@pytest.mark.django_db
def test_public_docs_detail_uses_documentation_service():
    DocumentationModel.objects.create(
        title="详情文档",
        slug="detail-doc",
        category="concept",
        content="# 详情",
        summary="详情摘要",
        order=1,
        is_published=True,
    )

    response = Client().get("/docs/detail-doc/")

    content = _assert_html_contract(response, "详情文档")
    assert "# 详情" in content


@pytest.mark.django_db
def test_ai_provider_manage_page_uses_settings_language(superuser_client):
    response = superuser_client.get("/ai/")

    content = _assert_html_contract(response, "AI接口管理", "返回设置中心")
    assert "AI接口管理" in content
    assert "返回设置中心" in content
    assert "当前页属于系统级 AI 能力配置入口" in content


@pytest.mark.django_db
def test_prompt_manage_page_uses_settings_language(superuser_client):
    response = superuser_client.get("/prompt/manage/")

    content = _assert_html_contract(response, "Prompt 模板管理", "返回设置中心")
    assert "Prompt 模板管理" in content
    assert "返回设置中心" in content
    assert "当前页属于系统级 AI 模板与执行配置入口" in content


@pytest.mark.django_db
def test_rss_manage_page_uses_module_operations_language(superuser_client):
    response = superuser_client.get("/policy/rss/sources/")

    content = _assert_html_contract(response, "RSS 源管理", "政策工作台")
    assert "RSS 源管理" in content
    assert "政策工作台" in content
    assert "当前页属于政策摄入链路的运维配置页" in content
