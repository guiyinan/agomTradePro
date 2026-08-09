"""Migration evidence for the final five legacy runtime configuration groups."""

from __future__ import annotations

import base64
import hashlib
import importlib
import uuid

import pytest
from cryptography.fernet import Fernet
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings

ACCOUNT_KEYS = {
    "account.require_user_approval",
    "account.auto_approve_first_admin",
    "account.default_mcp_enabled",
    "account.allow_token_plaintext_view",
    "account.user_agreement_content",
    "account.risk_warning_content",
    "account.notes",
}
ALPHA_KEYS = {"alpha.runtime.fixed_provider", "alpha.runtime.pool_mode"}
MARKET_KEYS = {
    "config_center.market.color_convention",
    "config_center.market.benchmark_code_map",
    "config_center.market.asset_proxy_code_map",
}
BACKUP_POLICY_KEYS = {
    "backup.enabled",
    "backup.recipient_email",
    "backup.app_base_url",
    "backup.mail_from_email",
    "backup.smtp_host",
    "backup.smtp_port",
    "backup.smtp_username",
    "backup.smtp_use_tls",
    "backup.smtp_use_ssl",
    "backup.interval_days",
    "backup.link_ttl_days",
    "backup.password_hint",
}
BACKUP_SECRET_KEYS = {"backup.archive_password", "backup.smtp_password"}
PROVIDER_KEYS = {
    "data_center.provider.default_source",
    "data_center.provider.enable_failover",
    "data_center.provider.failover_tolerance",
}
MATERIALIZED_KEYS = (
    ACCOUNT_KEYS
    | ALPHA_KEYS
    | MARKET_KEYS
    | BACKUP_POLICY_KEYS
    | BACKUP_SECRET_KEYS
    | PROVIDER_KEYS
)


def _legacy_encrypt(value: str, key: str) -> str:
    fernet_key = base64.urlsafe_b64encode(hashlib.sha256(key.encode("utf-8")).digest())
    return Fernet(fernet_key).encrypt(value.encode("utf-8")).decode("utf-8")


