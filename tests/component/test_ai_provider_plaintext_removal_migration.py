"""Guarded AI-provider plaintext-column removal and retry/idempotence evidence."""

import base64
from collections.abc import Iterator
from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from shared.config.secrets import get_secrets
from shared.infrastructure.crypto import FieldEncryptionService
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)

_BEFORE = ("ai_provider", "0004_aiuserfallbackquota_aiproviderconfig_owner_user_and_more")
_AFTER = ("ai_provider", "0005_drop_plaintext_api_key")


@pytest.fixture(autouse=True)
def _clear_cached_secrets() -> Iterator[None]:
    get_secrets.cache_clear()
    try:
        yield
    finally:
        get_secrets.cache_clear()


def _provider_model_at(migration: tuple[str, str]):
    """Return the historical provider model for one migration state."""

    return (
        MigrationExecutor(connection)
        .loader.project_state([migration])
        .apps.get_model("ai_provider", "AIProviderConfig")
    )


def _table_columns() -> set[str]:
    """Read the current provider table schema after a migration attempt."""

    with connection.cursor() as cursor:
        return {
            column.name
            for column in connection.introspection.get_table_description(
                cursor,
                "ai_provider_config",
            )
        }


def _delete_fixture_row(name: str) -> None:
    """Remove one isolated row regardless of which side of the migration is active."""

    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM ai_provider_config WHERE name = %s", [name])


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("failure_case", "expected_error"),
    [
        ("plaintext", "ai_provider_plaintext_api_keys_remain"),
        ("mixed", "ai_provider_plaintext_api_keys_remain"),
        ("unprefixed", "ai_provider_ciphertext_not_prefixed"),
        ("wrong_key", "ai_provider_ciphertext_unreadable_with_current_key"),
        ("corrupt", "ai_provider_ciphertext_unreadable_with_current_key"),
        ("empty_decryption", "ai_provider_ciphertext_unreadable_with_current_key"),
        ("missing_key", "ai_provider_encryption_key_unavailable"),
    ],
    ids=(
        "plaintext",
        "mixed",
        "unprefixed",
        "wrong-key",
        "corrupt",
        "empty-decryption",
        "missing-key",
    ),
)
def test_failed_removal_preserves_schema_and_credential_values(
    django_db_use_migrations: bool,
    monkeypatch: pytest.MonkeyPatch,
    failure_case: str,
    expected_error: str,
) -> None:
    """Every current migration guard fails before DDL and leaves the source row intact."""

    if not django_db_use_migrations:
        pytest.skip("Migration preservation proof requires migrations-enabled test database")
    if not connection.features.can_rollback_ddl:
        pytest.skip("Migration atomicity proof requires transactional DDL support")

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    name = f"ref06-{uuid4().hex}"
    plaintext = ""
    encrypted_key = ""
    active_key = "ref06-migration-active-key"

    if failure_case == "plaintext":
        plaintext = "sk-plaintext-must-survive"
        monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", active_key)
    elif failure_case == "mixed":
        plaintext = "sk-plaintext-and-ciphertext-must-survive"
        encrypted_key = FieldEncryptionService(encryption_key=active_key).encrypt(
            "sk-existing-ciphertext"
        )
        monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", active_key)
    elif failure_case == "unprefixed":
        encrypted_key = "legacy-unprefixed-ciphertext"
        monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", active_key)
    elif failure_case == "wrong_key":
        encrypted_key = FieldEncryptionService(encryption_key="ref06-old-key").encrypt(
            "sk-wrong-key"
        )
        monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", active_key)
    elif failure_case == "corrupt":
        encrypted_key = f"{FieldEncryptionService.PREFIX}not-valid-ciphertext"
        monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", active_key)
    elif failure_case == "empty_decryption":
        crypto = FieldEncryptionService(encryption_key=active_key)
        empty_token = crypto.fernet.encrypt(b"")
        encrypted_key = (
            f"{FieldEncryptionService.PREFIX}"
            f"{base64.urlsafe_b64encode(empty_token).decode('ascii')}"
        )
        monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", active_key)
    else:
        encrypted_key = FieldEncryptionService(encryption_key="ref06-source-key").encrypt(
            "sk-missing-environment-key"
        )
        monkeypatch.delenv("AGOMTRADEPRO_ENCRYPTION_KEY", raising=False)
    get_secrets.cache_clear()

    try:
        executor.migrate([_BEFORE])
        ProviderBefore = _provider_model_at(_BEFORE)
        provider = ProviderBefore._default_manager.create(
            name=name,
            provider_type="custom",
            base_url="https://example.invalid/v1",
            api_key=plaintext,
            api_key_encrypted=encrypted_key,
            default_model="gpt-4o-mini",
        )

        with pytest.raises(RuntimeError, match=expected_error):
            MigrationExecutor(connection).migrate([_AFTER])

        assert {"api_key", "api_key_encrypted"} <= _table_columns()
        stored = ProviderBefore._default_manager.get(pk=provider.pk)
        assert stored.api_key == plaintext
        assert stored.api_key_encrypted == encrypted_key
        assert _AFTER not in MigrationRecorder(connection).applied_migrations()
    finally:
        _delete_fixture_row(name)
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "seed_empty_credential",
    [False, True],
    ids=("absent-row", "empty-row"),
)
def test_empty_provider_state_migrates_without_encryption_key(
    django_db_use_migrations: bool,
    monkeypatch: pytest.MonkeyPatch,
    seed_empty_credential: bool,
) -> None:
    """No credential data means the guarded schema migration does not need a key."""

    if not django_db_use_migrations:
        pytest.skip("Migration preservation proof requires migrations-enabled test database")
    if not connection.features.can_rollback_ddl:
        pytest.skip("Migration atomicity proof requires transactional DDL support")

    monkeypatch.delenv("AGOMTRADEPRO_ENCRYPTION_KEY", raising=False)
    get_secrets.cache_clear()
    name = f"ref06-{uuid4().hex}"
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()

    try:
        executor.migrate([_BEFORE])
        ProviderBefore = _provider_model_at(_BEFORE)
        if seed_empty_credential:
            ProviderBefore._default_manager.create(
                name=name,
                provider_type="custom",
                base_url="https://example.invalid/v1",
                api_key="",
                api_key_encrypted="",
                default_model="gpt-4o-mini",
            )

        MigrationExecutor(connection).migrate([_AFTER])
        assert "api_key" not in _table_columns()
        ProviderAfter = _provider_model_at(_AFTER)
        provider = ProviderAfter._default_manager.filter(name=name).first()
        assert (provider is not None) is seed_empty_credential
        if provider is not None:
            assert provider.api_key_encrypted == ""

        MigrationExecutor(connection).migrate([_AFTER])
        assert ProviderAfter._default_manager.filter(name=name).exists() is seed_empty_credential
    finally:
        _delete_fixture_row(name)
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True)
def test_valid_removal_is_idempotent_and_preserves_decryptable_ciphertext(
    django_db_use_migrations: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verified ciphertext survives schema removal and an already-applied retry."""

    if not django_db_use_migrations:
        pytest.skip("Migration preservation proof requires migrations-enabled test database")
    if not connection.features.can_rollback_ddl:
        pytest.skip("Migration atomicity proof requires transactional DDL support")

    key = "ref06-migration-valid-key"
    monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", key)
    get_secrets.cache_clear()
    crypto = FieldEncryptionService(encryption_key=key)
    plaintext = "sk-ref06-valid-migration-credential"
    ciphertext = crypto.encrypt(plaintext)
    name = f"ref06-{uuid4().hex}"
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()

    try:
        executor.migrate([_BEFORE])
        ProviderBefore = _provider_model_at(_BEFORE)
        ProviderBefore._default_manager.create(
            name=name,
            provider_type="custom",
            base_url="https://example.invalid/v1",
            api_key="",
            api_key_encrypted=ciphertext,
            default_model="gpt-4o-mini",
        )

        MigrationExecutor(connection).migrate([_AFTER])
        assert "api_key" not in _table_columns()
        ProviderAfter = _provider_model_at(_AFTER)
        migrated = ProviderAfter._default_manager.get(name=name)
        assert migrated.api_key_encrypted == ciphertext
        assert crypto.decrypt(migrated.api_key_encrypted) == plaintext

        MigrationExecutor(connection).migrate([_AFTER])
        migrated.refresh_from_db()
        assert migrated.api_key_encrypted == ciphertext
        assert crypto.decrypt(migrated.api_key_encrypted) == plaintext

        MigrationExecutor(connection).migrate([_BEFORE])
        rolled_back = ProviderBefore._default_manager.get(name=name)
        assert rolled_back.api_key == ""
        assert rolled_back.api_key_encrypted == ciphertext
        assert crypto.decrypt(rolled_back.api_key_encrypted) == plaintext
        MigrationExecutor(connection).migrate([_AFTER])
        assert "api_key" not in _table_columns()
        assert ProviderAfter._default_manager.get(name=name).api_key_encrypted == ciphertext
    finally:
        _delete_fixture_row(name)
        MigrationExecutor(connection).migrate(leaf_nodes)
