"""Stable application ports for runtime configuration and storage policy."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from apps.config_center.application.runtime_definition_reconcile import (
    reconcile_runtime_definitions as _reconcile_runtime_definitions,
)
from apps.config_center.application.runtime_repository_provider import (
    get_runtime_config_service,
    get_runtime_definition_repository,
    get_runtime_value_repository,
    get_storage_budget_query_service,
    get_storage_capacity_observation_service,
)
from apps.config_center.application.storage_budget import StoragePressureGuard
from apps.config_center.domain.runtime_config import (
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeConfigValue,
    StorageBudgetPolicy,
    StorageCapacityObservation,
)

_QLIB_RUNTIME_FIELDS: tuple[tuple[str, str, type[object]], ...] = (
    ("enabled", "alpha.qlib.enabled", bool),
    ("provider_uri", "alpha.qlib.provider_uri", str),
    ("region", "alpha.qlib.region", str),
    ("model_path", "alpha.qlib.model_path", str),
    ("default_universe", "alpha.qlib.default_universe", str),
    ("default_feature_set_id", "alpha.qlib.default_feature_set_id", str),
    ("default_label_id", "alpha.qlib.default_label_id", str),
    ("train_queue_name", "alpha.qlib.train_queue_name", str),
    ("infer_queue_name", "alpha.qlib.infer_queue_name", str),
    ("allow_auto_activate", "alpha.qlib.allow_auto_activate", bool),
)

_DOMAIN_RUNTIME_FIELDS: tuple[tuple[str, str, type[object]], ...] = (
    ("alpha_fixed_provider", "alpha.runtime.fixed_provider", str),
    ("alpha_pool_mode", "alpha.runtime.pool_mode", str),
    ("market_color_convention", "config_center.market.color_convention", str),
    ("benchmark_code_map", "config_center.market.benchmark_code_map", dict),
    ("asset_proxy_code_map", "config_center.market.asset_proxy_code_map", dict),
)

_ACCOUNT_RUNTIME_FIELDS: tuple[tuple[str, str, type[object]], ...] = (
    ("require_user_approval", "account.require_user_approval", bool),
    ("auto_approve_first_admin", "account.auto_approve_first_admin", bool),
    ("default_mcp_enabled", "account.default_mcp_enabled", bool),
    ("allow_token_plaintext_view", "account.allow_token_plaintext_view", bool),
    ("user_agreement_content", "account.user_agreement_content", str),
    ("risk_warning_content", "account.risk_warning_content", str),
    ("notes", "account.notes", str),
)

_BACKUP_RUNTIME_FIELDS: tuple[tuple[str, str, type[object]], ...] = (
    ("backup_enabled", "backup.enabled", bool),
    ("backup_email", "backup.recipient_email", str),
    ("backup_app_base_url", "backup.app_base_url", str),
    ("backup_mail_from_email", "backup.mail_from_email", str),
    ("backup_smtp_host", "backup.smtp_host", str),
    ("backup_smtp_port", "backup.smtp_port", int),
    ("backup_smtp_username", "backup.smtp_username", str),
    ("backup_smtp_use_tls", "backup.smtp_use_tls", bool),
    ("backup_smtp_use_ssl", "backup.smtp_use_ssl", bool),
    ("backup_interval_days", "backup.interval_days", int),
    ("backup_link_ttl_days", "backup.link_ttl_days", int),
    ("backup_password_hint", "backup.password_hint", str),
    ("backup_archive_password_ref", "backup.archive_password", str),
    ("backup_smtp_password_ref", "backup.smtp_password", str),
)
_BACKUP_SECRET_DEFINITION_KEYS = frozenset({"backup.archive_password", "backup.smtp_password"})


def validate_runtime_values(values: tuple[RuntimeConfigValue, ...]) -> dict[str, object]:
    """Validate typed values against the registered definition catalog."""

    return get_runtime_config_service().validate_values(values)


def get_active_runtime_profile(environment: str) -> RuntimeConfigProfile | None:
    """Read the active typed runtime profile for an environment."""

    return get_runtime_config_service().get_active_profile(environment)


def get_latest_runtime_snapshot(profile_key: str) -> RuntimeConfigSnapshot | None:
    """Read the latest resolved snapshot for a profile key."""

    return get_runtime_config_service().get_latest_snapshot(profile_key)


def get_active_runtime_value(*, environment: str, definition_key: str) -> object | None:
    """Read one value from the active, version-matched runtime snapshot.

    Consumers must not read a raw profile value directly.  The active profile and
    its immutable snapshot are checked together so a stale snapshot cannot be
    mistaken for the currently active configuration.  Missing or unavailable
    configuration is represented by ``None`` and the caller owns its declared
    compatibility/fail-closed policy.
    """

    normalized_environment = str(environment or "").strip()
    normalized_key = str(definition_key or "").strip()
    if not normalized_environment or not normalized_key:
        return None
    try:
        profile = get_active_runtime_profile(normalized_environment)
    except RuntimeError:
        # Unit-level callers may provide an explicit value seam without a
        # configured database; the typed projection will use that seam below.
        return None
    if profile is None:
        return None
    try:
        snapshot = get_latest_runtime_snapshot(profile.profile_key)
    except RuntimeError:
        return None
    if snapshot is None:
        return None
    if snapshot.profile_id != profile.profile_id or snapshot.profile_version != profile.version:
        return None
    return snapshot.resolved_values.get(normalized_key)


def get_active_runtime_secret_ref(*, environment: str, definition_key: str) -> str | None:
    """Read one active profile's secret reference without resolving its value."""

    normalized_environment = str(environment or "").strip()
    normalized_key = str(definition_key or "").strip()
    if not normalized_environment or not normalized_key:
        return None
    try:
        profile = get_active_runtime_profile(normalized_environment)
    except RuntimeError:
        # A value-only test seam may be used without database access.
        return None
    if profile is None:
        return None
    try:
        snapshot = get_latest_runtime_snapshot(profile.profile_key)
    except RuntimeError:
        return None
    if snapshot is None:
        return None
    if snapshot.profile_id != profile.profile_id or snapshot.profile_version != profile.version:
        return None
    try:
        values = get_runtime_value_repository().list_for_profile(profile.profile_id)
    except RuntimeError:
        return None
    for value in values:
        if value.definition_key == normalized_key and value.secret_ref.strip():
            return value.secret_ref.strip()
    return None


