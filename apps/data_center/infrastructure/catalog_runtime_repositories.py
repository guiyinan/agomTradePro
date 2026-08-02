"""ORM repositories for versioned Dataset Catalog runtime truth."""

from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction

from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    ProviderBinding,
    PublicationPolicy,
)

from .catalog_models import (
    DataOwnerRegistrationModel,
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)


class DatasetContractRepository:
    """Read/write repository for active Dataset Contract versions."""

    def list_active(self) -> list[DatasetContract]:
        """Return the active version for each dataset in stable order."""

        rows = DatasetContractModel._default_manager.filter(active=True).order_by(
            "dataset_key", "-updated_at", "-id"
        )
        seen: set[str] = set()
        contracts: list[DatasetContract] = []
        for row in rows:
            if row.dataset_key in seen:
                continue
            seen.add(row.dataset_key)
            contracts.append(row.to_domain())
        return contracts

    def get_active(self, dataset_key: str) -> DatasetContract | None:
        """Return the newest active contract for one dataset."""

        row = (
            DatasetContractModel._default_manager.filter(
                dataset_key=dataset_key.strip(), active=True
            )
            .order_by("-updated_at", "-id")
            .first()
        )
        return row.to_domain() if row is not None else None

    def save(self, contract: DatasetContract) -> DatasetContract:
        """Upsert a contract and supersede older versions for its dataset."""

        with transaction.atomic():
            DatasetContractModel._default_manager.filter(
                dataset_key=contract.key.value,
                active=True,
            ).exclude(
                contract_version=contract.key.contract_version,
                schema_version=contract.key.schema_version,
            ).update(
                active=False
            )
            row, _created = DatasetContractModel._default_manager.update_or_create(
                dataset_key=contract.key.value,
                contract_version=contract.key.contract_version,
                schema_version=contract.key.schema_version,
                defaults={
                    "owner": contract.owner,
                    "frequency": contract.frequency,
                    "decision_critical": contract.decision_critical,
                    "fields": [
                        {
                            "name": field.name,
                            "type": field.value_type,
                            "unit": field.unit,
                            "nullable": field.nullable,
                            "zero_allowed": field.zero_allowed,
                            "minimum": field.minimum,
                            "maximum": field.maximum,
                        }
                        for field in contract.fields
                    ],
                    "freshness_seconds": contract.freshness_seconds,
                    "comparable_group": contract.comparable_group or "",
                    "active": True,
                },
            )
        return row.to_domain()


class ProviderBindingRepository:
    """Repository for active provider bindings."""

    def list_active(self, dataset_key: str | None = None) -> list[ProviderBinding]:
        """Return active bindings ordered by dataset and failover priority."""

        queryset = DatasetProviderBindingModel._default_manager.filter(enabled=True)
        if dataset_key is not None:
            queryset = queryset.filter(dataset_key=dataset_key.strip())
        return [row.to_domain() for row in queryset.order_by("dataset_key", "priority", "provider")]

    def save(self, binding: ProviderBinding) -> ProviderBinding:
        """Upsert one versioned provider binding."""

        row, _created = DatasetProviderBindingModel._default_manager.update_or_create(
            dataset_key=binding.dataset.value,
            contract_version=binding.dataset.contract_version,
            schema_version=binding.dataset.schema_version,
            provider=binding.provider,
            capability=binding.capability,
            defaults={
                "priority": binding.priority,
                "freshness_seconds": binding.freshness_seconds,
                "validator_key": binding.validator_key,
                "enabled": binding.enabled,
            },
        )
        return row.to_domain()

    def synchronize(self, bindings: Iterable[ProviderBinding]) -> int:
        """Replace active bindings atomically while retaining audit history."""

        entries = list(bindings)
        with transaction.atomic():
            DatasetProviderBindingModel._default_manager.filter(enabled=True).update(enabled=False)
            for binding in entries:
                self.save(binding)
        return len(entries)


class PublicationPolicyRepository:
    """Repository for active dataset publication policies."""

    def list_active(self, dataset_key: str | None = None) -> list[PublicationPolicy]:
        """Return active policies in deterministic dataset order."""

        queryset = DatasetPublicationPolicyModel._default_manager.filter(active=True)
        if dataset_key is not None:
            queryset = queryset.filter(dataset_key=dataset_key.strip())
        return [row.to_domain() for row in queryset.order_by("dataset_key", "-updated_at", "-id")]

    def get_active(self, dataset_key: str) -> PublicationPolicy | None:
        """Return the newest active policy for one dataset."""

        row = (
            DatasetPublicationPolicyModel._default_manager.filter(
                dataset_key=dataset_key.strip(), active=True
            )
            .order_by("-updated_at", "-id")
            .first()
        )
        return row.to_domain() if row is not None else None

    def save(self, policy: PublicationPolicy) -> PublicationPolicy:
        """Upsert a policy and supersede older versions for its dataset."""

        with transaction.atomic():
            DatasetPublicationPolicyModel._default_manager.filter(
                dataset_key=policy.dataset.value,
                active=True,
            ).exclude(
                contract_version=policy.dataset.contract_version,
                schema_version=policy.dataset.schema_version,
            ).update(
                active=False
            )
            row, _created = DatasetPublicationPolicyModel._default_manager.update_or_create(
                dataset_key=policy.dataset.value,
                contract_version=policy.dataset.contract_version,
                schema_version=policy.dataset.schema_version,
                defaults={
                    "minimum_coverage_ratio": policy.minimum_coverage_ratio,
                    "allow_partial": policy.allow_partial,
                    "conflict_action": policy.conflict_action,
                    "required_evidence": list(policy.required_evidence),
                    "retention_days": policy.retention_days,
                    "active": True,
                },
            )
        return row.to_domain()


class DataOwnerRegistryRepository:
    """Repository for dataset ownership and acceptance registrations."""

    def list_active(self) -> list[DataOwnerRegistration]:
        """Return active ownership registrations in dataset order."""

        rows = DataOwnerRegistrationModel._default_manager.filter(active=True).order_by(
            "dataset_key"
        )
        return [row.to_domain() for row in rows]

    def save(self, registration: DataOwnerRegistration) -> DataOwnerRegistration:
        """Upsert one ownership registration."""

        row, _created = DataOwnerRegistrationModel._default_manager.update_or_create(
            dataset_key=registration.dataset_key,
            defaults={
                "data_platform_owner": registration.data_platform_owner,
                "business_owner": registration.business_owner,
                "acceptance_owner": registration.acceptance_owner,
                "active": registration.active,
            },
        )
        return row.to_domain()

    def synchronize(self, registrations: Iterable[DataOwnerRegistration]) -> int:
        """Replace active registrations atomically while retaining old rows."""

        entries = list(registrations)
        with transaction.atomic():
            DataOwnerRegistrationModel._default_manager.filter(active=True).update(active=False)
            for registration in entries:
                self.save(registration)
        return len(entries)


__all__ = [
    "DataOwnerRegistryRepository",
    "DatasetContractRepository",
    "ProviderBindingRepository",
    "PublicationPolicyRepository",
]
