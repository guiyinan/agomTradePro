"""Materialize the five remaining legacy runtime groups into Config Center."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import migrations, transaction
from django.utils import timezone

ACCOUNT_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("account.require_user_approval", "require_user_approval"),
    ("account.auto_approve_first_admin", "auto_approve_first_admin"),
    ("account.default_mcp_enabled", "default_mcp_enabled"),
    ("account.allow_token_plaintext_view", "allow_token_plaintext_view"),
    ("account.user_agreement_content", "user_agreement_content"),
    ("account.risk_warning_content", "risk_warning_content"),
    ("account.notes", "notes"),
)
ALPHA_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("alpha.runtime.fixed_provider", "alpha_fixed_provider"),
    ("alpha.runtime.pool_mode", "alpha_pool_mode"),
)
MARKET_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("config_center.market.color_convention", "market_color_convention"),
    ("config_center.market.benchmark_code_map", "benchmark_code_map"),
    ("config_center.market.asset_proxy_code_map", "asset_proxy_code_map"),
)
BACKUP_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("backup.enabled", "backup_enabled"),
    ("backup.recipient_email", "backup_email"),
    ("backup.app_base_url", "backup_app_base_url"),
    ("backup.mail_from_email", "backup_mail_from_email"),
    ("backup.smtp_host", "backup_smtp_host"),
    ("backup.smtp_port", "backup_smtp_port"),
    ("backup.smtp_username", "backup_smtp_username"),
    ("backup.smtp_use_tls", "backup_smtp_use_tls"),
    ("backup.smtp_use_ssl", "backup_smtp_use_ssl"),
    ("backup.interval_days", "backup_interval_days"),
    ("backup.link_ttl_days", "backup_link_ttl_days"),
    ("backup.password_hint", "backup_password_hint"),
)
PROVIDER_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("data_center.provider.default_source", "default_source"),
    ("data_center.provider.enable_failover", "enable_failover"),
    ("data_center.provider.failover_tolerance", "failover_tolerance"),
)
BACKUP_SECRET_MAP: tuple[tuple[str, str, str], ...] = (
    (
        "backup.archive_password",
        "backup_password_encrypted",
        "config_center.backup.archive_password",
    ),
    (
        "backup.smtp_password",
        "backup_smtp_password_encrypted",
        "config_center.backup.smtp_password",
    ),
)
SYSTEM_FIELD_MAP = ACCOUNT_FIELD_MAP + ALPHA_FIELD_MAP + MARKET_FIELD_MAP + BACKUP_FIELD_MAP
NON_SECRET_KEYS = frozenset(key for key, _field_name in SYSTEM_FIELD_MAP + PROVIDER_FIELD_MAP)
SECRET_KEYS = frozenset(key for key, _field_name, _secret_ref in BACKUP_SECRET_MAP)


def _runtime_environment() -> str:
    """Resolve the migration target environment using the production rule."""

    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    return "production" if settings_module.endswith(".production") else "development"


def _hash_values(values: dict[str, object]) -> str:
    serialized = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _fernet_for_key(raw_key: str) -> Fernet:
    normalized = str(raw_key or "").strip()
    if not normalized:
        raise RuntimeError("runtime_config_secret_materialization_key_missing")
    encoded = normalized.encode("utf-8")
    if len(encoded) == 44:
        return Fernet(encoded)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(encoded).digest()))


def _decrypt_legacy_secret(ciphertext: str) -> str:
    """Decrypt the historical raw Fernet token or fail closed."""

    legacy_key = str(getattr(settings, "AGOMTRADEPRO_ENCRYPTION_KEY", "") or "").strip()
    if not legacy_key:
        legacy_key = str(getattr(settings, "SECRET_KEY", "") or "").strip()
    try:
        plaintext = _fernet_for_key(legacy_key).decrypt(ciphertext.encode("utf-8"))
    except (InvalidToken, TypeError, ValueError) as exc:
        raise RuntimeError("runtime_config_legacy_secret_unrecoverable") from exc
    return plaintext.decode("utf-8")


def _encrypt_config_center_secret(plaintext: str) -> str:
    """Encode one secret with Config Center's current encrypted:v1 format."""

    encryption_key = str(getattr(settings, "AGOMTRADEPRO_ENCRYPTION_KEY", "") or "").strip()
    encrypted = _fernet_for_key(encryption_key).encrypt(plaintext.encode("utf-8"))
    return "encrypted:v1:" + base64.urlsafe_b64encode(encrypted).decode("ascii")


