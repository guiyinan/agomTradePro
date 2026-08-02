"""ORM repositories for the versioned runtime configuration control plane."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from django.db import transaction

from apps.config_center.domain.runtime_config import (
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigRevision,
    RuntimeConfigSnapshot,
    RuntimeConfigValue,
    StorageBudgetPolicy,
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
        """Upsert a profile by UUID."""

        with transaction.atomic():
            if profile.status.value == "active":
                RuntimeConfigProfileModel._default_manager.filter(
                    environment=profile.environment,
                    status="active",
                ).exclude(profile_id=_uuid(profile.profile_id)).update(status="superseded")
            model, _ = RuntimeConfigProfileModel._default_manager.update_or_create(
                profile_id=_uuid(profile.profile_id),
                defaults={
                    "profile_key": profile.profile_key,
                    "environment": profile.environment,
                    "version": profile.version,
                    "status": profile.status.value,
                    "based_on_profile": profile.based_on_profile,
                    "content_hash": profile.content_hash,
                    "created_by": profile.created_by,
                    "activated_by": profile.activated_by,
                    "created_at": profile.created_at,
                    "activated_at": profile.activated_at,
                    "change_reason": profile.change_reason,
                    "release_ref": profile.release_ref,
                },
            )
        return model.to_domain()

    def get(self, profile_id: str) -> RuntimeConfigProfile | None:
        """Return a profile by UUID."""

        model = RuntimeConfigProfileModel._default_manager.filter(profile_id=_uuid(profile_id)).first()
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
        """Upsert one value in a profile."""

        model, _ = RuntimeConfigValueModel._default_manager.update_or_create(
            profile_id=_uuid(value.profile_id),
            definition_key=value.definition_key,
            defaults={
                "value_json": value.value_json,
                "secret_ref": value.secret_ref,
                "source": value.source,
                "validation_status": value.validation_status,
                "validation_error": value.validation_error,
            },
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
        """Insert a snapshot, allowing the same hash to be retried idempotently."""

        model, _ = RuntimeConfigSnapshotModel._default_manager.update_or_create(
            snapshot_id=_uuid(snapshot.snapshot_id),
            defaults={
                "profile_id": _uuid(snapshot.profile_id),
                "profile_key": snapshot.profile_key,
                "profile_version": snapshot.profile_version,
                "snapshot_hash": snapshot.snapshot_hash,
                "resolved_values": snapshot.resolved_values,
                "generated_at": snapshot.generated_at,
                "effective_from": snapshot.effective_from,
                "validation_report": snapshot.validation_report,
                "consumer_acknowledgement": snapshot.consumer_acknowledgement,
            },
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

        model = StorageBudgetPolicyModel._default_manager.filter(active=True).order_by("-version").first()
        return model.to_domain() if model is not None else None


__all__ = [
    "RuntimeConfigDefinitionRepository",
    "RuntimeConfigProfileRepository",
    "RuntimeConfigRevisionRepository",
    "RuntimeConfigSnapshotRepository",
    "RuntimeConfigValueRepository",
    "StorageBudgetPolicyRepository",
]
