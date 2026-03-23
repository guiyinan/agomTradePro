import base64
import gzip
import io
import json
import secrets
from dataclasses import dataclass

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings
from django.core import management, signing
from django.core.mail import get_connection
from django.db import connections
from django.urls import reverse
from django.utils import timezone

from apps.account.infrastructure.models import SystemSettingsModel

DOWNLOAD_TOKEN_SALT = "account-db-backup-download"
BACKUP_FILE_MAGIC = b"AGBK1"


@dataclass
class GeneratedBackup:
    filename: str
    content: bytes
    content_type: str


def build_backup_download_url(token: str) -> str:
    path = reverse("admin-db-backup-download", kwargs={"token": token})
    config = SystemSettingsModel.get_settings()
    base_url = (config.backup_app_base_url or getattr(settings, "APP_BASE_URL", "")).rstrip("/")
    if base_url:
        return f"{base_url}{path}"

    scheme = "https" if getattr(settings, "SECURE_SSL_REDIRECT", False) else "http"
    host = (getattr(settings, "ALLOWED_HOSTS", []) or ["127.0.0.1:8000"])[0]
    return f"{scheme}://{host}{path}"


def generate_download_token(config: SystemSettingsModel) -> str:
    payload = {
        "settings_id": config.pk,
        "email": config.backup_email,
        "nonce": secrets.token_urlsafe(12),
        "ts": timezone.now().isoformat(),
    }
    return signing.dumps(payload, salt=DOWNLOAD_TOKEN_SALT)


def validate_download_token(token: str, max_age_seconds: int) -> dict:
    return signing.loads(token, salt=DOWNLOAD_TOKEN_SALT, max_age=max_age_seconds)


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


def describe_backup_package() -> dict:
    return {
        "format": "gzip + fernet(password-derived-key)",
        "extension": ".agbk",
        "magic": BACKUP_FILE_MAGIC.decode("ascii"),
    }


def get_backup_email_connection(config: SystemSettingsModel):
    return get_connection(
        host=config.backup_smtp_host,
        port=config.backup_smtp_port,
        username=config.backup_smtp_username or None,
        password=config.get_backup_smtp_password() or None,
        use_tls=config.backup_smtp_use_tls,
        use_ssl=config.backup_smtp_use_ssl,
        fail_silently=False,
    )


def _build_raw_backup_bytes() -> bytes:
    connection_settings = connections["default"].settings_dict
    engine = connection_settings.get("ENGINE", "")
    if engine.endswith("sqlite3"):
        db_name = connection_settings.get("NAME", "")
        return _copy_sqlite_database_bytes(db_name)
    return _dump_database_as_json_bytes()


def _copy_sqlite_database_bytes(db_name: str) -> bytes:
    if not db_name:
        raise ValueError("SQLite database path is empty")
    connections["default"].close()
    with open(db_name, "rb") as fh:
        return fh.read()


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
    encrypted = Fernet(key).encrypt(content)
    return BACKUP_FILE_MAGIC + salt + encrypted