def _manager(model: Any, alias: str) -> Any:
    return model.objects.using(alias)


def materialize_remaining_runtime_groups(apps: Any, schema_editor: Any) -> None:
    """Copy five legacy groups once while preserving every canonical value."""

    alias = schema_editor.connection.alias if schema_editor is not None else "default"
    legacy_model = apps.get_model("config_center", "SystemSettingsModel")
    provider_model = apps.get_model("data_center", "DataProviderSettingsModel")
    profile_model = apps.get_model("config_center", "RuntimeConfigProfileModel")
    value_model = apps.get_model("config_center", "RuntimeConfigValueModel")
    revision_model = apps.get_model("config_center", "RuntimeConfigRevisionModel")
    snapshot_model = apps.get_model("config_center", "RuntimeConfigSnapshotModel")
    secret_model = apps.get_model("config_center", "ConfigCenterSecretModel")
    state_model = apps.get_model("config_center", "BackupDeliveryStateModel")

    with transaction.atomic(using=alias):
        environment = _runtime_environment()
        active_profiles = list(
            _manager(profile_model, alias)
            .filter(environment=environment, status="active")
            .order_by("-version")
        )
        if len(active_profiles) > 1:
            raise RuntimeError("runtime_config_multiple_active_profiles")
        active = active_profiles[0] if active_profiles else None
        existing_rows = list(
            _manager(value_model, alias)
            .filter(profile_id=active.profile_id)
            .order_by("definition_key")
            if active is not None
            else ()
        )
        existing_by_key = {row.definition_key: row for row in existing_rows}
        latest_snapshot = (
            _manager(snapshot_model, alias)
            .filter(profile_key=active.profile_key)
            .order_by("-generated_at")
            .first()
            if active is not None
            else None
        )
        legacy = _manager(legacy_model, alias).filter(pk=1).first()
        provider = _manager(provider_model, alias).filter(pk=1).first()

        desired_values: dict[str, object] = {}
        if legacy is not None:
            desired_values.update(
                {key: getattr(legacy, field_name) for key, field_name in SYSTEM_FIELD_MAP}
            )
        if provider is not None:
            desired_values.update(
                {key: getattr(provider, field_name) for key, field_name in PROVIDER_FIELD_MAP}
            )

        desired_secret_refs: dict[str, str] = {}
        for definition_key, legacy_field, secret_ref in BACKUP_SECRET_MAP:
            canonical_secret = _manager(secret_model, alias).filter(secret_ref=secret_ref).first()
            if canonical_secret is not None and str(canonical_secret.encrypted_value or ""):
                desired_secret_refs[definition_key] = secret_ref
                continue
            legacy_ciphertext = str(getattr(legacy, legacy_field, "") or "")
            if not legacy_ciphertext:
                continue
            plaintext = _decrypt_legacy_secret(legacy_ciphertext)
            _manager(secret_model, alias).update_or_create(
                secret_ref=secret_ref,
                defaults={"encrypted_value": _encrypt_config_center_secret(plaintext)},
            )
            desired_secret_refs[definition_key] = secret_ref

        if not _manager(state_model, alias).filter(pk=1).exists():
            state_defaults = {
                "last_sent_at": getattr(legacy, "backup_last_sent_at", None),
                "download_token_digest": str(
                    getattr(legacy, "backup_download_token_digest", "") or ""
                ),
                "download_token_expires_at": getattr(
                    legacy, "backup_download_token_expires_at", None
                ),
                "download_token_consumed_at": getattr(legacy, "backup_download_consumed_at", None),
            }
            _manager(state_model, alias).create(pk=1, **state_defaults)

        required_keys = set(desired_values) | set(desired_secret_refs)
        existing_secret_keys = {
            key for key, row in existing_by_key.items() if str(row.secret_ref or "").strip()
        }
        snapshot_values = (
            dict(latest_snapshot.resolved_values or {}) if latest_snapshot is not None else {}
        )
        if (
            active is not None
            and required_keys.issubset(existing_by_key)
            and set(desired_secret_refs).issubset(existing_secret_keys)
            and (set(desired_values) - set(desired_secret_refs)).issubset(snapshot_values)
            and latest_snapshot is not None
            and latest_snapshot.profile_id == active.profile_id
            and latest_snapshot.profile_version == active.version
        ):
            return
        if not required_keys and active is None:
            return

        next_values: dict[str, dict[str, object]] = {
            row.definition_key: {
                "value_json": row.value_json,
                "secret_ref": row.secret_ref,
                "source": row.source,
                "validation_status": row.validation_status,
                "validation_error": row.validation_error,
            }
            for row in existing_rows
        }
        materialized_keys: set[str] = set()
        for definition_key, value in desired_values.items():
            if definition_key in next_values:
                continue
            next_values[definition_key] = {
                "value_json": value,
                "secret_ref": "",
                "source": "legacy_materialization_0015",
                "validation_status": "valid",
                "validation_error": "",
            }
            materialized_keys.add(definition_key)
        for definition_key, secret_ref in desired_secret_refs.items():
            if definition_key in next_values:
                continue
            next_values[definition_key] = {
                "value_json": None,
                "secret_ref": secret_ref,
                "source": "legacy_materialization_0015",
                "validation_status": "valid",
                "validation_error": "",
            }
            materialized_keys.add(definition_key)

        resolved_values = {
            key: payload["value_json"]
            for key, payload in next_values.items()
            if not str(payload["secret_ref"] or "").strip()
        }
        snapshot_hash = _hash_values(resolved_values)
        now = timezone.now()
        profile_key = active.profile_key if active is not None else environment
        version = (
            max(
                _manager(profile_model, alias)
                .filter(profile_key=profile_key)
                .values_list("version", flat=True),
                default=0,
            )
            + 1
        )
        next_profile_id = uuid.uuid4()
        if active is not None:
            _manager(profile_model, alias).filter(environment=environment, status="active").update(
                status="superseded"
            )
        _manager(profile_model, alias).create(
            profile_id=next_profile_id,
            profile_key=profile_key,
            environment=environment,
            version=version,
            status="active",
            based_on_profile=str(active.profile_id) if active is not None else "",
            content_hash=snapshot_hash,
            created_by="migration:0015",
            activated_by="migration:0015",
            created_at=now,
            activated_at=now,
            change_reason="Materialize remaining legacy runtime configuration groups",
        )
        _manager(value_model, alias).bulk_create(
            [
                value_model(
                    value_id=uuid.uuid4(),
                    profile_id=next_profile_id,
                    definition_key=key,
                    **payload,
                )
                for key, payload in sorted(next_values.items())
            ]
        )
        before_projection = (
            dict(latest_snapshot.resolved_values or {}) if latest_snapshot is not None else {}
        )
        _manager(revision_model, alias).create(
            revision_id=uuid.uuid4(),
            profile_id=next_profile_id,
            before_hash=str(active.content_hash or "") if active is not None else "",
            after_hash=snapshot_hash,
            changed_keys=sorted(materialized_keys),
            before_projection=before_projection,
            after_projection=resolved_values,
            actor="migration:0015",
            reason="Materialize remaining legacy runtime configuration groups",
            changed_at=now,
            validation_evidence={"valid": True, "materialized_keys": sorted(materialized_keys)},
        )
        _manager(snapshot_model, alias).create(
            snapshot_id=uuid.uuid4(),
            profile_id=next_profile_id,
            profile_key=profile_key,
            profile_version=version,
            snapshot_hash=snapshot_hash,
            resolved_values=resolved_values,
            generated_at=now,
            effective_from=now,
            validation_report={"valid": True, "materialized_keys": sorted(materialized_keys)},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("config_center", "0014_materialize_qlib_runtime_profile"),
        ("data_center", "0066_make_retention_digest_widening_reversible"),
    ]

    operations = [
        migrations.RunPython(
            materialize_remaining_runtime_groups,
            migrations.RunPython.noop,
        ),
    ]