def activate_runtime_profile_patch(
    *,
    environment: str,
    patch: Mapping[str, object],
    secret_ref_patch: Mapping[str, str] | None = None,
    bootstrap_values: Mapping[str, object] | None = None,
    bootstrap_secret_refs: Mapping[str, str] | None = None,
    actor: str,
    reason: str,
    release_ref: str = "",
) -> tuple[RuntimeConfigProfile, RuntimeConfigSnapshot]:
    """Activate one forward runtime-profile revision from a typed patch.

    Existing active values are carried forward by definition key. Optional
    ``bootstrap_values`` fill only keys absent from the active profile, making
    a legacy-to-typed import explicit and auditable rather than a runtime
    fallback. The caller's patch always wins over carried values.
    """

    normalized_environment = str(environment or "").strip()
    normalized_actor = str(actor or "").strip()
    normalized_reason = str(reason or "").strip()
    if not normalized_environment:
        raise ValueError("Runtime profile environment is required")
    if not normalized_actor:
        raise ValueError("Runtime profile actor is required")
    if not normalized_reason:
        raise ValueError("Runtime profile change reason is required")

    reconcile_runtime_definitions()
    value_repository = get_runtime_value_repository()
    active = get_active_runtime_profile(normalized_environment)
    existing_values = (
        value_repository.list_for_profile(active.profile_id) if active is not None else []
    )
    existing_by_key = {value.definition_key: value for value in existing_values}
    compatibility = dict(bootstrap_values or {})
    compatibility_secret_refs = {
        str(key).strip(): str(value).strip()
        for key, value in (bootstrap_secret_refs or {}).items()
        if str(key).strip() and str(value).strip()
    }
    normalized_patch = {str(key).strip(): value for key, value in patch.items()}
    normalized_secret_ref_patch = {
        str(key).strip(): str(value).strip()
        for key, value in (secret_ref_patch or {}).items()
        if str(key).strip() and str(value).strip()
    }
    if any(not key for key in normalized_patch):
        raise ValueError("Runtime profile patch contains an empty definition key")

    profile_id = str(uuid4())
    next_values: list[RuntimeConfigValue] = []
    for definition_key in sorted(
        set(existing_by_key)
        | set(compatibility)
        | set(compatibility_secret_refs)
        | set(normalized_patch)
        | set(normalized_secret_ref_patch)
    ):
        if definition_key in normalized_secret_ref_patch:
            next_values.append(
                RuntimeConfigValue(
                    profile_id=profile_id,
                    definition_key=definition_key,
                    value_json=None,
                    secret_ref=normalized_secret_ref_patch[definition_key],
                    source="admin_secret",
                )
            )
            continue
        if definition_key in normalized_patch:
            next_values.append(
                RuntimeConfigValue(
                    profile_id=profile_id,
                    definition_key=definition_key,
                    value_json=normalized_patch[definition_key],
                    source="admin",
                )
            )
            continue
        existing = existing_by_key.get(definition_key)
        if existing is not None:
            next_values.append(
                RuntimeConfigValue(
                    profile_id=profile_id,
                    definition_key=definition_key,
                    value_json=existing.value_json,
                    secret_ref=existing.secret_ref,
                    source=existing.source,
                    validation_status=existing.validation_status,
                    validation_error=existing.validation_error,
                )
            )
            continue
        next_values.append(
            RuntimeConfigValue(
                profile_id=profile_id,
                definition_key=definition_key,
                value_json=compatibility.get(definition_key),
                secret_ref=compatibility_secret_refs.get(definition_key, ""),
                source=(
                    "compatibility_secret_ref"
                    if definition_key in compatibility_secret_refs
                    else "compatibility_migration"
                ),
            )
        )

    next_profile = RuntimeConfigProfile(
        profile_id=profile_id,
        profile_key=active.profile_key if active is not None else normalized_environment,
        environment=normalized_environment,
        version=active.version + 1 if active is not None else 1,
        based_on_profile=active.profile_id if active is not None else "",
        created_by=normalized_actor,
        created_at=datetime.now(UTC),
    )
    return activate_runtime_profile(
        next_profile,
        tuple(next_values),
        actor=normalized_actor,
        reason=normalized_reason,
        release_ref=release_ref,
    )


