"""Move provider secrets to Config Center and remove legacy credential stores."""

from __future__ import annotations

from typing import Any

from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError

_ENCRYPTED_PREFIX = "encrypted:v1:"


def _aggregate_ref(provider_id: int) -> str:
    return f"data_center.provider.{provider_id}.credentials"


def _api_key_ref(provider_id: int) -> str:
    return f"config_center.data_center.provider.{provider_id}.credentials.api_key"


def _api_secret_ref(provider_id: int) -> str:
    return f"config_center.data_center.provider.{provider_id}.credentials.api_secret"


def _copy_secret(
    secret_model: Any,
    *,
    using: str,
    secret_ref: str,
    encrypted_value: str,
) -> None:
    if not encrypted_value:
        return
    if not encrypted_value.startswith(_ENCRYPTED_PREFIX):
        raise RuntimeError("provider_credential_ciphertext_is_not_canonical")
    existing = secret_model.objects.using(using).filter(secret_ref=secret_ref).first()
    if existing is not None:
        if existing.encrypted_value != encrypted_value:
            raise RuntimeError("provider_credential_config_center_collision")
        return
    secret_model.objects.using(using).create(
        secret_ref=secret_ref,
        encrypted_value=encrypted_value,
    )


def move_provider_credentials_forward(apps: Any, schema_editor: Any) -> None:
    """Copy canonical ciphertext and reject any unmigrated plaintext."""

    using = schema_editor.connection.alias
    provider_model = apps.get_model("data_center", "ProviderConfigModel")
    legacy_model = apps.get_model("data_center", "ProviderCredentialModel")
    secret_model = apps.get_model("config_center", "ConfigCenterSecretModel")

    if (
        provider_model.objects.using(using).exclude(api_key="").exists()
        or provider_model.objects.using(using).exclude(api_secret="").exists()
    ):
        raise RuntimeError("unmigrated_provider_plaintext_credentials")

    for legacy in legacy_model.objects.using(using).order_by("provider_id"):
        provider_id = int(legacy.provider_id)
        if legacy.credential_ref != _aggregate_ref(provider_id):
            raise RuntimeError("provider_credential_legacy_ref_is_not_canonical")
        _copy_secret(
            secret_model,
            using=using,
            secret_ref=_api_key_ref(provider_id),
            encrypted_value=str(legacy.api_key_encrypted or ""),
        )
        _copy_secret(
            secret_model,
            using=using,
            secret_ref=_api_secret_ref(provider_id),
            encrypted_value=str(legacy.api_secret_encrypted or ""),
        )


def restore_provider_credentials_reverse(apps: Any, schema_editor: Any) -> None:
    """Rebuild the old encrypted side table exactly from canonical refs."""

    using = schema_editor.connection.alias
    provider_model = apps.get_model("data_center", "ProviderConfigModel")
    legacy_model = apps.get_model("data_center", "ProviderCredentialModel")
    secret_model = apps.get_model("config_center", "ConfigCenterSecretModel")

    for provider_id in provider_model.objects.using(using).values_list("pk", flat=True):
        normalized_id = int(provider_id)
        api_key_row = (
            secret_model.objects.using(using).filter(secret_ref=_api_key_ref(normalized_id)).first()
        )
        api_secret_row = (
            secret_model.objects.using(using)
            .filter(secret_ref=_api_secret_ref(normalized_id))
            .first()
        )
        api_key_encrypted = str(api_key_row.encrypted_value or "") if api_key_row else ""
        api_secret_encrypted = str(api_secret_row.encrypted_value or "") if api_secret_row else ""
        if not api_key_encrypted and not api_secret_encrypted:
            continue
        if (api_key_encrypted and not api_key_encrypted.startswith(_ENCRYPTED_PREFIX)) or (
            api_secret_encrypted and not api_secret_encrypted.startswith(_ENCRYPTED_PREFIX)
        ):
            raise IrreversibleError(
                "provider Config Center ciphertext cannot restore the legacy side table"
            )
        legacy_model.objects.using(using).update_or_create(
            provider_id=normalized_id,
            defaults={
                "credential_ref": _aggregate_ref(normalized_id),
                "api_key_encrypted": api_key_encrypted,
                "api_secret_encrypted": api_secret_encrypted,
            },
        )


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("config_center", "0015_remove_legacy_backup_secret_columns"),
        ("data_center", "0066_make_retention_digest_widening_reversible"),
    ]

    operations = [
        migrations.RunPython(
            move_provider_credentials_forward,
            restore_provider_credentials_reverse,
        ),
        migrations.RemoveField(
            model_name="providerconfigmodel",
            name="api_key",
        ),
        migrations.RemoveField(
            model_name="providerconfigmodel",
            name="api_secret",
        ),
        migrations.DeleteModel(
            name="ProviderCredentialModel",
        ),
    ]
