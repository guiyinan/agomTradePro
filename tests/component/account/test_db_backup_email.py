from datetime import timedelta

import pytest
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.account.application.tasks import send_database_backup_email_task
from apps.account.infrastructure.backup_delivery_projection import (
    BackupDeliveryRuntimeSettings,
    get_backup_delivery_settings,
)
from apps.account.infrastructure.backup_service import (
    BACKUP_FILE_MAGIC,
    generate_backup_archive,
    generate_download_token,
    get_backup_email_connection,
)
from apps.config_center.application.public import update_backup_delivery_settings
from apps.config_center.models import BackupDeliveryStateModel, ConfigCenterSecretModel

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _encryption_key(settings) -> None:
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = "backup-delivery-component-key"


def _configure_backup(*, enabled: bool = True) -> BackupDeliveryRuntimeSettings:
    update_backup_delivery_settings(
        {
            "backup_enabled": enabled,
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
            "backup_archive_password": "secret-123",
            "backup_smtp_password": "smtp-secret",
        },
        actor="backup-component-test",
    )
    return get_backup_delivery_settings()


def test_backup_secrets_roundtrip_only_through_config_center() -> None:
    config = _configure_backup()

    assert config.archive_password == "secret-123"
    assert config.smtp_password == "smtp-secret"
    assert ConfigCenterSecretModel._default_manager.count() == 2


def test_generate_backup_archive_returns_encrypted_package() -> None:
    archive = generate_backup_archive(_configure_backup())

    assert archive.filename.endswith(".agbk")
    assert archive.content.startswith(BACKUP_FILE_MAGIC)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    APP_BASE_URL="http://testserver",
)
def test_backup_email_task_sends_download_link(client) -> None:
    _configure_backup()

    result = send_database_backup_email_task()

    assert result["status"] == "sent"
    assert len(mail.outbox) == 1
    assert "http://testserver/admin/db-backup/" in mail.outbox[0].body


def test_backup_download_view_returns_file(client) -> None:
    config = _configure_backup()
    token = generate_download_token(config)

    response = client.get(reverse("admin-db-backup-download", kwargs={"token": token}))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/octet-stream"
    response.close()
    replay = client.get(reverse("admin-db-backup-download", kwargs={"token": token}))
    assert replay.status_code == 404


def test_generating_new_backup_link_revokes_previous_link(client) -> None:
    config = _configure_backup()
    old_token = generate_download_token(config)
    current_token = generate_download_token(config)

    assert (
        client.get(reverse("admin-db-backup-download", kwargs={"token": old_token})).status_code
        == 404
    )
    current_response = client.get(
        reverse("admin-db-backup-download", kwargs={"token": current_token})
    )
    assert current_response.status_code == 200
    current_response.close()


def test_persisted_backup_link_expiry_is_enforced(client) -> None:
    token = generate_download_token(_configure_backup())
    state = BackupDeliveryStateModel._default_manager.get(pk=1)
    state.download_token_expires_at = timezone.now() - timedelta(seconds=1)
    state.save(update_fields=["download_token_expires_at", "updated_at"])

    response = client.get(reverse("admin-db-backup-download", kwargs={"token": token}))

    assert response.status_code == 404


@override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
def test_backup_email_connection_uses_runtime_admin_config() -> None:
    config = _configure_backup()
    config.backup_smtp_port = 465
    config.backup_smtp_use_tls = False
    config.backup_smtp_use_ssl = True

    connection = get_backup_email_connection(config)

    assert connection.host == "smtp.example.com"
    assert connection.port == 465
    assert connection.username == "mailer"
    assert connection.password == "smtp-secret"
    assert connection.use_ssl is True