def activate_runtime_profile_patch_payload(
    *,
    environment: str,
    patch: Mapping[str, object],
    secret_ref_patch: Mapping[str, str] | None = None,
    bootstrap_values: Mapping[str, object] | None = None,
    bootstrap_secret_refs: Mapping[str, str] | None = None,
    actor: str,
    reason: str,
) -> dict[str, object]:
    """Activate a typed patch and return non-secret revision evidence."""

    profile, snapshot = activate_runtime_profile_patch(
        environment=environment,
        patch=patch,
        secret_ref_patch=secret_ref_patch,
        bootstrap_values=bootstrap_values,
        bootstrap_secret_refs=bootstrap_secret_refs,
        actor=actor,
        reason=reason,
    )
    return {
        "profile_id": profile.profile_id,
        "profile_key": profile.profile_key,
        "profile_version": profile.version,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_hash": snapshot.snapshot_hash,
        "changed_keys": tuple(sorted(set(patch) | set(secret_ref_patch or {}))),
    }


def get_active_qlib_runtime_config(environment: str) -> dict[str, object] | None:
    """Resolve a complete Qlib runtime mapping from the active snapshot.

    The typed snapshot is an opt-in cutover path.  A partial, stale or malformed
    snapshot returns ``None`` so the owner can keep its explicitly documented
    SystemSettings compatibility path.  No values are invented here.
    """

    normalized_environment = str(environment or "").strip()
    if not normalized_environment:
        return None
    resolved: dict[str, object] = {}
    for field_name, definition_key, expected_type in _QLIB_RUNTIME_FIELDS:
        value = get_active_runtime_value(
            environment=normalized_environment,
            definition_key=definition_key,
        )
        if isinstance(value, bool) and expected_type is bool:
            resolved[field_name] = value
        elif isinstance(value, str) and expected_type is str and value.strip():
            resolved[field_name] = value
        else:
            return None

    provider_uri = str(resolved["provider_uri"])
    resolved["is_configured"] = bool(
        bool(resolved["enabled"]) and Path(provider_uri).expanduser().exists()
    )
    return resolved


def get_active_domain_runtime_config(environment: str) -> dict[str, object] | None:
    """Resolve typed Alpha/market runtime values from one active snapshot.

    The projection is intentionally all-or-nothing: a partial snapshot returns
    ``None`` so the owning repository can apply its explicitly documented
    compatibility policy rather than mixing values from two configuration
    sources.
    """

    return _get_typed_runtime_projection(environment, _DOMAIN_RUNTIME_FIELDS)


def get_active_account_runtime_config(environment: str) -> dict[str, object] | None:
    """Resolve account access/content values from one active typed snapshot."""

    return _get_typed_runtime_projection(environment, _ACCOUNT_RUNTIME_FIELDS)


def get_active_backup_delivery_config(environment: str) -> dict[str, object] | None:
    """Resolve the complete typed backup policy and secret references."""

    return _get_typed_runtime_projection(
        environment,
        _BACKUP_RUNTIME_FIELDS,
        secret_definition_keys=_BACKUP_SECRET_DEFINITION_KEYS,
    )


def _get_typed_runtime_projection(
    environment: str,
    fields: tuple[tuple[str, str, type[object]], ...],
    *,
    secret_definition_keys: frozenset[str] = frozenset(),
) -> dict[str, object] | None:
    """Resolve one all-or-nothing typed projection from an active snapshot."""

    normalized_environment = str(environment or "").strip()
    if not normalized_environment:
        return None

    resolved: dict[str, object] = {}
    for field_name, definition_key, expected_type in fields:
        value: object | None
        if definition_key in secret_definition_keys:
            value = get_active_runtime_secret_ref(
                environment=normalized_environment,
                definition_key=definition_key,
            )
            # Keep unit-test and explicit migration shims able to provide a
            # ref through the ordinary public-value seam; production snapshots
            # never expose secret values.
            if value is None:
                fallback = get_active_runtime_value(
                    environment=normalized_environment,
                    definition_key=definition_key,
                )
                value = fallback if isinstance(fallback, str) else None
        else:
            value = get_active_runtime_value(
                environment=normalized_environment,
                definition_key=definition_key,
            )
        if expected_type is dict:
            if not isinstance(value, dict):
                return None
            resolved[field_name] = dict(value)
        elif isinstance(value, expected_type):
            resolved[field_name] = value
        else:
            return None
    return resolved


