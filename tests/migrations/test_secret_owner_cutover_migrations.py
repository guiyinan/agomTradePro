"""Migration evidence for Config Center secret-owner cutovers."""

from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import override_settings

from shared.infrastructure.crypto import FieldEncryptionService

CONFIG_BEFORE = [("config_center", "0014_materialize_qlib_runtime_profile")]
CONFIG_AFTER = [("config_center", "0015_remove_legacy_backup_secret_columns")]
DATA_BEFORE = [("data_center", "0066_make_retention_digest_widening_reversible")]
DATA_AFTER = [("data_center", "0067_move_provider_credentials_to_config_center")]
ARCHIVE_REF = "config_center.backup.archive_password"
SMTP_REF = "config_center.backup.smtp_password"


def _legacy_backup_ciphertext(plaintext: str) -> str:
    raw_key = str(
        getattr(settings, "AGOMTRADEPRO_ENCRYPTION_KEY", "") or getattr(settings, "SECRET_KEY", "")
    )
    key = base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode("utf-8")).digest())
    return Fernet(key).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _migration_applied(app_label: str, name: str) -> bool:
    return (
        MigrationRecorder(connection)
        .migration_qs.filter(
            app=app_label,
            name=name,
        )
        .exists()
    )


@pytest.mark.django_db(transaction=True)
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="secret-cutover-migration-key")
def test_backup_secret_cutover_proves_equivalence_and_roundtrips() -> None:
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(CONFIG_BEFORE)
        before_apps = executor.loader.project_state(CONFIG_BEFORE).apps
        settings_model = before_apps.get_model("config_center", "SystemSettingsModel")
        secret_model = before_apps.get_model("config_center", "ConfigCenterSecretModel")
        settings_model.objects.update_or_create(
            pk=1,
            defaults={
                "backup_password_encrypted": _legacy_backup_ciphertext("archive-secret"),
                "backup_smtp_password_encrypted": _legacy_backup_ciphertext("smtp-secret"),
            },
        )
        crypto = FieldEncryptionService()
        secret_model.objects.create(
            secret_ref=ARCHIVE_REF,
            encrypted_value=crypto.encrypt("archive-secret"),
        )
        secret_model.objects.create(
            secret_ref=SMTP_REF,
            encrypted_value=crypto.encrypt("smtp-secret"),
        )

        executor = MigrationExecutor(connection)
        executor.migrate(CONFIG_AFTER)
        after_apps = executor.loader.project_state(CONFIG_AFTER).apps
        after_settings = after_apps.get_model("config_center", "SystemSettingsModel")
        assert "backup_password_encrypted" not in {
            field.name for field in after_settings._meta.fields
        }
        assert after_apps.get_model("config_center", "ConfigCenterSecretModel").objects.count() == 2

        executor = MigrationExecutor(connection)
        executor.migrate(CONFIG_BEFORE)
        reverse_apps = executor.loader.project_state(CONFIG_BEFORE).apps
        restored = reverse_apps.get_model("config_center", "SystemSettingsModel").objects.get(pk=1)
        assert restored.backup_password_encrypted == ""
        assert restored.backup_smtp_password_encrypted == ""
        assert (
            reverse_apps.get_model("config_center", "ConfigCenterSecretModel").objects.count() == 2
        )

        MigrationExecutor(connection).migrate(CONFIG_AFTER)
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True)
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="secret-cutover-migration-key")
def test_backup_secret_cutover_rejects_missing_or_conflicting_evidence_atomically() -> None:
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(CONFIG_BEFORE)
        before_apps = executor.loader.project_state(CONFIG_BEFORE).apps
        settings_model = before_apps.get_model("config_center", "SystemSettingsModel")
        secret_model = before_apps.get_model("config_center", "ConfigCenterSecretModel")
        legacy = _legacy_backup_ciphertext("legacy-secret")
        settings_model.objects.update_or_create(
            pk=1,
            defaults={
                "backup_password_encrypted": legacy,
                "backup_smtp_password_encrypted": "",
            },
        )

        with pytest.raises(RuntimeError, match="unmigrated_backup_delivery_secret"):
            MigrationExecutor(connection).migrate(CONFIG_AFTER)
        assert not _migration_applied(*CONFIG_AFTER[0])
        assert settings_model.objects.get(pk=1).backup_password_encrypted == legacy

        secret_model.objects.create(
            secret_ref=ARCHIVE_REF,
            encrypted_value=FieldEncryptionService().encrypt("different-secret"),
        )
        with pytest.raises(RuntimeError, match="backup_delivery_secret_conflict"):
            MigrationExecutor(connection).migrate(CONFIG_AFTER)
        assert not _migration_applied(*CONFIG_AFTER[0])
        assert settings_model.objects.get(pk=1).backup_password_encrypted == legacy
        settings_model.objects.filter(pk=1).delete()
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True)
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="secret-cutover-migration-key")
def test_provider_credential_cutover_preserves_ciphertext_and_refs_roundtrip() -> None:
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(DATA_BEFORE + CONFIG_AFTER)
        before_apps = executor.loader.project_state(DATA_BEFORE + CONFIG_AFTER).apps
        provider_model = before_apps.get_model("data_center", "ProviderConfigModel")
        legacy_model = before_apps.get_model("data_center", "ProviderCredentialModel")
        provider = provider_model.objects.create(
            name="provider-migration-roundtrip",
            source_type="tushare",
            api_key="",
            api_secret="",
        )
        crypto = FieldEncryptionService()
        key_ciphertext = crypto.encrypt("provider-key")
        secret_ciphertext = crypto.encrypt("provider-secret")
        legacy_ref = f"data_center.provider.{provider.pk}.credentials"
        legacy_model.objects.create(
            provider_id=provider.pk,
            credential_ref=legacy_ref,
            api_key_encrypted=key_ciphertext,
            api_secret_encrypted=secret_ciphertext,
        )

        executor = MigrationExecutor(connection)
        executor.migrate(DATA_AFTER)
        after_apps = executor.loader.project_state(DATA_AFTER).apps
        secret_model = after_apps.get_model("config_center", "ConfigCenterSecretModel")
        new_ref = f"config_center.data_center.provider.{provider.pk}.credentials"
        assert (
            secret_model.objects.get(secret_ref=f"{new_ref}.api_key").encrypted_value
            == key_ciphertext
        )
        assert (
            secret_model.objects.get(secret_ref=f"{new_ref}.api_secret").encrypted_value
            == secret_ciphertext
        )

        executor = MigrationExecutor(connection)
        executor.migrate(DATA_BEFORE)
        reverse_apps = executor.loader.project_state(DATA_BEFORE).apps
        restored = reverse_apps.get_model("data_center", "ProviderCredentialModel").objects.get(
            provider_id=provider.pk
        )
        assert restored.credential_ref == legacy_ref
        assert restored.api_key_encrypted == key_ciphertext
        assert restored.api_secret_encrypted == secret_ciphertext

        MigrationExecutor(connection).migrate(DATA_AFTER)
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True)
@override_settings(AGOMTRADEPRO_ENCRYPTION_KEY="secret-cutover-migration-key")
def test_provider_credential_cutover_rejects_plaintext_and_collision_atomically() -> None:
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(DATA_BEFORE + CONFIG_AFTER)
        before_apps = executor.loader.project_state(DATA_BEFORE + CONFIG_AFTER).apps
        provider_model = before_apps.get_model("data_center", "ProviderConfigModel")
        legacy_model = before_apps.get_model("data_center", "ProviderCredentialModel")
        secret_model = before_apps.get_model("config_center", "ConfigCenterSecretModel")
        provider = provider_model.objects.create(
            name="provider-migration-block",
            source_type="tushare",
            api_key="plaintext-must-block",
            api_secret="",
        )
        with pytest.raises(RuntimeError, match="unmigrated_provider_plaintext_credentials"):
            MigrationExecutor(connection).migrate(DATA_AFTER)
        assert not _migration_applied(*DATA_AFTER[0])
        assert provider_model.objects.get(pk=provider.pk).api_key == "plaintext-must-block"

        provider_model.objects.filter(pk=provider.pk).update(api_key="")
        ciphertext = FieldEncryptionService().encrypt("source-secret")
        legacy_model.objects.create(
            provider_id=provider.pk,
            credential_ref=f"data_center.provider.{provider.pk}.credentials",
            api_key_encrypted=ciphertext,
            api_secret_encrypted="",
        )
        new_ref = f"config_center.data_center.provider.{provider.pk}.credentials.api_key"
        collision = FieldEncryptionService().encrypt("different-secret")
        secret_model.objects.create(secret_ref=new_ref, encrypted_value=collision)
        with pytest.raises(RuntimeError, match="provider_credential_config_center_collision"):
            MigrationExecutor(connection).migrate(DATA_AFTER)
        assert not _migration_applied(*DATA_AFTER[0])
        assert legacy_model.objects.get(provider_id=provider.pk).api_key_encrypted == ciphertext
        assert secret_model.objects.get(secret_ref=new_ref).encrypted_value == collision
        provider_model.objects.filter(pk=provider.pk).delete()
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
