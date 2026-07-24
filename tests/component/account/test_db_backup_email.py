from datetime import timedelta

import pytest
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.account.application.tasks import send_database_backup_email_task
from apps.account.infrastructure.backup_service import (
    BACKUP_FILE_MAGIC,
    generate_backup_archive,
    generate_download_token,
    get_backup_email_connection,
)
from apps.account.infrastructure.models import SystemSettingsModel


@pytest.mark.django_db
def test_system_settings_can_roundtrip_backup_password():
    settings_obj = SystemSettingsModel.get_settings()

    settings_obj.set_backup_password("secret-123")
    settings_obj.set_backup_smtp_password("smtp-secret")

    assert settings_obj.backup_password_encrypted
    assert settings_obj.get_backup_password() == "secret-123"
    assert settings_obj.get_backup_smtp_password() == "smtp-secret"


@pytest.mark.django_db
def test_generate_backup_archive_returns_encrypted_package():
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.set_backup_password("secret-123")

    archive = generate_backup_archive(settings_obj)

    assert archive.filename.endswith(".agbk")
    assert archive.content.startswith(BACKUP_FILE_MAGIC)


@pytest.mark.django_db
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    APP_BASE_URL="http://testserver",
)
def test_backup_email_task_sends_download_link(client):
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.backup_enabled = True
    settings_obj.backup_email = "admin@example.com"
    settings_obj.backup_app_base_url = "http://testserver"
    settings_obj.backup_mail_from_email = "noreply@example.com"
    settings_obj.backup_interval_days = 7
    settings_obj.backup_link_ttl_days = 2
    settings_obj.backup_smtp_host = "smtp.example.com"
    settings_obj.backup_smtp_port = 587
    settings_obj.backup_smtp_username = "mailer"
    settings_obj.backup_smtp_use_tls = True
    settings_obj.backup_smtp_use_ssl = False
    settings_obj.backup_last_sent_at = timezone.now() - timedelta(days=8)
    settings_obj.set_backup_password("secret-123")
    settings_obj.set_backup_smtp_password("smtp-secret")
    settings_obj.save()

    result = send_database_backup_email_task()

    assert result["status"] == "sent"
    assert len(mail.outbox) == 1
    assert "http://testserver/admin/db-backup/" in mail.outbox[0].body


@pytest.mark.django_db
def test_backup_download_view_returns_file(client):
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.backup_enabled = True
    settings_obj.backup_email = "admin@example.com"
    settings_obj.backup_app_base_url = "http://testserver"
    settings_obj.backup_mail_from_email = "noreply@example.com"
    settings_obj.backup_link_ttl_days = 2
    settings_obj.backup_smtp_host = "smtp.example.com"
    settings_obj.backup_smtp_port = 587
    settings_obj.set_backup_password("secret-123")
    settings_obj.set_backup_smtp_password("smtp-secret")
    settings_obj.save()

    token = generate_download_token(settings_obj)
    response = client.get(reverse("admin-db-backup-download", kwargs={"token": token}))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/octet-stream"


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
def test_backup_email_connection_uses_runtime_admin_config():
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.backup_smtp_host = "smtp.example.com"
    settings_obj.backup_smtp_port = 465
    settings_obj.backup_smtp_username = "mailer"
    settings_obj.backup_smtp_use_tls = False
    settings_obj.backup_smtp_use_ssl = True
    settings_obj.set_backup_smtp_password("smtp-secret")

    connection = get_backup_email_connection(settings_obj)

    assert connection.host == "smtp.example.com"
    assert connection.port == 465
    assert connection.username == "mailer"
    assert connection.password == "smtp-secret"
    assert connection.use_ssl is True
