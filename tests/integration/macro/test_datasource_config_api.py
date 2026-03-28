import json

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.macro.infrastructure.models import DataSourceConfig


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