def reconcile_runtime_definitions() -> tuple[RuntimeConfigDefinition, ...]:
    """Idempotently reconcile the Config Center-owned definition catalog."""

    return _reconcile_runtime_definitions(get_runtime_definition_repository())


def validate_active_runtime_profile(environment: str) -> dict[str, object]:
    """Validate the active profile without changing runtime state."""

    return get_runtime_config_service().validate_active_profile(environment)


def preview_runtime_profile(
    profile: RuntimeConfigProfile,
    values: tuple[RuntimeConfigValue, ...],
) -> dict[str, object]:
    """Return validation, changed keys and operational impact without writes."""

    return get_runtime_config_service().preview(profile, values)


def activate_runtime_profile(
    profile: RuntimeConfigProfile,
    values: tuple[RuntimeConfigValue, ...],
    *,
    actor: str,
    reason: str,
    release_ref: str = "",
) -> tuple[RuntimeConfigProfile, RuntimeConfigSnapshot]:
    """Activate a profile and return its immutable resolved snapshot."""

    return get_runtime_config_service().activate(
        profile,
        values,
        actor=actor,
        reason=reason,
        release_ref=release_ref,
    )


def rollback_runtime_profile(
    profile: RuntimeConfigProfile,
    values: tuple[RuntimeConfigValue, ...],
    *,
    actor: str,
    reason: str,
    release_ref: str = "",
) -> tuple[RuntimeConfigProfile, RuntimeConfigSnapshot]:
    """Restore a known-good profile as a new forward revision."""

    return get_runtime_config_service().rollback(
        profile,
        values,
        actor=actor,
        reason=reason,
        release_ref=release_ref,
    )


def get_active_storage_budget() -> StorageBudgetPolicy | None:
    """Read the active policy without silently defaulting capacity."""

    return get_storage_budget_query_service().get_active()


def require_active_storage_budget() -> StorageBudgetPolicy:
    """Read the active policy or raise a stable fail-closed error."""

    return get_storage_budget_query_service().require_active()


def evaluate_storage_pressure(
    *,
    used_bytes: int,
    actual_capacity_bytes: int | None = None,
) -> dict[str, object]:
    """Evaluate filesystem usage against the active policy without fallback."""

    try:
        report = StoragePressureGuard(get_storage_budget_query_service()).evaluate(
            used_bytes=used_bytes,
            actual_capacity_bytes=actual_capacity_bytes,
        )
    except Exception:
        return {
            "state": "blocked",
            "used_bytes": used_bytes,
            "effective_capacity_bytes": None,
            "configured_capacity_bytes": None,
            "usage_ratio": None,
            "reason": "storage_budget_unavailable",
        }
    return {
        "state": report.state.value,
        "used_bytes": report.used_bytes,
        "effective_capacity_bytes": report.effective_capacity_bytes,
        "configured_capacity_bytes": report.configured_capacity_bytes,
        "usage_ratio": report.usage_ratio,
        "reason": report.reason,
    }


def record_storage_capacity_observation(
    observation: StorageCapacityObservation,
) -> StorageCapacityObservation:
    """Persist one filesystem/database capacity observation."""

    return get_storage_capacity_observation_service().record(observation)


def get_latest_storage_capacity_observation(
    environment: str,
) -> StorageCapacityObservation | None:
    """Return the latest capacity observation without a fallback."""

    return get_storage_capacity_observation_service().get_latest(environment)


__all__ = [
    "activate_runtime_profile",
    "activate_runtime_profile_patch",
    "activate_runtime_profile_patch_payload",
    "evaluate_storage_pressure",
    "get_active_runtime_profile",
    "get_active_runtime_value",
    "get_active_runtime_secret_ref",
    "get_active_domain_runtime_config",
    "get_active_account_runtime_config",
    "get_active_backup_delivery_config",
    "get_active_qlib_runtime_config",
    "get_active_storage_budget",
    "get_latest_runtime_snapshot",
    "get_latest_storage_capacity_observation",
    "reconcile_runtime_definitions",
    "require_active_storage_budget",
    "preview_runtime_profile",
    "rollback_runtime_profile",
    "record_storage_capacity_observation",
    "validate_runtime_values",
    "validate_active_runtime_profile",
]
