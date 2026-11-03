"""App-neutral bridge for Config Center runtime read ports.

The configuration app owns runtime-profile resolution and storage-budget policy
evaluation.  Consumers register against this small Protocol at the composition
root instead of importing Config Center application modules directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RuntimeConfigDefinitionSpec:
    """App-neutral scalar configuration metadata supplied to the owner."""

    key: str
    namespace: str
    owner_app: str
    value_type: Literal["bool", "int", "string", "bytes"]
    criticality: Literal["bootstrap", "critical", "normal", "experimental"] = "normal"
    reload_mode: Literal["immediate", "next_task", "restart_required"] = "next_task"
    secret: bool = False
    description: str = ""
    minimum: int | None = None


@runtime_checkable
class RuntimeConfigProfileRead(Protocol):
    """App-neutral read view of one active Config Center profile."""

    @property
    def profile_id(self) -> str:
        """Return the stable identifier of this profile."""
        ...

    @property
    def profile_key(self) -> str:
        """Return the configuration key identifying this profile family."""
        ...

    @property
    def environment(self) -> str:
        """Return the runtime environment to which this profile applies."""
        ...

    @property
    def version(self) -> int:
        """Return this profile's immutable version number."""
        ...

    @property
    def status(self) -> str:
        """Return the owner's profile status value."""
        ...

    @property
    def content_hash(self) -> str:
        """Return the owner's content hash for this profile version."""
        ...

    @property
    def created_at(self) -> datetime:
        """Return the timezone-aware profile creation time."""
        ...

    @property
    def activated_at(self) -> datetime | None:
        """Return the timezone-aware activation time, when available."""
        ...

    def __post_init__(self) -> None:
        """Revalidate the owner-created immutable profile value."""


@runtime_checkable
class RuntimeConfigSnapshotRead(Protocol):
    """App-neutral read view of one immutable resolved runtime snapshot."""

    @property
    def snapshot_id(self) -> str:
        """Return the stable identifier of this immutable snapshot."""
        ...

    @property
    def profile_id(self) -> str:
        """Return the identifier of the profile resolved by this snapshot."""
        ...

    @property
    def profile_key(self) -> str:
        """Return the configuration key identifying the resolved profile."""
        ...

    @property
    def profile_version(self) -> int:
        """Return the version of the profile resolved by this snapshot."""
        ...

    @property
    def snapshot_hash(self) -> str:
        """Return the owner's integrity hash for this resolved snapshot."""
        ...

    @property
    def resolved_values(self) -> Mapping[str, object]:
        """Return the resolved values as a read-only app-neutral mapping."""
        ...

    @property
    def generated_at(self) -> datetime:
        """Return the timezone-aware time this snapshot was generated."""
        ...

    @property
    def effective_from(self) -> datetime | None:
        """Return the timezone-aware effective time, when declared."""
        ...

    def __post_init__(self) -> None:
        """Revalidate the owner-created immutable snapshot value."""


@dataclass(frozen=True, slots=True)
class ActiveRuntimeValueEvidence:
    """Bind one value to immutable profile and snapshot evidence.

    ``known_at`` preserves the persisted profile creation clock because the
    runtime profile has no separate known-at field. ``effective_at`` preserves
    the snapshot's declared effective-from clock.
    """

    environment: str
    definition_key: str
    value: object
    profile_id: str
    profile_key: str
    profile_version: int
    profile_content_hash: str
    snapshot_id: str
    snapshot_hash: str
    created_at: datetime
    known_at: datetime
    activated_at: datetime
    snapshot_generated_at: datetime
    effective_at: datetime
    as_of: datetime


class ConfigCenterRuntimeReadPort(Protocol):
    """Config Center-owned runtime operations used by registered consumers."""

    def get_active_runtime_secret_ref(self, *, environment: str, definition_key: str) -> str | None:
        """Read a secret reference without returning secret material."""

    def register_runtime_definitions(
        self, specifications: tuple[RuntimeConfigDefinitionSpec, ...]
    ) -> tuple[str, ...]:
        """Validate and persist definition metadata through the owner."""

    def get_active_runtime_value(
        self,
        *,
        environment: str,
        definition_key: str,
        as_of: datetime | None = None,
    ) -> object | None:
        """Return one typed value from the active snapshot at an optional cutoff."""

    def get_active_runtime_profile(self, environment: str) -> RuntimeConfigProfileRead | None:
        """Return the exact active profile selected by the owner."""

    def get_latest_runtime_snapshot(self, profile_key: str) -> RuntimeConfigSnapshotRead | None:
        """Return the immutable resolved snapshot for one profile key."""

    def evaluate_storage_pressure(
        self,
        *,
        used_bytes: int,
        actual_capacity_bytes: int | None = None,
    ) -> dict[str, object]:
        """Evaluate observed storage usage against the active policy."""

    def collect_storage_capacity_profile(
        self,
        *,
        environment: str,
        source: str,
    ) -> dict[str, object]:
        """Collect and persist one policy-bound capacity observation payload."""


