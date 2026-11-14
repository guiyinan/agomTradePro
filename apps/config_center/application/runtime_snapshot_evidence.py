"""Read fresh runtime profile and snapshot evidence through Config Center ports."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from apps.config_center.application.runtime_config import (
    RuntimeConfigDefinitionRepositoryPort,
    RuntimeConfigService,
    RuntimeConfigValueRepositoryPort,
)
from apps.config_center.domain.runtime_config import (
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeConfigValue,
    RuntimeProfileStatus,
    hash_public_runtime_projection,
    project_public_runtime_values,
    verify_runtime_profile_values,
)
from core.integration.config_center_runtime import ActiveRuntimeSnapshotEvidence


@dataclass(frozen=True, slots=True)
class _RuntimeSnapshotReadState:
    """One owner read set, retained only while checking the adjacent fresh pass."""

    profile: RuntimeConfigProfile
    snapshot: RuntimeConfigSnapshot
    values: tuple[RuntimeConfigValue, ...]
    definitions: tuple[RuntimeConfigDefinition, ...]


def _aware(value: object) -> bool:
    """Return whether a value is an exact timezone-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() is not None
    except (OverflowError, TypeError, ValueError):
        return False


def _valid_request(
    *,
    environment: object,
    definition_keys: object,
    as_of: object,
) -> bool:
    """Validate the exact environment, canonical keys, and aware cutoff."""

    return (
        type(environment) is str
        and bool(environment.strip())
        and environment.strip() == environment
        and type(definition_keys) is tuple
        and bool(definition_keys)
        and all(
            type(key) is str and bool(key) and key.strip() == key and "." in key
            for key in definition_keys
        )
        and definition_keys == tuple(sorted(set(definition_keys)))
        and _aware(as_of)
    )


def _read_state(
    *,
    runtime_config_service: RuntimeConfigService,
    value_repository: RuntimeConfigValueRepositoryPort,
    definition_repository: RuntimeConfigDefinitionRepositoryPort,
    environment: str,
    definition_keys: tuple[str, ...],
    as_of: datetime,
) -> _RuntimeSnapshotReadState | None:
    """Read and fully validate the latest active profile/snapshot source rows."""

    observed_profile = runtime_config_service.get_active_profile(environment)
    if type(observed_profile) is not RuntimeConfigProfile:
        return None
    profile = deepcopy(observed_profile)
    try:
        RuntimeConfigProfile.__post_init__(profile)
    except (TypeError, ValueError):
        return None
    if profile.environment != environment or profile.status is not RuntimeProfileStatus.ACTIVE:
        return None

    observed_snapshot = runtime_config_service.get_latest_snapshot(profile.profile_key)
    if type(observed_snapshot) is not RuntimeConfigSnapshot:
        return None
    snapshot = deepcopy(observed_snapshot)
    try:
        RuntimeConfigSnapshot.__post_init__(snapshot)
    except (TypeError, ValueError):
        return None
    if (
        (snapshot.profile_id, snapshot.profile_key, snapshot.profile_version)
        != (profile.profile_id, profile.profile_key, profile.version)
        or profile.activated_at is None
        or snapshot.effective_from != profile.activated_at
    ):
        return None

    raw_values = tuple(value_repository.list_for_profile(profile.profile_id))
    raw_definitions = tuple(definition_repository.list_all())
    if any(type(value) is not RuntimeConfigValue for value in raw_values):
        return None
    if any(type(definition) is not RuntimeConfigDefinition for definition in raw_definitions):
        return None
    values = deepcopy(raw_values)
    definitions = deepcopy(raw_definitions)
    try:
        full_profile_values = verify_runtime_profile_values(profile, values)
        definition_by_key = {definition.key: definition for definition in definitions}
        if len(definition_by_key) != len(definitions):
            return None
        public_values = project_public_runtime_values(full_profile_values, definition_by_key)
        snapshot_values = deepcopy(snapshot.resolved_values)
        if (
            public_values != snapshot_values
            or hash_public_runtime_projection(snapshot_values) != snapshot.snapshot_hash
            or any(
                key not in definition_by_key
                or definition_by_key[key].secret
                or key not in public_values
                for key in definition_keys
            )
        ):
            return None
    except (ArithmeticError, TypeError, ValueError):
        return None

    clocks = (
        profile.created_at,
        profile.activated_at,
        snapshot.generated_at,
        snapshot.effective_from,
    )
    if any(not _aware(clock) or clock > as_of for clock in clocks):
        return None
    return _RuntimeSnapshotReadState(
        profile=profile,
        snapshot=snapshot,
        values=values,
        definitions=definitions,
    )


def _same_read(
    first: _RuntimeSnapshotReadState,
    final: _RuntimeSnapshotReadState,
) -> bool:
    """Reject any profile, snapshot, full-value, or definition drift."""

    return (
        first.profile == final.profile
        and first.snapshot == final.snapshot
        and first.values == final.values
        and first.definitions == final.definitions
    )


def read_active_runtime_snapshot_evidence(
    *,
    runtime_config_service: RuntimeConfigService,
    value_repository: RuntimeConfigValueRepositoryPort,
    definition_repository: RuntimeConfigDefinitionRepositoryPort,
    environment: str,
    definition_keys: tuple[str, ...],
    as_of: datetime,
) -> ActiveRuntimeSnapshotEvidence | None:
    """Read a fresh, full-hash-verified public snapshot and its active profile.

    This performs two exact owner reads to catch both immutable successor
    publication and same-ID row drift. It never caches results between calls
    and exposes only the already-public snapshot projection, not secret refs.
    """

    if (
        not callable(getattr(runtime_config_service, "get_active_profile", None))
        or not callable(getattr(runtime_config_service, "get_latest_snapshot", None))
        or not callable(getattr(value_repository, "list_for_profile", None))
        or not callable(getattr(definition_repository, "list_all", None))
        or not _valid_request(
            environment=environment,
            definition_keys=definition_keys,
            as_of=as_of,
        )
    ):
        return None
    try:
        first = _read_state(
            runtime_config_service=runtime_config_service,
            value_repository=value_repository,
            definition_repository=definition_repository,
            environment=environment,
            definition_keys=definition_keys,
            as_of=as_of,
        )
        final = _read_state(
            runtime_config_service=runtime_config_service,
            value_repository=value_repository,
            definition_repository=definition_repository,
            environment=environment,
            definition_keys=definition_keys,
            as_of=as_of,
        )
    except (ArithmeticError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None
    if first is None or final is None or not _same_read(first, final):
        return None
    try:
        return ActiveRuntimeSnapshotEvidence(
            environment=environment,
            definition_keys=definition_keys,
            profile=first.profile,
            snapshot=first.snapshot,
            as_of=as_of,
        )
    except (ArithmeticError, AttributeError, TypeError, ValueError):
        return None


__all__ = ("read_active_runtime_snapshot_evidence",)
