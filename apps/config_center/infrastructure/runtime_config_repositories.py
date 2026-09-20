"""ORM repositories for the versioned runtime configuration control plane."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from uuid import UUID

from django.db import connection, transaction

from apps.config_center.domain.runtime_config import (
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigRevision,
    RuntimeConfigSnapshot,
    RuntimeConfigValue,
    StorageBudgetPolicy,
    hash_public_runtime_projection,
)

from .models import (
    RuntimeConfigDefinitionModel,
    RuntimeConfigProfileModel,
    RuntimeConfigRevisionModel,
    RuntimeConfigSnapshotModel,
    RuntimeConfigValueModel,
    StorageBudgetPolicyModel,
)


def _uuid(value: str) -> UUID:
    """Convert a domain ID to a UUID primary key."""

    return UUID(value)


class RuntimeConfigDefinitionRepository:
    """Read-only/write registry for typed definitions."""

    def list_all(self) -> list[RuntimeConfigDefinition]:
        """Return all definitions in deterministic key order."""

        return [
            model.to_domain()
            for model in RuntimeConfigDefinitionModel._default_manager.all().order_by("key")
        ]

    def get(self, key: str) -> RuntimeConfigDefinition | None:
        """Return a definition by stable key."""

        model = RuntimeConfigDefinitionModel._default_manager.filter(key=key).first()
        return model.to_domain() if model is not None else None

    def save(self, definition: RuntimeConfigDefinition) -> RuntimeConfigDefinition:
        """Upsert a definition by stable key."""

        model, _ = RuntimeConfigDefinitionModel._default_manager.update_or_create(
            key=definition.key,
            defaults={
                "namespace": definition.namespace,
                "owner_app": definition.owner_app,
                "value_type": definition.value_type.value,
                "unit": definition.unit,
                "constraints": definition.constraints,
                "criticality": definition.criticality.value,
                "secret": definition.secret,
                "reload_mode": definition.reload_mode.value,
                "description": definition.description,
                "user_impact": definition.user_impact,
                "is_deprecated": definition.is_deprecated,
                "replacement_key": definition.replacement_key,
            },
        )
        return model.to_domain()


class RuntimeConfigProfileRepository:
    """Versioned profile repository."""

    def save(self, profile: RuntimeConfigProfile) -> RuntimeConfigProfile:
        """Insert one immutable profile, allowing an exact idempotent retry."""

        profile_id = _uuid(profile.profile_id)
        existing = RuntimeConfigProfileModel._default_manager.filter(profile_id=profile_id).first()
        if existing is not None:
            if existing.to_domain() != profile:
                raise ValueError("runtime profiles are immutable")
            return existing.to_domain()
        model = RuntimeConfigProfileModel._default_manager.create(
            profile_id=profile_id,
            profile_key=profile.profile_key,
            environment=profile.environment,
            version=profile.version,
            status=profile.status.value,
            based_on_profile=profile.based_on_profile,
            content_hash=profile.content_hash,
            created_by=profile.created_by,
            activated_by=profile.activated_by,
            created_at=profile.created_at,
            activated_at=profile.activated_at,
            change_reason=profile.change_reason,
            release_ref=profile.release_ref,
        )
        return model.to_domain()

    def get(self, profile_id: str) -> RuntimeConfigProfile | None:
        """Return a profile by UUID."""

        model = RuntimeConfigProfileModel._default_manager.filter(
            profile_id=_uuid(profile_id)
        ).first()
        return model.to_domain() if model is not None else None

    def get_active(self, environment: str) -> RuntimeConfigProfile | None:
        """Return the active profile for one environment."""

        model = (
            RuntimeConfigProfileModel._default_manager.filter(
                environment=environment,
                status="active",
            )
            .order_by("-version")
            .first()
        )
        return model.to_domain() if model is not None else None


class RuntimeConfigValueRepository:
    """Profile value repository with definition-key idempotency."""

    def save(self, value: RuntimeConfigValue) -> RuntimeConfigValue:
        """Insert one immutable profile value, allowing an exact retry."""

        profile_id = _uuid(value.profile_id)
        existing = RuntimeConfigValueModel._default_manager.filter(
            profile_id=profile_id,
            definition_key=value.definition_key,
        ).first()
        if existing is not None:
            if existing.to_domain() != value:
                raise ValueError("runtime profile values are immutable")
            return existing.to_domain()
        model = RuntimeConfigValueModel._default_manager.create(
            profile_id=profile_id,
            definition_key=value.definition_key,
            value_json=value.value_json,
            secret_ref=value.secret_ref,
            source=value.source,
            validation_status=value.validation_status,
            validation_error=value.validation_error,
        )
        return model.to_domain()

    def list_for_profile(self, profile_id: str) -> list[RuntimeConfigValue]:
        """Return all values in stable definition-key order."""

        return [
            model.to_domain()
            for model in RuntimeConfigValueModel._default_manager.filter(
                profile_id=_uuid(profile_id)
            ).order_by("definition_key")
        ]


class RuntimeConfigRevisionRepository:
    """Append-only revision repository."""

    def save(self, revision: RuntimeConfigRevision) -> RuntimeConfigRevision:
        """Insert one immutable revision."""

        model = RuntimeConfigRevisionModel._default_manager.create(
            revision_id=_uuid(revision.revision_id),
            profile_id=_uuid(revision.profile_id),
            before_hash=revision.before_hash,
            after_hash=revision.after_hash,
            changed_keys=list(revision.changed_keys),
            before_projection=revision.before_projection,
            after_projection=revision.after_projection,
            actor=revision.actor,
            reason=revision.reason,
            changed_at=revision.changed_at,
            release_ref=revision.release_ref,
            validation_evidence=revision.validation_evidence,
        )
        return model.to_domain()


class RuntimeConfigSnapshotRepository:
    """Immutable resolved-snapshot repository."""

    def save(self, snapshot: RuntimeConfigSnapshot) -> RuntimeConfigSnapshot:
        """Insert one immutable snapshot, allowing an exact idempotent retry."""

        snapshot_id = _uuid(snapshot.snapshot_id)
        existing = RuntimeConfigSnapshotModel._default_manager.filter(
            snapshot_id=snapshot_id
        ).first()
        if existing is not None:
            if existing.to_domain() != snapshot:
                raise ValueError("runtime snapshots are immutable")
            return existing.to_domain()
        model = RuntimeConfigSnapshotModel._default_manager.create(
            snapshot_id=snapshot_id,
            profile_id=_uuid(snapshot.profile_id),
            profile_key=snapshot.profile_key,
            profile_version=snapshot.profile_version,
            snapshot_hash=snapshot.snapshot_hash,
            resolved_values=snapshot.resolved_values,
            generated_at=snapshot.generated_at,
            effective_from=snapshot.effective_from,
            validation_report=snapshot.validation_report,
            consumer_acknowledgement=snapshot.consumer_acknowledgement,
        )
        return model.to_domain()

    def get_latest(self, profile_key: str) -> RuntimeConfigSnapshot | None:
        """Return the newest resolved snapshot for a profile key."""

        model = (
            RuntimeConfigSnapshotModel._default_manager.filter(profile_key=profile_key)
            .order_by("-generated_at")
            .first()
        )
        return model.to_domain() if model is not None else None


class RuntimeConfigActivationUnitOfWork:
    """Lock a predecessor and atomically append one runtime successor."""

    def activate(
        self,
        *,
        profile: RuntimeConfigProfile,
        values: tuple[RuntimeConfigValue, ...],
        revision: RuntimeConfigRevision,
        snapshot: RuntimeConfigSnapshot,
        expected_previous_profile: RuntimeConfigProfile | None,
        expected_previous_snapshot: RuntimeConfigSnapshot | None = None,
    ) -> tuple[RuntimeConfigProfile, RuntimeConfigSnapshot]:
        """Persist profile, values, revision and snapshot as one transaction."""

        if profile.status.value != "active":
            raise ValueError("runtime activation requires an active profile")
        if revision.profile_id != profile.profile_id:
            raise ValueError("runtime revision profile_id mismatch")
        if (
            snapshot.profile_id,
            snapshot.profile_key,
            snapshot.profile_version,
        ) != (
            profile.profile_id,
            profile.profile_key,
            profile.version,
        ):
            raise ValueError("runtime snapshot profile identity mismatch")
        if any(value.profile_id != profile.profile_id for value in values):
            raise ValueError("runtime profile value profile_id mismatch")
        if hash_public_runtime_projection(snapshot.resolved_values) != snapshot.snapshot_hash:
            raise ValueError("runtime snapshot public hash mismatch")

        with transaction.atomic():
            _lock_runtime_environment(profile.environment)
            active_models = list(
                RuntimeConfigProfileModel._default_manager.select_for_update()
                .filter(environment=profile.environment, status="active")
                .order_by("-version")
            )
            if len(active_models) > 1:
                raise ValueError("multiple active runtime profiles require reconciliation")
            previous_model = active_models[0] if active_models else None
            previous = previous_model.to_domain() if previous_model is not None else None
            if not _same_predecessor(previous, expected_previous_profile):
                raise ValueError("runtime profile predecessor drifted")
            previous_snapshots = (
                list(
                    RuntimeConfigSnapshotModel._default_manager.select_for_update()
                    .filter(
                        profile_id=_uuid(previous.profile_id),
                        profile_version=previous.version,
                    )
                    .order_by("-generated_at")
                )
                if previous is not None
                else []
            )
            if previous is None:
                if expected_previous_snapshot is not None:
                    raise ValueError("unexpected predecessor snapshot")
            elif len(previous_snapshots) != 1:
                raise ValueError("active runtime profile snapshot is unavailable")
            elif expected_previous_snapshot is not None and not _same_snapshot(
                previous_snapshots[0].to_domain(), expected_previous_snapshot
            ):
                raise ValueError("runtime profile snapshot predecessor drifted")
            if RuntimeConfigProfileModel._default_manager.filter(
                profile_id=_uuid(profile.profile_id)
            ).exists():
                raise ValueError("runtime profiles are immutable")
            if previous is not None:
                if previous_model is None:
                    raise RuntimeError("active runtime profile row disappeared")
                if profile.version != previous.version + 1:
                    raise ValueError("runtime profile successor version must be exact")
                if profile.based_on_profile != previous.profile_id:
                    raise ValueError("runtime profile predecessor does not match active profile")
                previous_model.status = "superseded"
                previous_model.save(update_fields=["status"])
            elif profile.based_on_profile:
                raise ValueError("runtime profile predecessor is unavailable")

            profile_model = RuntimeConfigProfileModel._default_manager.create(
                profile_id=_uuid(profile.profile_id),
                profile_key=profile.profile_key,
                environment=profile.environment,
                version=profile.version,
                status=profile.status.value,
                based_on_profile=profile.based_on_profile,
                content_hash=profile.content_hash,
                created_by=profile.created_by,
                activated_by=profile.activated_by,
                created_at=profile.created_at,
                activated_at=profile.activated_at,
                change_reason=profile.change_reason,
                release_ref=profile.release_ref,
            )
            for value in values:
                RuntimeConfigValueModel._default_manager.create(
                    profile_id=_uuid(value.profile_id),
                    definition_key=value.definition_key,
                    value_json=value.value_json,
                    secret_ref=value.secret_ref,
                    source=value.source,
                    validation_status=value.validation_status,
                    validation_error=value.validation_error,
                )
            RuntimeConfigRevisionModel._default_manager.create(
                revision_id=_uuid(revision.revision_id),
                profile_id=_uuid(revision.profile_id),
                before_hash=revision.before_hash,
                after_hash=revision.after_hash,
                changed_keys=list(revision.changed_keys),
                before_projection=revision.before_projection,
                after_projection=revision.after_projection,
                actor=revision.actor,
                reason=revision.reason,
                changed_at=revision.changed_at,
                release_ref=revision.release_ref,
                validation_evidence=revision.validation_evidence,
            )
            snapshot_model = RuntimeConfigSnapshotModel._default_manager.create(
                snapshot_id=_uuid(snapshot.snapshot_id),
                profile_id=_uuid(snapshot.profile_id),
                profile_key=snapshot.profile_key,
                profile_version=snapshot.profile_version,
                snapshot_hash=snapshot.snapshot_hash,
                resolved_values=snapshot.resolved_values,
                generated_at=snapshot.generated_at,
                effective_from=snapshot.effective_from,
                validation_report=snapshot.validation_report,
                consumer_acknowledgement=snapshot.consumer_acknowledgement,
            )
        return profile_model.to_domain(), snapshot_model.to_domain()


def _same_predecessor(
    actual: RuntimeConfigProfile | None,
    expected: RuntimeConfigProfile | None,
) -> bool:
    """Compare the locked predecessor identity without comparing timestamps."""

    if actual is None or expected is None:
        return actual is None and expected is None
    return (
        actual.profile_id,
        actual.profile_key,
        actual.environment,
        actual.version,
        actual.status,
        actual.content_hash,
    ) == (
        expected.profile_id,
        expected.profile_key,
        expected.environment,
        expected.version,
        expected.status,
        expected.content_hash,
    )


def _same_snapshot(
    actual: RuntimeConfigSnapshot | None,
    expected: RuntimeConfigSnapshot | None,
) -> bool:
    """Compare the approved public snapshot identity and hash."""

    if actual is None or expected is None:
        return actual is None and expected is None
    return (
        actual.snapshot_id,
        actual.profile_id,
        actual.profile_key,
        actual.profile_version,
        actual.snapshot_hash,
        actual.resolved_values,
    ) == (
        expected.snapshot_id,
        expected.profile_id,
        expected.profile_key,
        expected.profile_version,
        expected.snapshot_hash,
        expected.resolved_values,
    )


def _lock_runtime_environment(environment: str) -> None:
    """Serialize bootstrap and successor activation for one environment on PostgreSQL."""

    if connection.vendor != "postgresql":
        return
    digest = hashlib.sha256(environment.encode("utf-8")).digest()
    lock_key = int.from_bytes(digest[:8], byteorder="big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])


class StorageBudgetPolicyRepository:
    """Storage policy repository with an explicit active query."""

    def save(self, policy: StorageBudgetPolicy) -> StorageBudgetPolicy:
        """Upsert one versioned policy and make no implicit active change."""

        model, _ = StorageBudgetPolicyModel._default_manager.update_or_create(
            policy_key=policy.policy_key,
            version=policy.version,
            defaults={
                "configured_capacity_bytes": policy.configured_capacity_bytes,
                "raw_budget_ratio": policy.raw_budget_ratio,
                "quarantine_budget_ratio": policy.quarantine_budget_ratio,
                "database_budget_ratio": policy.database_budget_ratio,
                "logs_budget_ratio": policy.logs_budget_ratio,
                "emergency_reserve_ratio": policy.emergency_reserve_ratio,
                "warning_ratio": policy.warning_ratio,
                "critical_ratio": policy.critical_ratio,
                "active": policy.active,
            },
        )
        return model.to_domain()

    @transaction.atomic
    def activate(self, policy: StorageBudgetPolicy) -> StorageBudgetPolicy:
        """Activate one policy version and retire all other active versions."""

        StorageBudgetPolicyModel._default_manager.filter(active=True).update(active=False)
        return self.save(replace(policy, active=True))

    def get_active(self) -> StorageBudgetPolicy | None:
        """Return the active policy or ``None`` without a fallback."""

        model = (
            StorageBudgetPolicyModel._default_manager.filter(active=True)
            .order_by("-version")
            .first()
        )
        return model.to_domain() if model is not None else None


__all__ = [
    "RuntimeConfigActivationUnitOfWork",
    "RuntimeConfigDefinitionRepository",
    "RuntimeConfigProfileRepository",
    "RuntimeConfigRevisionRepository",
    "RuntimeConfigSnapshotRepository",
    "RuntimeConfigValueRepository",
    "StorageBudgetPolicyRepository",
]
