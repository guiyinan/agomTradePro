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
        "连接方式:",
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


def _assert_publisher_page_contract(response) -> str:
    return _assert_html_contract(
        response,
        "Data Center — Publishers",
        "发布机构代码表与别名治理入口",
        "Publisher Catalog",
        "publisher_code",
        "publisher_codes",
        'id="publisher-list"',
        "/api/data-center/publishers/",
        "data_center_list_publishers",
        "data_center_update_publisher",
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
def test_tushare_transport_mode_is_explicit_safe_and_preserves_provider_config(admin_client):
    create_response = admin_client.post(
        "/api/data-center/providers/",
        data=json.dumps(
            {
                "name": "Tushare Relay",
                "source_type": "tushare",
                "api_key": "stored-relay-key",
                "http_url": "https://relay.example.com/tushare/pro",
                "tushare_request_mode": "unified_relay",
                "extra_config": {"health_metrics": {"success_count": 12}},
            }
        ),
        content_type="application/json",
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert "api_key" not in created
    assert created["has_api_key"] is True
    assert created["tushare_request_mode"] == "unified_relay"
    assert created["tushare_request_mode_label"] == "统一中继"

    provider_id = created["id"]
    update_response = admin_client.patch(
        f"/api/data-center/providers/{provider_id}/",
        data=json.dumps(
            {
                "api_key": "",
                "tushare_request_mode": "sdk_path",
                "clear_service_address": True,
            }
        ),
        content_type="application/json",
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["http_url"] == ""
    assert updated["tushare_request_mode"] == "sdk_path"
    assert updated["tushare_request_mode_label"] == "标准 Tushare"

    config = ProviderConfigModel.objects.get(id=provider_id)
    assert config.api_key == "stored-relay-key"
    assert config.http_url == ""
    assert config.extra_config == {
        "health_metrics": {"success_count": 12},
        "tushare_request_mode": "sdk_path",
    }


@pytest.mark.django_db
def test_multiple_active_tushare_routes_can_be_configured_in_parallel(admin_client):
    routes = [
        {
            "name": "Tushare Primary SDK",
            "source_type": "tushare",
            "priority": 10,
            "api_key": "primary-token",
            "http_url": "https://sdk-relay.example.test",
            "tushare_request_mode": "sdk_path",
        },
        {
            "name": "Tushare Unified Relay",
            "source_type": "tushare",
            "priority": 20,
            "api_key": "relay-token",
            "http_url": "https://relay.example.test/tushare/pro",
            "tushare_request_mode": "unified_relay",
        },
    ]

    responses = [
        admin_client.post(
            "/api/data-center/providers/",
            data=json.dumps(route),
            content_type="application/json",
        )
        for route in routes
    ]

    assert [response.status_code for response in responses] == [201, 201]
    stored = ProviderConfigModel.objects.filter(name__in=[route["name"] for route in routes])
    assert stored.count() == 2
    assert set(stored.values_list("source_type", flat=True)) == {"tushare"}
    assert list(stored.order_by("priority").values_list("name", flat=True)) == [
        "Tushare Primary SDK",
        "Tushare Unified Relay",
    ]


@pytest.mark.django_db
def test_unified_tushare_transport_requires_a_service_address(admin_client):
    response = admin_client.post(
        "/api/data-center/providers/",
        data=json.dumps(
            {
                "name": "Incomplete Relay",
                "source_type": "tushare",
                "api_key": "relay-key",
                "tushare_request_mode": "unified_relay",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["details"]["http_url"] == "统一中继连接必须填写服务地址。"


@pytest.mark.django_db
def test_tushare_transport_field_is_rejected_for_other_providers(admin_client):
    response = admin_client.post(
        "/api/data-center/providers/",
        data=json.dumps(
            {
                "name": "QMT Local",
                "source_type": "qmt",
                "tushare_request_mode": "unified_relay",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["details"]["tushare_request_mode"] == "连接方式仅适用于 Tushare 服务商。"


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
def test_data_center_publisher_page_renders_management_console(admin_client):
    response = admin_client.get("/data-center/publishers/")

    _assert_publisher_page_contract(response)


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

    class _UseCase:
        def execute(self, provider_id):
            return _Result()

    mocker.patch(
        "apps.data_center.interface.api_views.make_run_provider_connection_test_use_case",
        return_value=_UseCase(),
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
    assert client.get("/api" + "/macro/datasources/").status_code == 404
