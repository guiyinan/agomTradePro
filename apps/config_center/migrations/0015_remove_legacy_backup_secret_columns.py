"""Remove legacy backup secret columns after Config Center cutover."""

from __future__ import annotations

import base64
import hashlib
import secrets
from binascii import Error as BinasciiError
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import migrations

_ENCRYPTED_PREFIX = "encrypted:v1:"
_ARCHIVE_REF = "config_center.backup.archive_password"
_SMTP_REF = "config_center.backup.smtp_password"


def _canonical_fernet() -> Fernet:
    raw_key = getattr(settings, "AGOMTRADEPRO_ENCRYPTION_KEY", None)
    if not isinstance(raw_key, str) or not raw_key.strip():
        raise ValueError("AGOMTRADEPRO_ENCRYPTION_KEY not configured")
    key_bytes = raw_key.strip().encode("utf-8")
    if len(key_bytes) == 44:
        return Fernet(key_bytes)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest()))


def _decrypt_canonical(ciphertext: str) -> str:
    encoded_token = ciphertext[len(_ENCRYPTED_PREFIX) :]
    token = base64.urlsafe_b64decode(encoded_token.encode("ascii"))
    return _canonical_fernet().decrypt(token).decode("utf-8")


def reject_unmigrated_backup_secrets(apps: Any, schema_editor: Any) -> None:
    """Block column removal while a legacy value lacks canonical evidence."""

    using = schema_editor.connection.alias
    settings_model = apps.get_model("config_center", "SystemSettingsModel")
    secret_model = apps.get_model("config_center", "ConfigCenterSecretModel")
    settings_row = settings_model.objects.using(using).filter(pk=1).first()
    if settings_row is None:
        return

    checks = (
        (str(settings_row.backup_password_encrypted or ""), _ARCHIVE_REF),
        (str(settings_row.backup_smtp_password_encrypted or ""), _SMTP_REF),
    )
    for legacy_value, secret_ref in checks:
        if not legacy_value:
            continue
        canonical = secret_model.objects.using(using).filter(secret_ref=secret_ref).first()
        canonical_value = str(canonical.encrypted_value or "") if canonical else ""
        if not canonical_value.startswith(_ENCRYPTED_PREFIX):
            raise RuntimeError("unmigrated_backup_delivery_secret")
        try:
            legacy_key = getattr(settings, "AGOMTRADEPRO_ENCRYPTION_KEY", "") or getattr(
                settings, "SECRET_KEY", ""
            )
            legacy_fernet = Fernet(
                base64.urlsafe_b64encode(hashlib.sha256(legacy_key.encode("utf-8")).digest())
            )
            legacy_plaintext = legacy_fernet.decrypt(legacy_value.encode("utf-8")).decode("utf-8")
            canonical_plaintext = _decrypt_canonical(canonical_value)
        except (
            BinasciiError,
            InvalidToken,
            TypeError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            raise RuntimeError("backup_delivery_secret_equivalence_unprovable") from exc
        if not secrets.compare_digest(legacy_plaintext, canonical_plaintext):
            raise RuntimeError("backup_delivery_secret_conflict")


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("config_center", "0014_materialize_qlib_runtime_profile"),
    ]

    operations = [
        migrations.RunPython(
            reject_unmigrated_backup_secrets,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="systemsettingsmodel",
            name="backup_password_encrypted",
        ),
        migrations.RemoveField(
            model_name="systemsettingsmodel",
            name="backup_smtp_password_encrypted",
        ),
    ]
