"""Application use cases for synchronizing the versioned Data Center catalog."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    ProviderBinding,
    PublicationPolicy,
)
from apps.data_center.domain.protocols import (
    DataOwnerRegistryRepositoryProtocol,
    DatasetContractRepositoryProtocol,
    ProviderBindingRepositoryProtocol,
    PublicationPolicyRepositoryProtocol,
)


@dataclass(frozen=True)
class CatalogSynchronizationResult:
    """Counts emitted by an idempotent catalog synchronization."""

    contracts: int
    bindings: int
    policies: int
    owners: int


class SynchronizeDataCenterCatalogUseCase:
    """Persist validated contract projections without reading ORM models."""

    def __init__(
        self,
        *,
        contracts: DatasetContractRepositoryProtocol,
        bindings: ProviderBindingRepositoryProtocol,
        policies: PublicationPolicyRepositoryProtocol,
        owners: DataOwnerRegistryRepositoryProtocol,
    ) -> None:
        self._contracts = contracts
        self._bindings = bindings
        self._policies = policies
        self._owners = owners

    def execute(
        self,
        *,
        contracts: Iterable[DatasetContract],
        bindings: Iterable[ProviderBinding],
        policies: Iterable[PublicationPolicy],
        owners: Iterable[DataOwnerRegistration],
    ) -> CatalogSynchronizationResult:
        """Synchronize all catalog rows and return deterministic row counts."""

        contract_rows = list(contracts)
        binding_rows = list(bindings)
        policy_rows = list(policies)
        owner_rows = list(owners)
        if not contract_rows:
            raise ValueError("at least one Dataset Contract is required")
        contract_keys = {contract.key.value for contract in contract_rows}
        if {binding.dataset.value for binding in binding_rows} - contract_keys:
            raise ValueError("provider binding references an unknown Dataset Contract")
        if {policy.dataset.value for policy in policy_rows} - contract_keys:
            raise ValueError("publication policy references an unknown Dataset Contract")
        if {owner.dataset_key for owner in owner_rows} - contract_keys:
            raise ValueError("owner registration references an unknown Dataset Contract")

        for contract in contract_rows:
            self._contracts.save(contract)
        self._bindings.synchronize(binding_rows)
        for policy in policy_rows:
            self._policies.save(policy)
        self._owners.synchronize(owner_rows)
        return CatalogSynchronizationResult(
            contracts=len(contract_rows),
            bindings=len(binding_rows),
            policies=len(policy_rows),
            owners=len(owner_rows),
        )


__all__ = ["CatalogSynchronizationResult", "SynchronizeDataCenterCatalogUseCase"]
