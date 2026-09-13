"""Immutable policy versions and a single active publication gate per dataset."""

from __future__ import annotations

from django.db import transaction

from apps.data_center.domain.contracts import PublicationPolicy

from .catalog_models import DatasetPublicationPolicyModel


class PublicationPolicyRepository:
    """Persist immutable decision content separately from activation state."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the transaction identity used by this repository."""

        return "django:default"

    def list_active(self, dataset_key: str | None = None) -> list[PublicationPolicy]:
        """Return one active policy per dataset, rejecting ambiguous state."""

        rows = DatasetPublicationPolicyModel._default_manager.filter(active=True)
        if dataset_key is not None:
            rows = rows.filter(dataset_key=dataset_key.strip())
        policies = [row.to_domain() for row in rows.order_by("dataset_key", "-updated_at", "-id")]
        keys = [policy.dataset.value for policy in policies]
        if len(set(keys)) != len(keys):
            raise ValueError("Multiple active publication policies are ambiguous")
        return policies

    def get_active(self, dataset_key: str) -> PublicationPolicy | None:
        """Read the unique active policy without silently choosing between versions."""

        policies = self.list_active(dataset_key)
        return policies[0] if policies else None

    def get_locked_active(self, dataset_key: str) -> PublicationPolicy | None:
        """Lock the active decision policy until the surrounding publication commits."""

        rows = list(
            DatasetPublicationPolicyModel._default_manager.select_for_update()
            .filter(dataset_key=dataset_key.strip(), active=True)
            .order_by("id")
        )
        if len(rows) > 1:
            raise ValueError("Multiple active publication policies are ambiguous")
        return rows[0].to_domain() if rows else None

    def save(self, policy: PublicationPolicy) -> PublicationPolicy:
        """Activate exact content, rejecting any rewrite of an existing version."""

        with transaction.atomic():
            manager = DatasetPublicationPolicyModel._default_manager
            # Existing version locks serialize reactivation and protect its content.
            existing = (
                manager.select_for_update()
                .filter(
                    dataset_key=policy.dataset.value,
                    contract_version=policy.dataset.contract_version,
                    schema_version=policy.dataset.schema_version,
                    policy_version=policy.policy_version,
                )
                .first()
            )
            if existing is not None and existing.to_domain() != policy:
                raise ValueError("Publication policy version content is immutable")
            manager.filter(dataset_key=policy.dataset.value, active=True).update(active=False)
            row, created = manager.get_or_create(
                dataset_key=policy.dataset.value,
                contract_version=policy.dataset.contract_version,
                schema_version=policy.dataset.schema_version,
                policy_version=policy.policy_version,
                defaults={
                    "minimum_coverage_ratio": policy.minimum_coverage_ratio,
                    "allow_partial": policy.allow_partial,
                    "conflict_action": policy.conflict_action,
                    "required_evidence": list(policy.required_evidence),
                    "retention_days": policy.retention_days,
                    "active": True,
                },
            )
            # get_or_create may observe a concurrent creator of the same version.
            if row.to_domain() != policy:
                raise ValueError("Publication policy version content is immutable")
            if not created:
                row.active = True
                row.save(update_fields=["active", "updated_at"])
        return row.to_domain()
