"""Guarded removal of the deprecated plaintext AI provider key column."""

from collections.abc import Iterator
from typing import Any, cast

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

from shared.config.secrets import get_secrets
from shared.infrastructure.crypto import FieldEncryptionService


def _field_encryption_service() -> FieldEncryptionService:
    """Build the existing field-encryption service from the environment key."""

    try:
        encryption_key = get_secrets(require_tushare_token=False).field_encryption_key
    except Exception:
        raise RuntimeError("ai_provider_encryption_key_unavailable") from None
    if not isinstance(encryption_key, str) or not encryption_key.strip():
        raise RuntimeError("ai_provider_encryption_key_unavailable")
    try:
        return FieldEncryptionService(encryption_key=encryption_key)
    except Exception:
        raise RuntimeError("ai_provider_encryption_key_unavailable") from None


def _guard_plaintext_column_removal(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Abort before schema changes if plaintext remains or any ciphertext is unreadable."""

    # The historical ORM state still has the field removed from the runtime model.
    # Keep that dynamic model at the ORM boundary and narrow its rows below.
    provider_model: Any = apps.get_model("ai_provider", "AIProviderConfig")
    if schema_editor.connection.vendor == "postgresql":
        # Prevent a concurrent writer from adding plaintext after validation but before DDL.
        table_name = schema_editor.quote_name(provider_model._meta.db_table)
        schema_editor.execute(f"LOCK TABLE {table_name} IN ACCESS EXCLUSIVE MODE")

    provider_rows = cast(
        Iterator[tuple[object, object]],
        provider_model._base_manager.using(schema_editor.connection.alias)
        .order_by("pk")
        .values_list("api_key", "api_key_encrypted")
        .iterator(chunk_size=500),
    )
    crypto_service: FieldEncryptionService | None = None

    for plaintext_key, encrypted_key in provider_rows:
        if plaintext_key not in (None, ""):
            raise RuntimeError("ai_provider_plaintext_api_keys_remain")
        if encrypted_key in (None, ""):
            continue
        if not isinstance(encrypted_key, str):
            raise RuntimeError("ai_provider_ciphertext_invalid")
        if crypto_service is None:
            crypto_service = _field_encryption_service()
        if not crypto_service.is_encrypted(encrypted_key):
            raise RuntimeError("ai_provider_ciphertext_not_prefixed")
        try:
            plaintext = crypto_service.decrypt(encrypted_key, suppress_warning=True)
        except Exception:
            raise RuntimeError("ai_provider_ciphertext_unreadable_with_current_key") from None
        if not plaintext:
            raise RuntimeError("ai_provider_ciphertext_unreadable_with_current_key")


class Migration(migrations.Migration):
    """Remove plaintext storage only after every remaining credential is recoverable."""

    atomic = True

    dependencies = [
        ("ai_provider", "0004_aiuserfallbackquota_aiproviderconfig_owner_user_and_more"),
    ]

    operations = [
        migrations.RunPython(
            code=_guard_plaintext_column_removal,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="aiproviderconfig",
            name="api_key",
        ),
    ]
