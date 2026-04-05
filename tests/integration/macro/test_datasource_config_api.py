import json
import time
from datetime import date
from unittest.mock import Mock

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.macro.infrastructure.models import DataProviderSettings, DataSourceConfig, MacroIndicator
from apps.macro.infrastructure.datasource_connection_tester import run_datasource_connection_test
from core.application.provider_inventory import build_unified_provider_inventory


@pytest.fixture
def admin_client(db):
    user = User.objects.create_user(
        username="macro_ds_admin",
        password="pass1234",
        is_staff=True,
        is_superuser=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_macro_datasource_api_create_and_update_http_url(admin_client):
    create_response = admin_client.post(
        "/api/macro/datasources/",
        data=json.dumps(
            {
                "name": "Tushare Pro",
                "source_type": "tushare",
                "is_active": True,
                "priority": 1,
                "api_key": "test-token",
                "http_url": "https://proxy.example.com",
                "api_endpoint": "",
                "api_secret": "",
                "extra_config": {},
                "description": "third-party tushare proxy",
            }
        ),
        content_type="application/json",
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["http_url"] == "https://proxy.example.com"

    source_id = payload["id"]
    update_response = admin_client.patch(
        f"/api/macro/datasources/{source_id}/",
        data=json.dumps({"http_url": "https://proxy-2.example.com"}),
        content_type="application/json",
    )

    assert update_response.status_code == 200
    assert update_response.json()["http_url"] == "https://proxy-2.example.com"

    config = DataSourceConfig.objects.get(id=source_id)
    assert config.http_url == "https://proxy-2.example.com"


@pytest.mark.django_db
def test_config_center_snapshot_exposes_custom_http_url_count(admin_client):
    DataSourceConfig.objects.create(
        name="Tushare Proxy",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="test-token",
        http_url="https://proxy.example.com",
    )

    response = admin_client.get("/api/system/config-center/")
    assert response.status_code == 200

    items = {
        item["key"]: item
        for section in response.json()["data"]["sections"]
        for item in section["items"]
    }
    summary = items["macro_datasources"]["summary"]
    assert summary["custom_http_url_count"] == 1


@pytest.mark.django_db
def test_macro_datasource_api_accepts_qmt_source_with_extra_config(admin_client):
    response = admin_client.post(
        "/api/macro/datasources/",
        data=json.dumps(
            {
                "name": "QMT Local",
                "source_type": "qmt",
                "is_active": True,
                "priority": 15,
                "api_key": "",
                "http_url": "",
                "api_endpoint": "",
                "api_secret": "",
                "extra_config": {
                    "client_path": "C:/qmt",
                    "data_dir": "D:/qmt/data",
                },
                "description": "local xtquant quote provider",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_type"] == "qmt"
    assert payload["extra_config"]["client_path"] == "C:/qmt"


@pytest.mark.django_db
def test_macro_datasource_page_highlights_tushare_configuration_entry(admin_client):
    response = admin_client.get("/macro/datasources/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "财经数据源配置" in content
    assert "数据源管理台" in content
    assert "Tushare Token / HTTP URL 就在这里配置" in content
    assert "运行时状态与快速测试" in content
    assert 'id="provider-status"' in content


@pytest.mark.django_db
def test_macro_datasource_page_supports_inline_edit_workbench(admin_client):
    source = DataSourceConfig.objects.create(
        name="Tushare Pro",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="test-token-123456",
        http_url="https://proxy.example.com",
        description="primary proxy",
    )

    response = admin_client.get(f"/macro/datasources/?edit={source.id}")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "数据源管理台" in content
    assert "配置工作台" in content
    assert "保存当前配置" in content
    assert f"?edit={source.id}" in content
    assert "完整表单" in content


@pytest.mark.django_db
def test_macro_datasource_page_renders_connection_test_button_and_modal_hook(admin_client):
    source = DataSourceConfig.objects.create(
        name="Tushare Pro",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="test-token-123456",
    )

    response = admin_client.get("/macro/datasources/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "测试连接" in content
    assert f"openDatasourceTestModal({source.id}, 'Tushare Pro')" in content
    assert "/api/macro/datasources/${sourceId}/test/" in content


@pytest.mark.django_db
def test_macro_datasource_page_create_mode_is_a_first_class_state(admin_client):
    DataSourceConfig.objects.create(
        name="Existing Source",
        source_type="akshare",
        is_active=True,
        priority=1,
    )

    response = admin_client.get("/macro/datasources/?mode=create")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "当前处于新建模式" in content
    assert "创建并启用配置" in content


@pytest.mark.django_db
def test_macro_datasource_page_zero_config_state_still_renders_workbench(admin_client):
    MacroIndicator.objects.create(
        code="CN_PMI",
        value=50.2,
        unit="指数",
        original_unit="指数",
        reporting_period=date(2026, 2, 1),
        period_type="M",
        source="akshare",
    )

    response = admin_client.get("/macro/datasources/?mode=create")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "统一 Provider 目录" in content
    assert "配置工作台" in content
    assert "创建并启用配置" in content
    assert "公开数据与系统内置源" in content
    assert "AKShare 公共接口" in content
    assert "默认抓取策略" in content
    assert "当前还没有可管理的数据源配置" in content
    assert "库里已有历史财经数据，但当前没有配置记录" in content
    assert 'href="#datasource-workbench"' in content
    assert DataProviderSettings.objects.count() == 1


@pytest.mark.django_db
def test_provider_inventory_marks_tushare_as_needs_config_when_failover_references_it(mocker):
    settings_obj = DataProviderSettings.load()
    settings_obj.default_data_source = "failover"
    settings_obj.save()

    eastmoney_status = Mock()
    eastmoney_status.to_dict.return_value = {
        "provider_name": "eastmoney",
        "capability": "realtime_quote",
        "is_healthy": True,
    }
    registry = Mock()
    registry.get_all_statuses.return_value = [eastmoney_status]
    mocker.patch("core.application.provider_inventory.get_registry", return_value=registry)

    inventory = {
        item["key"]: item
        for item in build_unified_provider_inventory()
    }

    assert inventory["tushare"]["macro_mode"] == "needs_config"
    assert inventory["tushare"]["access_category"] == "licensed"
    assert inventory["tushare"]["macro_config_summary"] == "策略已引用，但本页还未创建配置记录"
    assert inventory["eastmoney"]["macro_mode"] == "none"
    assert inventory["eastmoney"]["access_category"] == "public"
    assert inventory["eastmoney"]["config_surface_label"] == "统一数据源中心（只读 / 运行状态）"
    assert inventory["eastmoney"]["catalog_badge_label"] == "运行时已注册"
    assert inventory["eastmoney"]["macro_list_presence_label"] == "会显示在左侧只读列表"


@pytest.mark.django_db
def test_macro_datasource_page_separates_external_market_providers_from_macro_configs(admin_client, mocker):
    settings_obj = DataProviderSettings.load()
    settings_obj.default_data_source = "failover"
    settings_obj.save()

    eastmoney_status = Mock()
    eastmoney_status.to_dict.return_value = {
        "provider_name": "eastmoney",
        "capability": "realtime_quote",
        "is_healthy": True,
    }
    registry = Mock()
    registry.get_all_statuses.return_value = [eastmoney_status]
    mocker.patch("core.application.provider_inventory.get_registry", return_value=registry)

    response = admin_client.get("/macro/datasources/?mode=create")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "公开数据" in content
    assert "授权数据" in content
    assert "本地终端" in content
    assert "待补配置 / 只读 Provider" in content
    assert "?mode=create&amp;source_type=tushare&amp;name=Tushare Pro#datasource-workbench" in content
    assert "EastMoney / 东方财富" in content
    assert "运行时已注册" in content
    assert "会显示在左侧只读列表" in content
    assert "策略已引用，但本页还未创建配置记录" in content
    assert "它会出现在左侧“待补配置 / 只读 Provider”分区" in content
    assert "如果你准备立刻启用 `Tushare`" in content


@pytest.mark.django_db
def test_macro_datasource_page_prefills_tushare_create_form_from_pending_provider_link(admin_client):
    response = admin_client.get("/macro/datasources/?mode=create&source_type=tushare&name=Tushare%20Pro")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert 'value="Tushare Pro"' in content
    assert '<option value="tushare" selected>' in content


@pytest.mark.django_db
def test_macro_datasource_test_connection_endpoint_returns_probe_logs(admin_client, mocker):
    source = DataSourceConfig.objects.create(
        name="Tushare Pro",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="test-token-123456",
    )
    mocker.patch(
        "apps.macro.interface.views.config_api.RunDataSourceConnectionTestUseCase.execute",
        return_value={
            "success": True,
            "status": "success",
            "summary": "连接成功",
            "logs": ["[INFO] start", "[SUCCESS] ok"],
        },
    )

    response = admin_client.post(f"/api/macro/datasources/{source.id}/test/")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "status": "success",
        "summary": "连接成功",
        "logs": ["[INFO] start", "[SUCCESS] ok"],
    }


@pytest.mark.django_db
def test_datasource_connection_returns_timeout_instead_of_hanging(mocker):
    source = DataSourceConfig.objects.create(
        name="Tushare Pro",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="test-token-123456",
    )

    def _slow_probe(config, logs):
        logs.append("[INFO] 模拟慢探针启动")
        time.sleep(0.05)
        return {
            "success": True,
            "status": "success",
            "summary": "should not finish",
            "logs": logs,
        }

    mocker.patch(
        "apps.macro.infrastructure.datasource_connection_tester._test_tushare",
        side_effect=_slow_probe,
    )
    mocker.patch(
        "apps.macro.infrastructure.datasource_connection_tester._TEST_TIMEOUT_SECONDS",
        0.01,
    )

    result = run_datasource_connection_test(source)

    assert result["success"] is False
    assert result["status"] == "error"
    assert "超时" in result["summary"]
    assert any("模拟慢探针启动" in line for line in result["logs"])


@pytest.mark.django_db
def test_macro_datasource_page_inline_edit_updates_config(admin_client):
    source = DataSourceConfig.objects.create(
        name="AKShare",
        source_type="akshare",
        is_active=True,
        priority=2,
        api_key="",
        http_url="",
        api_endpoint="https://old.example.com",
        api_secret="",
        extra_config={},
        description="before update",
    )

    response = admin_client.post(
        f"/macro/datasources/?edit={source.id}",
        data={
            "name": "AKShare",
            "source_type": "akshare",
            "is_active": "on",
            "priority": 3,
            "api_endpoint": "https://new.example.com",
            "http_url": "",
            "api_key": "",
            "api_secret": "",
            "extra_config": "{}",
            "description": "updated inline",
        },
    )

    assert response.status_code == 302
    assert response["Location"].endswith(f"/macro/datasources/?edit={source.id}")

    source.refresh_from_db()
    assert source.priority == 3
    assert source.api_endpoint == "https://new.example.com"
    assert source.description == "updated inline"
