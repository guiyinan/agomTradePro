"""Application ports and use cases for versioned runtime configuration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import uuid4

from apps.config_center.domain.runtime_config import (
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigRevision,
    RuntimeConfigSnapshot,
    RuntimeConfigValue,
    RuntimeProfileStatus,
    StorageBudgetPolicy,
)


class RuntimeConfigDefinitionRepositoryPort(Protocol):
    """Persistence port for the configuration definition registry."""

    def list_all(self) -> list[RuntimeConfigDefinition]: ...

    def get(self, key: str) -> RuntimeConfigDefinition | None: ...

    def save(self, definition: RuntimeConfigDefinition) -> RuntimeConfigDefinition: ...


class RuntimeConfigProfileRepositoryPort(Protocol):
    """Persistence port for profiles."""

    def save(self, profile: RuntimeConfigProfile) -> RuntimeConfigProfile: ...

    def get(self, profile_id: str) -> RuntimeConfigProfile | None: ...

    def get_active(self, environment: str) -> RuntimeConfigProfile | None: ...


class RuntimeConfigValueRepositoryPort(Protocol):
    """Persistence port for profile values."""

    def save(self, value: RuntimeConfigValue) -> RuntimeConfigValue: ...

    def list_for_profile(self, profile_id: str) -> list[RuntimeConfigValue]: ...


class RuntimeConfigRevisionRepositoryPort(Protocol):
    """Persistence port for immutable revision evidence."""

    def save(self, revision: RuntimeConfigRevision) -> RuntimeConfigRevision: ...


class RuntimeConfigSnapshotRepositoryPort(Protocol):
    """Persistence port for resolved snapshots."""

    def save(self, snapshot: RuntimeConfigSnapshot) -> RuntimeConfigSnapshot: ...

    def get_latest(self, profile_key: str) -> RuntimeConfigSnapshot | None: ...


class StorageBudgetRepositoryPort(Protocol):
    """Persistence port for the active storage policy."""

    def save(self, policy: StorageBudgetPolicy) -> StorageBudgetPolicy: ...

    def get_active(self) -> StorageBudgetPolicy | None: ...


class RuntimeConfigService:
    """Validate, activate and resolve one versioned runtime profile."""

    def __init__(
        self,
        definitions: RuntimeConfigDefinitionRepositoryPort,
        profiles: RuntimeConfigProfileRepositoryPort,
        values: RuntimeConfigValueRepositoryPort,
        revisions: RuntimeConfigRevisionRepositoryPort,
        snapshots: RuntimeConfigSnapshotRepositoryPort,
    ) -> None:
        self._definitions = definitions
        self._profiles = profiles
        self._values = values
        self._revisions = revisions
        self._snapshots = snapshots

    def get_active_profile(self, environment: str) -> RuntimeConfigProfile | None:
        """Return the active typed profile for an environment."""

        return self._profiles.get_active(environment)

    def get_latest_snapshot(self, profile_key: str) -> RuntimeConfigSnapshot | None:
        """Return the latest immutable resolved snapshot for a profile key."""

        return self._snapshots.get_latest(profile_key)

    def validate_active_profile(self, environment: str) -> dict[str, object]:
        """Validate values belonging to the active profile for one environment.

        This is intentionally a read-only check used by bootstrap/reconcile
        commands and readiness evidence.  It does not activate or mutate a
        profile, and it applies the same definition validation as activation.
        """

        normalized_environment = str(environment or "").strip()
        if not normalized_environment:
            return {
                "valid": False,
                "environment": normalized_environment,
                "errors": ("environment_required",),
                "profile_id": None,
                "profile_key": None,
            }
        profile = self._profiles.get_active(normalized_environment)
        if profile is None:
            return {
                "valid": False,
                "environment": normalized_environment,
                "errors": ("active_profile_missing",),
                "profile_id": None,
                "profile_key": None,
            }
        values = tuple(self._values.list_for_profile(profile.profile_id))
        validation = self.validate_values(values)
        errors = list(cast(tuple[str, ...], validation["errors"]))
        if any(value.profile_id != profile.profile_id for value in values):
            errors.append("profile_id_mismatch")
        definitions = {item.key: item for item in self._definitions.list_all()}
        supplied = {value.definition_key for value in values}
        errors.extend(
            f"missing_critical_definition:{definition.key}"
            for definition in definitions.values()
            if definition.criticality.value in {"bootstrap", "critical"}
            and not definition.is_deprecated
            and definition.key not in supplied
        )
        return {
            "valid": not errors,
            "environment": normalized_environment,
            "errors": tuple(errors),
            "validated": validation["validated"],
            "profile_id": profile.profile_id,
            "profile_key": profile.profile_key,
            "profile_version": profile.version,
        }

    def validate_values(self, values: tuple[RuntimeConfigValue, ...]) -> dict[str, object]:
        """Validate values against the registered definitions."""

        definitions = {item.key: item for item in self._definitions.list_all()}
        errors: list[str] = []
        validated = 0
        seen_keys: set[str] = set()
        for value in values:
            if value.profile_id.strip() == "":
                errors.append(f"profile_id_required:{value.definition_key}")
            if value.definition_key in seen_keys:
                errors.append(f"duplicate_definition:{value.definition_key}")
                continue
            seen_keys.add(value.definition_key)
            definition = definitions.get(value.definition_key)
            if definition is None:
                errors.append(f"unknown_definition:{value.definition_key}")
                continue
            try:
                definition.validate(value.value_json, secret_ref=value.secret_ref)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            validated += 1
        return {"valid": not errors, "validated": validated, "errors": tuple(errors)}

    def preview(
        self,
        profile: RuntimeConfigProfile,
        values: tuple[RuntimeConfigValue, ...],
    ) -> dict[str, object]:
        """Return a side-effect-free activation/impact preview."""

        validation = self.validate_values(values)
        definitions = {item.key: item for item in self._definitions.list_all()}
        active = self._profiles.get_active(profile.environment)
        before_values = (
            self._values.list_for_profile(active.profile_id) if active is not None else []
        )
        before = {
            item.definition_key: item.secret_ref if item.secret_ref else item.value_json
            for item in before_values
        }
        after = {
            item.definition_key: item.secret_ref if item.secret_ref else item.value_json
            for item in values
        }
        changed_keys = tuple(
            sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
        )
        reload_modes = {
            key: definitions[key].reload_mode.value for key in changed_keys if key in definitions
        }
        return {
            "valid": bool(validation["valid"]),
            "errors": validation["errors"],
            "validated": validation["validated"],
            "environment": profile.environment,
            "profile_key": profile.profile_key,
            "before_profile_id": active.profile_id if active is not None else None,
            "before_hash": active.content_hash if active is not None else "",
            "after_hash": RuntimeConfigSnapshot.hash_values(after),
            "changed_keys": changed_keys,
            "reload_modes": reload_modes,
            "impact": {
                "critical_changes": tuple(
                    key
                    for key in changed_keys
                    if key in definitions
                    and definitions[key].criticality.value in {"bootstrap", "critical"}
                ),
                "restart_required": tuple(
                    key for key in changed_keys if reload_modes.get(key) == "restart_required"
                ),
            },
        }

    def activate(
        self,
        profile: RuntimeConfigProfile,
        values: tuple[RuntimeConfigValue, ...],
        *,
        actor: str,
        reason: str,
        release_ref: str = "",
    ) -> tuple[RuntimeConfigProfile, RuntimeConfigSnapshot]:
        """Validate and atomically publish a profile plus resolved snapshot."""

        if profile.environment.strip() == "":
            raise ValueError("Runtime profile environment is required")
        if any(value.profile_id != profile.profile_id for value in values):
            raise ValueError("Runtime profile value profile_id mismatch")
        preview = self.preview(profile, values)
        validation = {
            "valid": preview["valid"],
            "validated": preview["validated"],
            "errors": preview["errors"],
        }
        if not bool(validation["valid"]):
            errors = cast(tuple[str, ...], validation["errors"])
            raise ValueError("Runtime profile validation failed: " + "; ".join(errors))
        definitions = {item.key: item for item in self._definitions.list_all()}
        previous = self._profiles.get_active(profile.environment)
        if previous is not None and profile.version <= previous.version:
            raise ValueError(
                f"Runtime profile version must advance beyond active version {previous.version}"
            )
        supplied = {item.definition_key for item in values}
        missing_critical = [
            definition.key
            for definition in definitions.values()
            if definition.criticality.value in {"bootstrap", "critical"}
            and not definition.is_deprecated
            and definition.key not in supplied
        ]
        if missing_critical:
            raise ValueError(
                "Missing critical runtime definitions: " + ", ".join(sorted(missing_critical))
            )
        resolved = {
            item.definition_key: item.secret_ref if item.secret_ref else item.value_json
            for item in values
        }
        snapshot_hash = RuntimeConfigSnapshot.hash_values(resolved)
        active_profile = replace(
            profile,
            status=RuntimeProfileStatus.ACTIVE,
            content_hash=snapshot_hash,
            activated_by=actor,
            activated_at=datetime.now(UTC),
            change_reason=reason,
            release_ref=release_ref,
        )
        saved_profile = self._profiles.save(active_profile)
        for value in values:
            self._values.save(value)
        revision = RuntimeConfigRevision(
            revision_id=str(uuid4()),
            profile_id=profile.profile_id,
            before_hash=previous.content_hash if previous is not None else "",
            after_hash=snapshot_hash,
            changed_keys=tuple(sorted(resolved)),
            before_projection=(
                {
                    item.definition_key: item.value_json
                    for item in self._values.list_for_profile(previous.profile_id)
                    if item.definition_key in definitions
                    and not definitions[item.definition_key].secret
                }
                if previous is not None
                else {}
            ),
            after_projection={
                key: value for key, value in resolved.items() if not definitions[key].secret
            },
            actor=actor,
            reason=reason,
            release_ref=release_ref,
        )
        self._revisions.save(revision)
        snapshot = RuntimeConfigSnapshot(
            snapshot_id=str(uuid4()),
            profile_id=saved_profile.profile_id,
            profile_key=saved_profile.profile_key,
            profile_version=saved_profile.version,
            snapshot_hash=snapshot_hash,
            resolved_values={
                key: value for key, value in resolved.items() if not definitions[key].secret
            },
            effective_from=saved_profile.activated_at,
            validation_report={"valid": True, "validated": validation["validated"]},
        )
        saved_snapshot = self._snapshots.save(snapshot)
        return saved_profile, saved_snapshot

    def rollback(
        self,
        profile: RuntimeConfigProfile,
        values: tuple[RuntimeConfigValue, ...],
        *,
        actor: str,
        reason: str,
        release_ref: str = "",
    ) -> tuple[RuntimeConfigProfile, RuntimeConfigSnapshot]:
        """Activate a previously validated profile as a new forward revision."""

        active = self._profiles.get_active(profile.environment)
        next_version = max(profile.version, (active.version + 1) if active is not None else 1)
        target = replace(
            profile,
            version=next_version,
            based_on_profile=active.profile_id if active is not None else profile.based_on_profile,
            status=RuntimeProfileStatus.DRAFT,
            activated_at=None,
        )
        return self.activate(target, values, actor=actor, reason=reason, release_ref=release_ref)


class StorageBudgetQueryService:
    """Single query port for storage policies; absence is a hard block."""

    def __init__(self, repository: StorageBudgetRepositoryPort) -> None:
        self._repository = repository

    def get_active(self) -> StorageBudgetPolicy | None:
        """Return the active policy without applying a code fallback."""

        return self._repository.get_active()

    def require_active(self) -> StorageBudgetPolicy:
        """Return the active policy or fail closed when none is configured."""

        policy = self._repository.get_active()
        if policy is None or not policy.active:
            raise RuntimeError("storage_budget_policy_missing_or_inactive")
        return policy


__all__ = [
    "RuntimeConfigDefinitionRepositoryPort",
    "RuntimeConfigProfileRepositoryPort",
    "RuntimeConfigRevisionRepositoryPort",
    "RuntimeConfigService",
    "RuntimeConfigSnapshotRepositoryPort",
    "RuntimeConfigValueRepositoryPort",
    "StorageBudgetQueryService",
    "StorageBudgetRepositoryPort",
]
