from datetime import timedelta

import pytest
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.account.application.tasks import send_database_backup_email_task
from apps.account.infrastructure.backup_delivery_projection import (
    get_backup_delivery_settings,
)
from apps.account.infrastructure.backup_service import (
    BACKUP_FILE_MAGIC,
    generate_backup_archive,
    generate_download_token,
    get_backup_email_connection,
)
from apps.config_center.application.public import update_backup_delivery_settings
from apps.config_center.models import BackupDeliveryStateModel
from apps.data_center.application.interface_services import save_provider_settings_payload
from tests.support.runtime_config import configure_critical_runtime


@pytest.fixture(autouse=True)
def _encryption_key(settings) -> None:
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = "backup-email-test-key"


def _configure_backup_settings(**overrides):
    configure_critical_runtime()
    save_provider_settings_payload(
        default_source="akshare",
        enable_failover=True,
        failover_tolerance=0.01,
        actor="backup-test-bootstrap",
    )
    payload = {
        "backup_enabled": True,
        "backup_email": "admin@example.com",
        "backup_app_base_url": "http://testserver",
        "backup_mail_from_email": "noreply@example.com",
        "backup_smtp_host": "smtp.example.com",
        "backup_smtp_port": 587,
        "backup_smtp_username": "mailer",
        "backup_smtp_use_tls": True,
        "backup_smtp_use_ssl": False,
        "backup_interval_days": 7,
        "backup_link_ttl_days": 2,
        "backup_password_hint": "test hint",
        "backup_archive_password": "secret-123",
        "backup_smtp_password": "smtp-secret",
    }
    payload.update(overrides)
    update_backup_delivery_settings(payload, actor="backup-component-test")
    return get_backup_delivery_settings()


@pytest.mark.django_db(transaction=True)
def test_config_center_can_roundtrip_backup_password():
    settings_obj = _configure_backup_settings()

    assert settings_obj.archive_password == "secret-123"
    assert settings_obj.smtp_password == "smtp-secret"


@pytest.mark.django_db(transaction=True)
def test_generate_backup_archive_returns_encrypted_package():
    settings_obj = _configure_backup_settings()

    archive = generate_backup_archive(settings_obj)

    assert archive.filename.endswith(".agbk")
    assert archive.content.startswith(BACKUP_FILE_MAGIC)


@pytest.mark.django_db(transaction=True)
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    APP_BASE_URL="http://testserver",
)
def test_backup_email_task_sends_download_link(client):
    _configure_backup_settings()

    result = send_database_backup_email_task()

    assert result["status"] == "sent"
    assert len(mail.outbox) == 1
    assert "http://testserver/admin/db-backup/" in mail.outbox[0].body


@pytest.mark.django_db(transaction=True)
def test_backup_download_view_returns_file(client):
    settings_obj = _configure_backup_settings()

    token = generate_download_token(settings_obj)
    response = client.get(reverse("admin-db-backup-download", kwargs={"token": token}))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/octet-stream"
    response.close()

    replay = client.get(reverse("admin-db-backup-download", kwargs={"token": token}))
    assert replay.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_generating_new_backup_link_revokes_previous_link(client):
    settings_obj = _configure_backup_settings()

    old_token = generate_download_token(settings_obj)
    current_token = generate_download_token(settings_obj)

    old_response = client.get(reverse("admin-db-backup-download", kwargs={"token": old_token}))
    assert old_response.status_code == 404

    current_response = client.get(
        reverse("admin-db-backup-download", kwargs={"token": current_token})
    )
    assert current_response.status_code == 200
    current_response.close()


@pytest.mark.django_db(transaction=True)
def test_persisted_backup_link_expiry_is_enforced(client):
    settings_obj = _configure_backup_settings()
    token = generate_download_token(settings_obj)
    state = BackupDeliveryStateModel._default_manager.get(pk=1)
    state.download_token_expires_at = timezone.now() - timedelta(seconds=1)
    state.save(update_fields=["download_token_expires_at", "updated_at"])

    response = client.get(reverse("admin-db-backup-download", kwargs={"token": token}))

    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
@override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
def test_backup_email_connection_uses_runtime_admin_config():
    settings_obj = _configure_backup_settings(
        backup_smtp_port=465,
        backup_smtp_use_tls=False,
        backup_smtp_use_ssl=True,
    )

    connection = get_backup_email_connection(settings_obj)

    assert connection.host == "smtp.example.com"
    assert connection.port == 465
    assert connection.username == "mailer"
    assert connection.password == "smtp-secret"
    assert connection.use_ssl is True