def read_active_runtime_value_evidence_from_port(
    provider: ConfigCenterRuntimeReadPort,
    *,
    environment: str,
    definition_key: str,
    as_of: datetime,
) -> ActiveRuntimeValueEvidence | None:
    """Bind one typed value to repeated, unchanged profile and snapshot reads."""

    if (
        type(environment) is not str
        or type(definition_key) is not str
        or not environment.strip()
        or not definition_key.strip()
        or not _is_aware_runtime_cutoff(as_of)
    ):
        return None
    try:
        profile_before = provider.get_active_runtime_profile(environment)
        if profile_before is None:
            return None
        snapshot_before = provider.get_latest_runtime_snapshot(profile_before.profile_key)
        if snapshot_before is None:
            return None
        value_before = provider.get_active_runtime_value(
            environment=environment,
            definition_key=definition_key,
            as_of=as_of,
        )
        profile_after = provider.get_active_runtime_profile(environment)
        if profile_after is None:
            return None
        snapshot_after = provider.get_latest_runtime_snapshot(profile_after.profile_key)
        if snapshot_after is None:
            return None
        value_after = provider.get_active_runtime_value(
            environment=environment,
            definition_key=definition_key,
            as_of=as_of,
        )
        profile_final = provider.get_active_runtime_profile(environment)
        if profile_final is None:
            return None
        snapshot_final = provider.get_latest_runtime_snapshot(profile_final.profile_key)
        if snapshot_final is None:
            return None
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None

    if value_before is None or value_after is None:
        return None
    if value_before != value_after:
        return None
    if (
        profile_before != profile_after
        or profile_after != profile_final
        or snapshot_before != snapshot_after
        or snapshot_after != snapshot_final
    ):
        return None
    if not _runtime_profile_snapshot_match(profile_after, snapshot_after, environment):
        return None
    if snapshot_after.resolved_values.get(definition_key) != value_after:
        return None
    if snapshot_after.effective_from is None or profile_after.activated_at is None:
        return None

    return ActiveRuntimeValueEvidence(
        environment=environment,
        definition_key=definition_key,
        value=deepcopy(value_after),
        profile_id=profile_after.profile_id,
        profile_key=profile_after.profile_key,
        profile_version=profile_after.version,
        profile_content_hash=profile_after.content_hash,
        snapshot_id=snapshot_after.snapshot_id,
        snapshot_hash=snapshot_after.snapshot_hash,
        created_at=profile_after.created_at,
        known_at=profile_after.created_at,
        activated_at=profile_after.activated_at,
        snapshot_generated_at=snapshot_after.generated_at,
        effective_at=snapshot_after.effective_from,
        as_of=as_of,
    )


def _runtime_profile_snapshot_match(
    profile: RuntimeConfigProfileRead,
    snapshot: RuntimeConfigSnapshotRead,
    environment: str,
) -> bool:
    """Require matching active profile identity and its declared effective clock."""

    return (
        profile.environment == environment
        and profile.status == "active"
        and profile.activated_at is not None
        and profile.activated_at == snapshot.effective_from
        and (snapshot.profile_id, snapshot.profile_key, snapshot.profile_version)
        == (profile.profile_id, profile.profile_key, profile.version)
    )