@pytest.mark.django_db(transaction=True)
@override_settings(
    AGOMTRADEPRO_ENCRYPTION_KEY="runtime-retirement-test-key",
    SECRET_KEY="runtime-retirement-secret-key",
)
def test_remaining_runtime_groups_materialize_once_with_canonical_precedence() -> None:
    """Legacy values fill gaps once while canonical values, secrets, and state win."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("config_center", "0014_materialize_qlib_runtime_profile")])
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(
            [
                ("config_center", "0014_materialize_qlib_runtime_profile"),
                ("data_center", "0066_make_retention_digest_widening_reversible"),
            ]
        ).apps
        Legacy = old_apps.get_model("config_center", "SystemSettingsModel")
        ProviderSettings = old_apps.get_model("data_center", "DataProviderSettingsModel")
        Profile = old_apps.get_model("config_center", "RuntimeConfigProfileModel")
        Value = old_apps.get_model("config_center", "RuntimeConfigValueModel")
        Snapshot = old_apps.get_model("config_center", "RuntimeConfigSnapshotModel")
        Secret = old_apps.get_model("config_center", "ConfigCenterSecretModel")
        State = old_apps.get_model("config_center", "BackupDeliveryStateModel")
        for model in (Snapshot, Value, Profile, Secret, State, ProviderSettings, Legacy):
            model.objects.all().delete()

        legacy = Legacy.objects.create(
            id=1,
            require_user_approval=False,
            auto_approve_first_admin=False,
            default_mcp_enabled=False,
            allow_token_plaintext_view=False,
            user_agreement_content="legacy agreement",
            risk_warning_content="legacy risk",
            notes="legacy notes",
            alpha_fixed_provider="qlib",
            alpha_pool_mode="market",
            market_color_convention="us_market",
            benchmark_code_map={"equity_market_benchmark": "000300.SH"},
            asset_proxy_code_map={"A_SHARE_GROWTH": "000300.SH"},
            backup_enabled=True,
            backup_email="ops@example.com",
            backup_app_base_url="https://example.com",
            backup_mail_from_email="backup@example.com",
            backup_smtp_host="smtp.example.com",
            backup_smtp_port=465,
            backup_smtp_username="backup-user",
            backup_smtp_use_tls=False,
            backup_smtp_use_ssl=True,
            backup_interval_days=5,
            backup_link_ttl_days=2,
            backup_password_hint="hint",
            backup_password_encrypted=_legacy_encrypt(
                "archive-secret", "runtime-retirement-test-key"
            ),
            backup_smtp_password_encrypted="unrecoverable-legacy-ciphertext",
            backup_download_token_digest="a" * 64,
        )
        ProviderSettings.objects.create(
            id=1,
            default_source="tushare",
            enable_failover=False,
            failover_tolerance=0.025,
        )
        old_profile_id = uuid.uuid4()
        Profile.objects.create(
            profile_id=old_profile_id,
            profile_key="development",
            environment="development",
            version=1,
            status="active",
            content_hash="old-hash",
            created_by="migration-test",
        )
        Value.objects.create(
            profile_id=old_profile_id,
            definition_key="account.default_mcp_enabled",
            value_json=True,
            source="admin",
        )
        Secret.objects.create(
            secret_ref="config_center.backup.archive_password",
            encrypted_value="canonical-secret-ciphertext",
        )
        State.objects.create(state_id=1, download_token_digest="b" * 64)

        with pytest.raises(RuntimeError, match="runtime_config_legacy_secret_unrecoverable"):
            executor.migrate([("config_center", "0015_materialize_remaining_runtime_groups")])
        assert Profile.objects.filter(environment="development", status="active").count() == 1
        assert not Secret.objects.filter(secret_ref="config_center.backup.smtp_password").exists()
        legacy.backup_smtp_password_encrypted = _legacy_encrypt(
            "smtp-secret", "runtime-retirement-test-key"
        )
        legacy.save(update_fields=["backup_smtp_password_encrypted"])

        executor = MigrationExecutor(connection)
        executor.migrate([("config_center", "0015_materialize_remaining_runtime_groups")])
        executor = MigrationExecutor(connection)
        new_apps = executor.loader.project_state(
            [("config_center", "0015_materialize_remaining_runtime_groups")]
        ).apps
        Profile = new_apps.get_model("config_center", "RuntimeConfigProfileModel")
        Value = new_apps.get_model("config_center", "RuntimeConfigValueModel")
        Snapshot = new_apps.get_model("config_center", "RuntimeConfigSnapshotModel")
        Secret = new_apps.get_model("config_center", "ConfigCenterSecretModel")
        State = new_apps.get_model("config_center", "BackupDeliveryStateModel")
        active = Profile.objects.get(environment="development", status="active")
        values = {
            row.definition_key: row for row in Value.objects.filter(profile_id=active.profile_id)
        }

        assert MATERIALIZED_KEYS.issubset(values)
        assert values["account.default_mcp_enabled"].value_json is True
        assert values["account.default_mcp_enabled"].source == "admin"
        assert values["account.require_user_approval"].value_json is legacy.require_user_approval
        assert values["alpha.runtime.pool_mode"].value_json == "market"
        assert values["config_center.market.color_convention"].value_json == "us_market"
        assert values["data_center.provider.default_source"].value_json == "tushare"
        assert values["backup.archive_password"].secret_ref == (
            "config_center.backup.archive_password"
        )
        assert values["backup.smtp_password"].secret_ref == "config_center.backup.smtp_password"
        assert (
            Secret.objects.get(secret_ref="config_center.backup.archive_password").encrypted_value
            == "canonical-secret-ciphertext"
        )
        assert Secret.objects.get(
            secret_ref="config_center.backup.smtp_password"
        ).encrypted_value.startswith("encrypted:v1:")
        assert State.objects.get(state_id=1).download_token_digest == "b" * 64
        snapshot = Snapshot.objects.get(profile_id=active.profile_id)
        assert snapshot.profile_version == active.version
        assert (MATERIALIZED_KEYS - BACKUP_SECRET_KEYS).issubset(snapshot.resolved_values)

        migration = importlib.import_module(
            "apps.config_center.migrations.0015_materialize_remaining_runtime_groups"
        )
        before_counts = (Profile.objects.count(), Value.objects.count(), Snapshot.objects.count())
        migration.materialize_remaining_runtime_groups(new_apps, None)
        assert (Profile.objects.count(), Value.objects.count(), Snapshot.objects.count()) == (
            before_counts
        )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True)
def test_remaining_runtime_groups_do_not_invent_profile_without_legacy_rows() -> None:
    """Fresh installs remain fail closed until an explicit typed profile is configured."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("config_center", "0014_materialize_qlib_runtime_profile")])
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(
            [
                ("config_center", "0014_materialize_qlib_runtime_profile"),
                ("data_center", "0066_make_retention_digest_widening_reversible"),
            ]
        ).apps
        for app_label, model_name in (
            ("config_center", "RuntimeConfigSnapshotModel"),
            ("config_center", "RuntimeConfigRevisionModel"),
            ("config_center", "RuntimeConfigValueModel"),
            ("config_center", "RuntimeConfigProfileModel"),
            ("config_center", "ConfigCenterSecretModel"),
            ("config_center", "BackupDeliveryStateModel"),
            ("config_center", "SystemSettingsModel"),
            ("data_center", "DataProviderSettingsModel"),
        ):
            old_apps.get_model(app_label, model_name).objects.all().delete()

        executor.migrate([("config_center", "0015_materialize_remaining_runtime_groups")])
        executor = MigrationExecutor(connection)
        new_apps = executor.loader.project_state(
            [("config_center", "0015_materialize_remaining_runtime_groups")]
        ).apps
        assert (
            not new_apps.get_model("config_center", "RuntimeConfigProfileModel")
            .objects.filter(environment="development", status="active")
            .exists()
        )
        empty_state = new_apps.get_model("config_center", "BackupDeliveryStateModel").objects.get(
            state_id=1
        )
        assert empty_state.download_token_digest == ""
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
