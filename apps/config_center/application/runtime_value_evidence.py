"""Read typed runtime values with their stable active-profile provenance."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from apps.config_center.application import runtime_public
from apps.config_center.domain.runtime_config import (
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeProfileStatus,
)


@dataclass(frozen=True, slots=True)
class ActiveRuntimeValueEvidence:
    """A value bound to one unchanged active profile and immutable snapshot.

    ``known_at`` is the persisted profile ``created_at`` clock: Config Center has
    no separate known-at field. ``effective_at`` is the snapshot's explicit
    ``effective_from`` clock. The two fields are copied from their real sources.
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


def read_active_runtime_value_evidence(
    *,
    environment: str,
    definition_key: str,
    as_of: datetime,
) -> ActiveRuntimeValueEvidence | None:
    """Return a cutoff-qualified value only when repeated reads keep one revision.

    The public runtime value getter remains the source of truth for profile,
    snapshot hash, persisted-value, and cutoff eligibility. This adapter reads
    the matching profile and snapshot around two qualified value reads and fails
    closed if any identity, immutable record, or returned value changes.
    """

    if (
        type(environment) is not str
        or type(definition_key) is not str
        or not environment.strip()
        or not definition_key.strip()
        or not _is_aware(as_of)
    ):
        return None
    try:
        profile_before = runtime_public.get_active_runtime_profile(environment)
        if profile_before is None:
            return None
        snapshot_before = runtime_public.get_latest_runtime_snapshot(profile_before.profile_key)
        if snapshot_before is None:
            return None
        value_before = runtime_public.get_active_runtime_value(
            environment=environment,
            definition_key=definition_key,
            as_of=as_of,
        )
        profile_after = runtime_public.get_active_runtime_profile(environment)
        if profile_after is None:
            return None
        snapshot_after = runtime_public.get_latest_runtime_snapshot(profile_after.profile_key)
        if snapshot_after is None:
            return None
        value_after = runtime_public.get_active_runtime_value(
            environment=environment,
            definition_key=definition_key,
            as_of=as_of,
        )
        profile_final = runtime_public.get_active_runtime_profile(environment)
        if profile_final is None:
            return None
        snapshot_final = runtime_public.get_latest_runtime_snapshot(profile_final.profile_key)
        if snapshot_final is None:
            return None
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None

    if value_before is None or value_after is None:
        return None
    if (
        profile_before != profile_after
        or profile_after != profile_final
        or snapshot_before != snapshot_after
        or snapshot_after != snapshot_final
    ):
        return None
    if value_before != value_after:
        return None
    if not _profile_snapshot_match(profile_after, snapshot_after, environment):
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


def _profile_snapshot_match(
    profile: RuntimeConfigProfile,
    snapshot: RuntimeConfigSnapshot,
    environment: str,
) -> bool:
    """Require exact active identity and the effective clock checked publicly."""

    return (
        profile.environment == environment
        and profile.status is RuntimeProfileStatus.ACTIVE
        and profile.activated_at is not None
        and profile.activated_at == snapshot.effective_from
        and (snapshot.profile_id, snapshot.profile_key, snapshot.profile_version)
        == (profile.profile_id, profile.profile_key, profile.version)
    )


def _is_aware(value: datetime) -> bool:
    """Return whether a cutoff is an exact timezone-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() is not None
    except (OverflowError, TypeError, ValueError):
        return False


__all__ = ("ActiveRuntimeValueEvidence", "read_active_runtime_value_evidence")
