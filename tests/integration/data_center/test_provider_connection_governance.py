"""Governance contracts for provider connection tests."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client, override_settings

from apps.data_center.domain.entities import ConnectionTestResult
from apps.data_center.infrastructure.models import ProviderConfigModel


@pytest.fixture
def staff_client(db) -> Client:
    user = User.objects.create_user(
        username="provider_probe_staff",
        password="pass1234",
        is_staff=True,
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_provider_connection_test_rejects_non_staff(authenticated_client: Client) -> None:
    provider = ProviderConfigModel.objects.create(
        name="staff-only-provider",
        source_type="tushare",
        api_key="staff-only-token",
    )

    response = authenticated_client.post(f"/api/data-center/providers/{provider.id}/test/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_provider_connection_test_persists_redacted_health_metadata(
    staff_client: Client,
    mocker,
) -> None:
    api_key = "probe-token-should-never-escape"
    api_secret = "probe-secret-should-never-escape"
    provider = ProviderConfigModel.objects.create(
        name="redaction-provider",
        source_type="tushare",
        api_key=api_key,
        api_secret=api_secret,
        extra_config={},
    )
    probe = mocker.patch(
        "apps.data_center.application.interface_services.run_data_center_connection_test",
        return_value=ConnectionTestResult(
            success=False,
            status="error",
            summary=f"request failed with token={api_key}",
            logs=[
                f"[ERROR] api_key={api_key}",
                f"[ERROR] api_secret={api_secret}",
            ],
        ),
    )

    response = staff_client.post(f"/api/data-center/providers/{provider.id}/test/")

    assert response.status_code == 200
    payload_text = response.content.decode("utf-8")
    assert api_key not in payload_text
    assert api_secret not in payload_text
    assert payload_text.count("[REDACTED]") >= 3
    probe.assert_called_once()

    provider.refresh_from_db()
    assert provider.extra_config["provider_last_status"] == "degraded"
    assert api_key not in provider.extra_config["provider_last_error"]
    assert provider.extra_config["provider_last_error"].endswith("[REDACTED]")


@pytest.mark.django_db
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="provider-api-test-key")
def test_provider_detail_and_create_responses_never_echo_credentials(
    staff_client: Client,
) -> None:
    api_key = "provider-api-key"
    api_secret = "provider-api-secret"
    create_response = staff_client.post(
        "/api/data-center/providers/",
        data={
            "name": "safe-provider-response",
            "source_type": "tushare",
            "api_key": api_key,
            "api_secret": api_secret,
            "extra_config": {
                "client_path": "C:/qmt",
                "nested": {"token": "nested-provider-token", "timeout": 10},
            },
        },
        content_type="application/json",
    )

    assert create_response.status_code == 201
    create_payload = create_response.json()
    assert "api_key" not in create_payload
    assert "api_secret" not in create_payload
    assert create_payload["has_api_key"] is True
    assert create_payload["has_api_secret"] is True
    assert create_payload["extra_config"] == {
        "client_path": "C:/qmt",
        "nested": {"timeout": 10},
        "tushare_request_mode": "sdk_path",
    }
    assert "nested-provider-token" not in create_response.content.decode("utf-8")

    detail_response = staff_client.get(f"/api/data-center/providers/{create_payload['id']}/")
    assert detail_response.status_code == 200
    assert api_key not in detail_response.content.decode("utf-8")
    assert api_secret not in detail_response.content.decode("utf-8")