def _is_aware_runtime_cutoff(value: datetime) -> bool:
    """Return whether a cutoff is an exact timezone-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() is not None
    except (OverflowError, TypeError, ValueError):
        return False


_provider: ConfigCenterRuntimeReadPort | None = None


def configure_config_center_runtime_port(provider: ConfigCenterRuntimeReadPort) -> None:
    """Register the Config Center-owned runtime facade at the composition root."""

    global _provider
    _provider = provider


def get_active_runtime_value(
    *,
    environment: str,
    definition_key: str,
    as_of: datetime | None = None,
) -> object | None:
    """Read one active runtime value at the optional cutoff through its owner."""

    if _provider is None:
        return None
    return _provider.get_active_runtime_value(
        environment=environment,
        definition_key=definition_key,
        as_of=as_of,
    )


def get_active_runtime_profile(environment: str) -> RuntimeConfigProfileRead | None:
    """Read one active profile through the configured Config Center owner."""

    if _provider is None:
        return None
    return _provider.get_active_runtime_profile(environment)


def get_latest_runtime_snapshot(profile_key: str) -> RuntimeConfigSnapshotRead | None:
    """Read one immutable profile snapshot through the configured owner."""

    if _provider is None:
        return None
    return _provider.get_latest_runtime_snapshot(profile_key)


def get_active_runtime_value_evidence(
    *,
    environment: str,
    definition_key: str,
    as_of: datetime,
) -> ActiveRuntimeValueEvidence | None:
    """Read stable typed-value provenance through the registered Config Center owner."""

    if _provider is None:
        return None
    return read_active_runtime_value_evidence_from_port(
        _provider,
        environment=environment,
        definition_key=definition_key,
        as_of=as_of,
    )


def get_active_runtime_secret_ref(*, environment: str, definition_key: str) -> str | None:
    """Read an owner-validated secret ref, returning None before registration."""

    if _provider is None:
        return None
    return _provider.get_active_runtime_secret_ref(
        environment=environment, definition_key=definition_key
    )


def register_runtime_definitions(
    definitions: tuple[RuntimeConfigDefinitionSpec, ...],
) -> tuple[str, ...]:
    """Persist supplied metadata only through the configured owner facade."""

    if _provider is None:
        raise RuntimeError("config_center_runtime_port_unconfigured")
    return _provider.register_runtime_definitions(definitions)


def evaluate_storage_pressure(
    *,
    used_bytes: int,
    actual_capacity_bytes: int | None = None,
) -> dict[str, object]:
    """Evaluate storage pressure through the owner facade, fail-closed if absent."""

    if _provider is None:
        return {
            "state": "blocked",
            "used_bytes": used_bytes,
            "effective_capacity_bytes": None,
            "configured_capacity_bytes": None,
            "usage_ratio": None,
            "reason": "config_center_runtime_port_unconfigured",
        }

    try:
        return _provider.evaluate_storage_pressure(
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
            "reason": "config_center_storage_pressure_unavailable",
        }


def collect_storage_capacity_profile(
    *,
    environment: str,
    source: str,
) -> dict[str, object]:
    """Collect policy-bound capacity evidence through the owner facade."""

    if _provider is None:
        raise RuntimeError("config_center_runtime_port_unconfigured")
    return _provider.collect_storage_capacity_profile(
        environment=environment,
        source=source,
    )


def activate_runtime_profile_patch(
    *,
    environment: str,
    patch: Mapping[str, object],
    bootstrap_values: Mapping[str, object] | None,
    secret_ref_patch: Mapping[str, str] | None = None,
    actor: str,
    reason: str,
) -> dict[str, object]:
    """Activate a typed runtime patch through the configured owner bridge."""

    if _provider is None:
        raise RuntimeError("config_center_runtime_port_unconfigured")
    callback = getattr(_provider, "activate_runtime_profile_patch_payload", None)
    if not callable(callback):
        raise RuntimeError("config_center_runtime_write_port_unconfigured")
    options: dict[str, object] = {
        "environment": environment,
        "patch": patch,
        "bootstrap_values": bootstrap_values,
        "actor": actor,
        "reason": reason,
    }
    if secret_ref_patch is not None:
        options["secret_ref_patch"] = secret_ref_patch
    result = callback(**options)
    if not isinstance(result, dict):
        raise TypeError("Config Center runtime write port returned an invalid payload")
    return dict(result)


__all__ = [
    "ActiveRuntimeValueEvidence",
    "ConfigCenterRuntimeReadPort",
    "RuntimeConfigDefinitionSpec",
    "RuntimeConfigProfileRead",
    "RuntimeConfigSnapshotRead",
    "activate_runtime_profile_patch",
    "collect_storage_capacity_profile",
    "configure_config_center_runtime_port",
    "evaluate_storage_pressure",
    "get_active_runtime_profile",
    "get_active_runtime_value",
    "get_active_runtime_value_evidence",
    "get_active_runtime_secret_ref",
    "get_latest_runtime_snapshot",
    "register_runtime_definitions",
    "read_active_runtime_value_evidence_from_port",
]
