"""Fail-closed Config Center binding for system-audit runtime policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TypedDict, TypeGuard

from apps.audit.application.system_audit_authority_provider import (
    SystemAuditAuthorityBundleSelector,
)
from apps.config_center.application.runtime_public import (
    get_active_runtime_profile,
    get_latest_runtime_snapshot,
)
from apps.config_center.domain.runtime_config import (
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeProfileStatus,
)


class _AuthoritySelectorPayload(TypedDict):
    actor_source_id: str
    actor_source_version: str
    actor_content_hash: str
    scope_source_id: str
    scope_source_version: str
    scope_content_hash: str


class SystemAuditRuntimeConfigurationUnavailable(RuntimeError):
    """Runtime audit configuration is absent or fails closed."""

    def __init__(self, reason_code: str) -> None:
        if not _is_canonical_token(reason_code, maximum=64):
            raise ValueError("runtime configuration reason_code must be canonical")
        super().__init__("system audit runtime configuration unavailable")
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class SystemAuditRuntimeConfigBinding:
    """Immutable audit runtime configuration bound to one snapshot."""

    mode: str
    outbox_enabled: bool
    authority_selector: SystemAuditAuthorityBundleSelector
    issuer_id: str
    snapshot_id: str
    snapshot_hash: str
    profile_id: str
    profile_key: str
    profile_version: int
    environment: str

    def __post_init__(self) -> None:
        """Validate the immutable binding at construction."""

        if (
            type(self.mode) is not str
            or self.mode not in {"off", "shadow", "required"}
            or type(self.outbox_enabled) is not bool
        ):
            raise ValueError("invalid audit runtime mode or outbox flag")
        if type(self.authority_selector) is not SystemAuditAuthorityBundleSelector:
            raise TypeError("authority selector type substitution")
        self.authority_selector.__post_init__()
        for value in (self.issuer_id, self.snapshot_id, self.profile_id, self.profile_key):
            if not _is_canonical_token(value, maximum=192):
                raise ValueError("runtime binding identity must be canonical")
        if not _is_canonical_token(self.environment, maximum=64):
            raise ValueError("runtime binding environment must be canonical")
        if (
            type(self.snapshot_hash) is not str
            or len(self.snapshot_hash) != 64
            or any(c not in "0123456789abcdef" for c in self.snapshot_hash)
        ):
            raise ValueError("snapshot_hash must be lowercase SHA-256")
        if type(self.profile_version) is not int or self.profile_version < 1:
            raise ValueError("profile_version must be positive")


def load_system_audit_runtime_config(*, environment: str) -> SystemAuditRuntimeConfigBinding:
    """Load and validate all audit settings from one active snapshot."""

    if not _is_canonical_token(environment, maximum=64):
        raise SystemAuditRuntimeConfigurationUnavailable("environment_invalid")
    try:
        profile = get_active_runtime_profile(environment)
        if type(profile) is not RuntimeConfigProfile:
            raise SystemAuditRuntimeConfigurationUnavailable("profile_unavailable")
        profile.__post_init__()
        if (
            profile.status is not RuntimeProfileStatus.ACTIVE
            or profile.environment != environment
            or not _is_canonical_token(profile.profile_id, maximum=192)
            or not _is_canonical_token(profile.profile_key, maximum=192)
        ):
            raise SystemAuditRuntimeConfigurationUnavailable("profile_unavailable")
        snapshot = get_latest_runtime_snapshot(profile.profile_key)
        if type(snapshot) is not RuntimeConfigSnapshot:
            raise SystemAuditRuntimeConfigurationUnavailable("snapshot_unavailable")
        snapshot.__post_init__()
        if not _is_canonical_token(snapshot.snapshot_id, maximum=192):
            raise SystemAuditRuntimeConfigurationUnavailable("snapshot_unavailable")
        if (snapshot.profile_id, snapshot.profile_key, snapshot.profile_version) != (
            profile.profile_id,
            profile.profile_key,
            profile.version,
        ):
            raise SystemAuditRuntimeConfigurationUnavailable("snapshot_profile_mismatch")
        if len(snapshot.snapshot_hash) != 64 or any(
            c not in "0123456789abcdef" for c in snapshot.snapshot_hash
        ):
            raise SystemAuditRuntimeConfigurationUnavailable("snapshot_hash_invalid")
        if RuntimeConfigSnapshot.hash_values(snapshot.resolved_values) != snapshot.snapshot_hash:
            raise SystemAuditRuntimeConfigurationUnavailable("snapshot_hash_mismatch")
        values = snapshot.resolved_values
        mode = values.get("audit.system_event.mode")
        enabled = values.get("audit.system_event.outbox_enabled")
        selector_raw = values.get("audit.system_event.authority_selector")
        if type(mode) is not str or mode not in {"off", "shadow", "required"}:
            raise SystemAuditRuntimeConfigurationUnavailable("mode_invalid")
        if type(enabled) is not bool:
            raise SystemAuditRuntimeConfigurationUnavailable("outbox_enabled_invalid")
        if not _is_selector_payload(selector_raw):
            raise SystemAuditRuntimeConfigurationUnavailable("authority_selector_invalid")
        try:
            selector = SystemAuditAuthorityBundleSelector(
                actor_source_id=selector_raw["actor_source_id"],
                actor_source_version=selector_raw["actor_source_version"],
                actor_content_hash=selector_raw["actor_content_hash"],
                scope_source_id=selector_raw["scope_source_id"],
                scope_source_version=selector_raw["scope_source_version"],
                scope_content_hash=selector_raw["scope_content_hash"],
            )
        except (TypeError, ValueError):
            raise SystemAuditRuntimeConfigurationUnavailable("authority_selector_invalid") from None
        issuer_id = (
            "audit-config:"
            + hashlib.sha256(
                json.dumps(
                    {
                        "snapshot_id": snapshot.snapshot_id,
                        "snapshot_hash": snapshot.snapshot_hash,
                        "profile_id": profile.profile_id,
                        "profile_key": profile.profile_key,
                        "profile_version": profile.version,
                        "environment": environment,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        return SystemAuditRuntimeConfigBinding(
            mode=mode,
            outbox_enabled=enabled,
            authority_selector=selector,
            issuer_id=issuer_id,
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            profile_id=profile.profile_id,
            profile_key=profile.profile_key,
            profile_version=profile.version,
            environment=environment,
        )
    except SystemAuditRuntimeConfigurationUnavailable:
        raise
    except Exception:
        raise SystemAuditRuntimeConfigurationUnavailable(
            "runtime_configuration_unavailable"
        ) from None


__all__ = [
    "SystemAuditRuntimeConfigBinding",
    "SystemAuditRuntimeConfigurationUnavailable",
    "load_system_audit_runtime_config",
]


def _is_selector_payload(value: object) -> TypeGuard[_AuthoritySelectorPayload]:
    """Narrow dynamic JSON to the exact six-string selector schema."""

    return (
        type(value) is dict
        and set(value)
        == {
            "actor_source_id",
            "actor_source_version",
            "actor_content_hash",
            "scope_source_id",
            "scope_source_version",
            "scope_content_hash",
        }
        and all(type(key) is str and type(item) is str for key, item in value.items())
    )


def _is_canonical_token(value: object, *, maximum: int) -> TypeGuard[str]:
    """Return whether a dynamic identity is one bounded canonical token."""

    return (
        type(value) is str
        and bool(value)
        and len(value) <= maximum
        and value.strip() == value
        and not any(character.isspace() for character in value)
    )
