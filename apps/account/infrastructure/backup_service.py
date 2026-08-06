import base64
import gzip
import hashlib
import io
import json
import os
import secrets
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, TypedDict, cast

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings
from django.core import management, signing
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend
from django.db import connections
from django.urls import reverse
from django.utils import timezone

from apps.account.infrastructure.backup_delivery_projection import get_backup_delivery_settings
from apps.account.infrastructure.models import SystemSettingsModel
from apps.config_center.application.public import record_backup_download_token

DOWNLOAD_TOKEN_SALT = "account-db-backup-download"
BACKUP_FILE_MAGIC = b"AGBK1"


@dataclass
class GeneratedBackup:
    filename: str
    content: bytes
    content_type: str


class BackupDownloadTokenPayload(TypedDict):
    """Validated claims carried by a signed backup download link."""

    settings_id: int
    email: str
    nonce: str
    ts: str


class BackupPackageDescription(TypedDict):
    """Public metadata for the encrypted backup package."""

    format: str
    extension: str
    magic: str


def build_backup_download_url(token: str) -> str:
    path = reverse("admin-db-backup-download", kwargs={"token": token})
    legacy_settings = SystemSettingsModel.get_settings_for_read()
    config = get_backup_delivery_settings(base_settings=legacy_settings)
    base_url = (config.backup_app_base_url or getattr(settings, "APP_BASE_URL", "")).rstrip("/")
    if base_url:
        return f"{base_url}{path}"

    scheme = "https" if getattr(settings, "SECURE_SSL_REDIRECT", False) else "http"
    host = (getattr(settings, "ALLOWED_HOSTS", []) or ["127.0.0.1:8000"])[0]
    return f"{scheme}://{host}{path}"


def generate_download_token(config: SystemSettingsModel) -> str:
    if (
        isinstance(config.backup_link_ttl_days, bool)
        or not isinstance(config.backup_link_ttl_days, int)
        or config.backup_link_ttl_days < 1
    ):
        raise ValueError("Backup link TTL must be a positive integer")

    issued_at = timezone.now()
    nonce = secrets.token_urlsafe(32)
    payload = {
        "settings_id": config.pk,
        "email": config.backup_email,
        "nonce": nonce,
        "ts": issued_at.isoformat(),
    }
    digest = hash_download_nonce(nonce)
    expires_at = issued_at + timedelta(days=config.backup_link_ttl_days)
    if getattr(config, "pk", None):
        record_backup_download_token(digest=digest, expires_at=expires_at)
    else:
        # Lightweight test doubles remain supported without bypassing the
        # production state owner.
        config.backup_download_token_digest = digest
        config.backup_download_token_expires_at = expires_at
        config.backup_download_consumed_at = None
        config.save(
            update_fields=[
                "backup_download_token_digest",
                "backup_download_token_expires_at",
                "backup_download_consumed_at",
                "updated_at",
            ]
        )
    return signing.dumps(payload, salt=DOWNLOAD_TOKEN_SALT)


def hash_download_nonce(nonce: str) -> str:
    """Return the irreversible persisted fingerprint for a download nonce."""

    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def validate_download_token(
    token: str,
    max_age_seconds: int,
) -> BackupDownloadTokenPayload:
    """Verify a signed token and narrow all security-sensitive claims."""

    if isinstance(max_age_seconds, bool) or max_age_seconds <= 0:
        raise ValueError("Backup token max age must be positive")
    raw_payload: Any = signing.loads(
        token,
        salt=DOWNLOAD_TOKEN_SALT,
        max_age=max_age_seconds,
    )
    if not isinstance(raw_payload, dict):
        raise ValueError("Invalid backup token payload")

    settings_id = raw_payload.get("settings_id")
    email = raw_payload.get("email")
    nonce = raw_payload.get("nonce")
    issued_at = raw_payload.get("ts")
    if isinstance(settings_id, bool) or not isinstance(settings_id, int) or settings_id <= 0:
        raise ValueError("Invalid backup token settings id")
    if not isinstance(email, str) or not email.strip():
        raise ValueError("Invalid backup token email")
    if not isinstance(nonce, str) or not nonce:
        raise ValueError("Invalid backup token nonce")
    if not isinstance(issued_at, str) or not issued_at:
        raise ValueError("Invalid backup token timestamp")
    return {
        "settings_id": settings_id,
        "email": email,
        "nonce": nonce,
        "ts": issued_at,
    }


def generate_backup_archive(config: SystemSettingsModel) -> GeneratedBackup:
    raw_backup = _build_raw_backup_bytes()
    compressed = gzip.compress(raw_backup, compresslevel=6)
    encrypted = _encrypt_backup_bytes(compressed, config.get_backup_password())
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    db_engine = connections["default"].settings_dict.get("ENGINE", "unknown").rsplit(".", 1)[-1]
    filename = f"agomtradepro-db-backup-{db_engine}-{timestamp}.agbk"
    return GeneratedBackup(
        filename=filename,
        content=encrypted,
        content_type="application/octet-stream",
    )


def describe_backup_package() -> BackupPackageDescription:
    return {
        "format": "gzip + fernet(password-derived-key)",
        "extension": ".agbk",
        "magic": BACKUP_FILE_MAGIC.decode("ascii"),
    }


def get_backup_email_connection(config: SystemSettingsModel) -> BaseEmailBackend:
    return cast(
        BaseEmailBackend,
        get_connection(
            host=config.backup_smtp_host,
            port=config.backup_smtp_port,
            username=config.backup_smtp_username or None,
            password=config.get_backup_smtp_password() or None,
            use_tls=config.backup_smtp_use_tls,
            use_ssl=config.backup_smtp_use_ssl,
            fail_silently=False,
        ),
    )


def _build_raw_backup_bytes() -> bytes:
    connection_settings = connections["default"].settings_dict
    engine = connection_settings.get("ENGINE", "")
    if engine.endswith("sqlite3"):
        return _copy_sqlite_database_bytes()
    return _dump_database_as_json_bytes()


def _copy_sqlite_database_bytes() -> bytes:
    """Create a consistent SQLite snapshot without closing the live connection."""

    django_connection = connections["default"]
    django_connection.ensure_connection()
    source = cast(sqlite3.Connection | None, django_connection.connection)
    if source is None:
        raise RuntimeError("SQLite database connection is unavailable")

    descriptor, snapshot_name = tempfile.mkstemp(suffix=".sqlite3")
    os.close(descriptor)
    snapshot_path = Path(snapshot_name)
    try:
        destination = sqlite3.connect(snapshot_name)
        try:
            source.backup(destination)
        finally:
            destination.close()
        return snapshot_path.read_bytes()
    finally:
        snapshot_path.unlink(missing_ok=True)


def _dump_database_as_json_bytes() -> bytes:
    stream = io.StringIO()
    management.call_command("dumpdata", stdout=stream, verbosity=0)
    payload = {
        "generated_at": timezone.now().isoformat(),
        "database_engine": connections["default"].settings_dict.get("ENGINE", ""),
        "format": "django-dumpdata-json",
        "data": json.loads(stream.getvalue() or "[]"),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _encrypt_backup_bytes(content: bytes, password: str) -> bytes:
    if not password:
        raise ValueError("Backup password is not configured")
    salt = secrets.token_bytes(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=390000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
    encrypted: bytes = Fernet(key).encrypt(content)
    return BACKUP_FILE_MAGIC + salt + encrypted
