import json
from datetime import UTC, datetime

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.data_center.infrastructure.models import ProviderConfigModel


def _response_text(response) -> str:
    return response.content.decode("utf-8")


def _assert_html_contract(response, *fragments: str) -> str:
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")

    content = _response_text(response)
    for fragment in fragments:
        assert fragment in content
    return content


def _assert_provider_config_page_contract(response) -> str:
    return _assert_html_contract(
        response,
        "Data Center — Providers",
        "数据中台 — Provider 配置",
        "统一数据源配置入口",
        "刷新列表",
        "运行状态",
        "设置中心",
        'id="provider-list"',
        "/api/data-center/providers/",
        "/data-center/monitor/",
        "testProvider",
    )


def _assert_monitor_page_contract(response) -> str:
    return _assert_html_contract(
        response,
        "Data Center — Monitor",
        "数据中台 — 运行状态",
        "查看所有已注册 Provider 的实时健康状态",
        "刷新状态",
        "Provider 配置",
        'id="status-list"',
        "/api/data-center/providers/status/",
        "/data-center/providers/",
        "loadStatus",
    )


@pytest.fixture
def admin_client(db):
    user = User.objects.create_user(
        username="data_center_admin",
        password="pass1234",
        is_staff=True,
        is_superuser=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_data_center_provider_api_create_and_update_http_url(admin_client):
    create_response = admin_client.post(
        "/api/data-center/providers/",
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

    provider_id = payload["id"]
    update_response = admin_client.patch(
        f"/api/data-center/providers/{provider_id}/",
        data=json.dumps({"http_url": "https://proxy-2.example.com"}),
        content_type="application/json",
    )

    assert update_response.status_code == 200
    assert update_response.json()["http_url"] == "https://proxy-2.example.com"

    config = ProviderConfigModel.objects.get(id=provider_id)
    assert config.http_url == "https://proxy-2.example.com"


@pytest.mark.django_db
def test_config_center_snapshot_exposes_data_center_provider_summary(admin_client):
    ProviderConfigModel.objects.create(
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
    summary = items["data_center_providers"]["summary"]
    assert summary["custom_http_url_count"] == 1
    assert summary["default_source"] == "akshare"


@pytest.mark.django_db
def test_data_center_provider_api_accepts_qmt_source_with_extra_config(admin_client):
    response = admin_client.post(
        "/api/data-center/providers/",
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
def test_data_center_provider_page_renders_canonical_entry(admin_client):
    response = admin_client.get("/data-center/providers/")

    _assert_provider_config_page_contract(response)


@pytest.mark.django_db
def test_data_center_monitor_page_renders_runtime_status_entry(admin_client):
    response = admin_client.get("/data-center/monitor/")

    _assert_monitor_page_contract(response)


@pytest.mark.django_db
def test_data_center_provider_test_connection_endpoint_returns_probe_logs(admin_client, mocker):
    provider = ProviderConfigModel.objects.create(
        name="Tushare Pro",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="test-token-123456",
    )

    class _Result:
        def to_dict(self):
            return {
                "success": True,
                "status": "success",
                "summary": "连接成功",
                "logs": ["[INFO] start", "[SUCCESS] ok"],
                "tested_at": datetime(2026, 4, 5, tzinfo=UTC),
            }

    mocker.patch(
        "apps.data_center.interface.api_views.RunProviderConnectionTestUseCase.execute",
        return_value=_Result(),
    )

    response = admin_client.post(f"/api/data-center/providers/{provider.id}/test/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["summary"] == "连接成功"
    assert payload["logs"] == ["[INFO] start", "[SUCCESS] ok"]


@pytest.mark.django_db
def test_legacy_macro_datasource_routes_are_removed(admin_client):
    client = Client(raise_request_exception=False)
    assert client.get("/macro/datasources/").status_code == 404
    assert client.get("/macro/datasources/new/").status_code == 404
    assert client.get("/api/macro/datasources/").status_code == 404
