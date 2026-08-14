"""Account-owned read composition for current owner-assignment evidence v3."""

from __future__ import annotations

from datetime import datetime

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_evidence_v3 import (
    GetCurrentAccountOwnerAssignmentEvidenceV3,
)
from apps.account.application.account_owner_assignment_mapping_v3 import (
    GetCurrentAuthoritativeAccountMappingV3,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v3 import (
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV3,
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV3Command,
)
from apps.account.application.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3Conflict,
    AllocatedPhysicalAccountRowObservationV3Corruption,
    AllocatedPhysicalAccountRowObservationV3Unavailable,
    GetCurrentAllocatedPhysicalAccountRowObservationV3,
    GetCurrentAllocatedPhysicalAccountRowObservationV3Command,
    GetExactAllocatedPhysicalAccountRowObservationV3,
    GetExactAllocatedPhysicalAccountRowObservationV3Command,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2Conflict,
    CanonicalAccountCreationBindingV2Corruption,
    CanonicalAccountCreationBindingV2Unavailable,
    GetExactCanonicalAccountCreationBindingV2,
    GetExactCanonicalAccountCreationBindingV2Command,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v3 import (
    AccountOwnerAssignmentProvenanceReceiptV3,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v3_repository import (
    DjangoAccountOwnerAssignmentEvidenceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v3_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_repository import (
    DjangoAllocatedPhysicalAccountRowObservationV3Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)


class AccountExactCanonicalAccountCreationBindingV2Provider:
    """Expose the durable Binding-v2 reader with Account assignment taxonomy."""

    def __init__(self, repository: DjangoCanonicalAccountCreationConsumptionRepository) -> None:
        self._reader = GetExactCanonicalAccountCreationBindingV2(repository)

    def get_exact(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationBindingV2 | None:
        """Read one exact durable binding without any current fallback."""

        try:
            return self._reader.execute(
                GetExactCanonicalAccountCreationBindingV2Command(
                    binding_id, binding_version, expected_content_hash, as_of
                )
            )
        except CanonicalAccountCreationBindingV2Unavailable as error:
            raise AccountOwnerAssignmentUnavailable(str(error)) from error
        except CanonicalAccountCreationBindingV2Conflict as error:
            raise AccountOwnerAssignmentCorruption(str(error)) from error
        except CanonicalAccountCreationBindingV2Corruption as error:
            raise AccountOwnerAssignmentCorruption(str(error)) from error


class AccountExactCurrentAllocatedPhysicalAccountRowObservationV3Provider:
    """Adapt the Account Physical-v3 ledger to exact and exact-current reads."""

    def __init__(
        self, repository: DjangoAllocatedPhysicalAccountRowObservationV3Repository
    ) -> None:
        self._exact = GetExactAllocatedPhysicalAccountRowObservationV3(repository)
        self._current = GetCurrentAllocatedPhysicalAccountRowObservationV3(repository)

    def get_exact(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AllocatedPhysicalAccountRowObservationV3 | None:
        """Read one immutable Physical-v3 root by its closed selector."""

        try:
            return self._exact.execute(
                GetExactAllocatedPhysicalAccountRowObservationV3Command(
                    observation_id, observation_version, expected_content_hash, as_of
                )
            )
        except AllocatedPhysicalAccountRowObservationV3Unavailable as error:
            raise AccountOwnerAssignmentUnavailable(str(error)) from error
        except AllocatedPhysicalAccountRowObservationV3Conflict as error:
            raise AccountOwnerAssignmentCorruption(str(error)) from error
        except AllocatedPhysicalAccountRowObservationV3Corruption as error:
            raise AccountOwnerAssignmentCorruption(str(error)) from error

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AllocatedPhysicalAccountRowObservationV3 | None:
        """Delegate the scalar selector to the server-owned closed-current reader."""

        try:
            return self._current.execute(
                GetCurrentAllocatedPhysicalAccountRowObservationV3Command(
                    observation_id,
                    observation_version,
                    expected_content_hash,
                    as_of,
                )
            )
        except AllocatedPhysicalAccountRowObservationV3Unavailable as error:
            raise AccountOwnerAssignmentUnavailable(str(error)) from error
        except AllocatedPhysicalAccountRowObservationV3Conflict as error:
            raise AccountOwnerAssignmentCorruption(str(error)) from error
        except AllocatedPhysicalAccountRowObservationV3Corruption as error:
            raise AccountOwnerAssignmentCorruption(str(error)) from error


class AccountExactCurrentAccountOwnerAssignmentProvenanceReceiptV3Provider:
    """Adapt Receipt-v3 exact/current use cases to the hash-only evidence port."""

    def __init__(
        self,
        *,
        repository: DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository,
        binding_provider: AccountExactCanonicalAccountCreationBindingV2Provider,
        root_provider: AccountExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
    ) -> None:
        self._current = GetCurrentAccountOwnerAssignmentProvenanceReceiptV3(
            repository=repository,
            binding_provider=binding_provider,
            root_provider=root_provider,
        )

    def get_exact_current(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentProvenanceReceiptV3 | None:
        """Delegate the scalar selector to the server-owned closed-current reader."""

        return self._current.execute(
            GetCurrentAccountOwnerAssignmentProvenanceReceiptV3Command(
                receipt_id,
                receipt_version,
                expected_content_hash,
                as_of,
            )
        )


def build_current_account_owner_assignment_evidence_v3(
    *, using: str = "default"
) -> GetCurrentAccountOwnerAssignmentEvidenceV3:
    """Build the Account-only closed-current Evidence-v3 reader."""

    binding = AccountExactCanonicalAccountCreationBindingV2Provider(
        DjangoCanonicalAccountCreationConsumptionRepository(using=using)
    )
    physical = AccountExactCurrentAllocatedPhysicalAccountRowObservationV3Provider(
        DjangoAllocatedPhysicalAccountRowObservationV3Repository(using=using)
    )
    receipt = AccountExactCurrentAccountOwnerAssignmentProvenanceReceiptV3Provider(
        repository=DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository(using=using),
        binding_provider=binding,
        root_provider=physical,
    )
    return GetCurrentAccountOwnerAssignmentEvidenceV3(
        receipt_provider=receipt,
        root_provider=physical,
        repository=DjangoAccountOwnerAssignmentEvidenceV3Repository(using=using),
    )


def build_current_authoritative_account_mapping_v3(
    *, using: str = "default"
) -> GetCurrentAuthoritativeAccountMappingV3:
    """Build the read-only authoritative mapping facade without writer capabilities."""

    evidence_repository = DjangoAccountOwnerAssignmentEvidenceV3Repository(using=using)
    binding = AccountExactCanonicalAccountCreationBindingV2Provider(
        DjangoCanonicalAccountCreationConsumptionRepository(using=using)
    )
    physical = AccountExactCurrentAllocatedPhysicalAccountRowObservationV3Provider(
        DjangoAllocatedPhysicalAccountRowObservationV3Repository(using=using)
    )
    receipt = AccountExactCurrentAccountOwnerAssignmentProvenanceReceiptV3Provider(
        repository=DjangoAccountOwnerAssignmentProvenanceReceiptV3Repository(using=using),
        binding_provider=binding,
        root_provider=physical,
    )
    current = GetCurrentAccountOwnerAssignmentEvidenceV3(
        receipt_provider=receipt,
        root_provider=physical,
        repository=evidence_repository,
    )
    return GetCurrentAuthoritativeAccountMappingV3(
        head_reader=evidence_repository, current_reader=current
    )


__all__ = [
    "AccountExactCanonicalAccountCreationBindingV2Provider",
    "AccountExactCurrentAccountOwnerAssignmentProvenanceReceiptV3Provider",
    "AccountExactCurrentAllocatedPhysicalAccountRowObservationV3Provider",
    "build_current_account_owner_assignment_evidence_v3",
    "build_current_authoritative_account_mapping_v3",
]
