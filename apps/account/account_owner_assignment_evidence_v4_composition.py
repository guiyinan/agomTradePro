"""Same-alias composition for explicit Account owner-assignment Evidence v4.

This module is the authenticated application boundary for the inactive v4
evidence flow.  It closes the policy and actor selectors when the facade is
constructed, and accepts only the ID/hash-only commands exposed by the
Application layer.  The facade never derives or changes Account identity,
policy, role, session, or execution authority.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TypeVar

from django.db import DatabaseError, connections, transaction
from django.utils.connection import ConnectionDoesNotExist

from apps.account.account_owner_assignment_evidence_v3_composition import (
    AccountExactCanonicalAccountCreationBindingV2Provider,
    AccountExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
)
from apps.account.application.account_actor_authority_request_reader import (
    CanonicalAccountActorAuthorityRequestReader,
)
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4Repository,
    ApproveAccountOwnerAssignmentEvidenceV4,
    ApproveAccountOwnerAssignmentEvidenceV4Command,
    ExactCurrentAccountOwnerAssignmentProvenanceReceiptV4Provider,
    GetCurrentAccountOwnerAssignmentEvidenceV4,
    GetCurrentAccountOwnerAssignmentEvidenceV4Command,
    RegisterAccountOwnerAssignmentSubjectV4,
    RegisterAccountOwnerAssignmentSubjectV4Command,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v4 import (
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV4,
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV4Command,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipantsProvider,
    SingleOwnerPolicyBinding,
)
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4,
    AccountOwnerAssignmentSubjectV4,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v4 import (
    AccountOwnerAssignmentProvenanceReceiptV4,
)
from apps.account.infrastructure.account_actor_authority_capture_snapshot import (
    DjangoAccountActorAuthorityCaptureBundleProviderV3,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_repository import (
    DjangoAccountOwnerAssignmentEvidenceV4Repository,
    lock_account_owner_assignment_evidence_v4_sources,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_repository import (
    DjangoAllocatedPhysicalAccountRowObservationV3Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)

_ReturnT = TypeVar("_ReturnT")


class _CurrentReceiptV4Provider:
    """Adapt the public Receipt v4 current use case to the Evidence port."""

    def __init__(self, reader: GetCurrentAccountOwnerAssignmentProvenanceReceiptV4) -> None:
        """Bind the exact-current Receipt reader without exposing its repository."""

        self._reader = reader

    def get_exact_current(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountOwnerAssignmentProvenanceReceiptV4 | None:
        """Read the selected Receipt v4 through its public Application contract."""

        return self._reader.execute(
            GetCurrentAccountOwnerAssignmentProvenanceReceiptV4Command(
                receipt_id=receipt_id,
                receipt_version=receipt_version,
                expected_content_hash=expected_content_hash,
                as_of=as_of,
            )
        )


class AccountOwnerAssignmentEvidenceV4Facade:
    """Expose authenticated, same-alias Subject/Evidence v4 operations.

    ``policy_binding`` and the actor selector are closed by the factory.  A
    caller can therefore supply only the immutable ID/hash selectors carried
    by each Application command; it cannot select a different owner, role,
    policy, authentication source, or validity clock at operation time.
    """

    def __init__(
        self,
        *,
        using: str,
        policy_id: str,
        actors: DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
        register: RegisterAccountOwnerAssignmentSubjectV4,
        approve: ApproveAccountOwnerAssignmentEvidenceV4,
        current: GetCurrentAccountOwnerAssignmentEvidenceV4,
    ) -> None:
        """Bind one database alias and the server-owned Application use cases."""

        self._using = using
        self._policy_id = policy_id
        self._actors = actors
        self._register = register
        self._approve = approve
        self._current = current

    def register(
        self, command: RegisterAccountOwnerAssignmentSubjectV4Command
    ) -> AccountOwnerAssignmentSubjectV4:
        """Register or replay one Subject after locking every source ledger."""

        if type(command) is not RegisterAccountOwnerAssignmentSubjectV4Command:
            raise TypeError("command must be an exact Subject v4 register command")
        command.__post_init__()
        return self._locked(lambda: self._register.execute(command))

    def approve(
        self, command: ApproveAccountOwnerAssignmentEvidenceV4Command
    ) -> AccountOwnerAssignmentEvidenceV4:
        """Explicitly approve or replay inactive Evidence v4 under current facts."""

        if type(command) is not ApproveAccountOwnerAssignmentEvidenceV4Command:
            raise TypeError("command must be an exact Evidence v4 approve command")
        command.__post_init__()
        return self._locked(lambda: self._approve.execute(command))

    def get_current(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV4Command
    ) -> AccountOwnerAssignmentEvidenceV4 | None:
        """Read current Evidence while retaining the actor capture UOW."""

        if type(command) is not GetCurrentAccountOwnerAssignmentEvidenceV4Command:
            raise TypeError("command must be an exact Evidence v4 current command")
        command.__post_init__()
        return self._locked(lambda: self._current.execute(command))

    def _locked(self, operation: Callable[[], _ReturnT]) -> _ReturnT:
        """Run one operation after source locking and inside the actor UOW."""

        self._ensure_postgresql()
        try:
            with transaction.atomic(using=self._using):
                lock_account_owner_assignment_evidence_v4_sources(
                    using=self._using,
                    policy_id=self._policy_id,
                )
                with self._actors.atomic():
                    return operation()
        except DatabaseError as error:
            raise AccountOwnerAssignmentUnavailable(
                "Evidence v4 write transaction is unavailable"
            ) from error

    def _ensure_postgresql(self) -> None:
        """Reject missing or non-PostgreSQL aliases before opening a UOW."""

        try:
            connection = connections[self._using]
        except (ConnectionDoesNotExist, KeyError) as error:
            raise AccountOwnerAssignmentUnavailable(
                "Evidence v4 database alias is unavailable"
            ) from error
        if connection.vendor != "postgresql":
            raise AccountOwnerAssignmentUnavailable("Evidence v4 composition requires PostgreSQL")


def build_account_owner_assignment_evidence_v4_facade(
    *,
    principal: AuthenticatedAccountPrincipalV3,
    policy_binding: SingleOwnerPolicyBinding,
    actor_source_id: str,
    actor_source_version: str,
    actor_source_content_hash: str,
    validity_period: timedelta,
    using: str = "default",
) -> AccountOwnerAssignmentEvidenceV4Facade:
    """Build the server-owned authenticated Evidence v4 facade.

    The principal, policy binding, actor selector, and validity period are
    composition inputs owned by the authenticated server boundary.  Commands
    passed to the returned facade contain only exact IDs and content hashes.
    All concrete repositories use ``using`` and the actor reader shares the
    actor repository UOW required by the capture-specific source provider.
    """

    if type(using) is not str or not using or using.strip() != using:
        raise ValueError("using must be an exact database alias")

    actors = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(using=using)
    actor_reader = CanonicalAccountActorAuthorityRequestReader(
        current_reader=GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3(
            input_bundle_provider=DjangoAccountActorAuthorityCaptureBundleProviderV3(
                using=using,
                require_capture_transaction=actors.require_capture_transaction,
            ),
            repository=actors,
        ),
        source_id=actor_source_id,
        source_version=actor_source_version,
        expected_content_hash=actor_source_content_hash,
    )
    participants = CurrentSingleOwnerParticipantsProvider(
        principal=principal,
        binding=policy_binding,
        policies=DjangoSingleOwnerAuthorityPolicyV1Repository(using=using),
        actors=actor_reader,
    )

    binding_provider = AccountExactCanonicalAccountCreationBindingV2Provider(
        DjangoCanonicalAccountCreationConsumptionRepository(using=using)
    )
    physical_provider = AccountExactCurrentAllocatedPhysicalAccountRowObservationV3Provider(
        DjangoAllocatedPhysicalAccountRowObservationV3Repository(using=using)
    )
    receipt_reader = GetCurrentAccountOwnerAssignmentProvenanceReceiptV4(
        repository=DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository(using=using),
        binding_provider=binding_provider,
        root_provider=physical_provider,
        participants_reader=participants,
    )
    receipt_provider: ExactCurrentAccountOwnerAssignmentProvenanceReceiptV4Provider = (
        _CurrentReceiptV4Provider(receipt_reader)
    )
    evidence_repository: AccountOwnerAssignmentEvidenceV4Repository = (
        DjangoAccountOwnerAssignmentEvidenceV4Repository(using=using)
    )
    return AccountOwnerAssignmentEvidenceV4Facade(
        using=using,
        policy_id=policy_binding.policy_id,
        actors=actors,
        register=RegisterAccountOwnerAssignmentSubjectV4(
            receipt_provider=receipt_provider,
            root_provider=physical_provider,
            repository=evidence_repository,
        ),
        approve=ApproveAccountOwnerAssignmentEvidenceV4(
            receipt_provider=receipt_provider,
            root_provider=physical_provider,
            participants_reader=participants,
            repository=evidence_repository,
            validity_period=validity_period,
        ),
        current=GetCurrentAccountOwnerAssignmentEvidenceV4(
            receipt_provider=receipt_provider,
            root_provider=physical_provider,
            participants_reader=participants,
            repository=evidence_repository,
        ),
    )


__all__ = [
    "AccountOwnerAssignmentEvidenceV4Facade",
    "build_account_owner_assignment_evidence_v4_facade",
]
