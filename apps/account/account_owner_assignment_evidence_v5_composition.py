"""Same-alias composition for authenticated, inactive Account Evidence V5.

The composition root closes the authenticated principal, single-owner policy,
actor-source selector, database alias, and validity period.  The returned
facade accepts only the ID/hash selectors defined by the Application layer.
Evidence V5 remains an inactive evidence artifact and this module does not
authenticate requests, register an owner, or grant execution authority.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import TypeVar

from django.db import DatabaseError, connections, transaction
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.account_actor_authority_request_reader import (
    CanonicalAccountActorAuthorityRequestReader,
)
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5Unavailable,
    ApproveAccountOwnerAssignmentEvidenceV5,
    ApproveAccountOwnerAssignmentEvidenceV5Command,
    GetCurrentAccountOwnerAssignmentEvidenceV5,
    GetCurrentAccountOwnerAssignmentEvidenceV5Command,
    GetExactAccountOwnerAssignmentEvidenceV5,
    GetExactAccountOwnerAssignmentEvidenceV5Command,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v5 import (
    GetCurrentAccountOwnerAssignmentProvenanceReceiptV5,
)
from apps.account.application.account_owner_assignment_subject_v5 import (
    GetCurrentAccountOwnerAssignmentSubjectV5,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    GetExactCanonicalAccountCreationBindingV2,
)
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    GetCurrentCanonicalAccountOwnershipReobservationV1,
)
from apps.account.application.physical_account_row_observation_v2 import (
    ExactPhysicalSimulatedAccountRowV2Provider,
    GetCurrentPhysicalAccountRowObservationV2,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipantsProvider,
    SingleOwnerPolicyBinding,
)
from apps.account.domain.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5,
)
from apps.account.infrastructure.account_actor_authority_capture_snapshot import (
    DjangoAccountActorAuthorityCaptureBundleProviderV3,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_repository import (
    DjangoAccountOwnerAssignmentEvidenceV5Repository,
    lock_account_owner_assignment_evidence_v5_sources,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_repository import (
    DjangoAccountOwnerAssignmentSubjectV5Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_repository import (
    DjangoCanonicalAccountOwnershipReobservationV1Repository,
)
from apps.account.infrastructure.physical_account_row_observation_v2_repository import (
    DjangoPhysicalAccountRowObservationV2Repository,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)

_ReturnT = TypeVar("_ReturnT")


class AccountOwnerAssignmentEvidenceV5Facade:
    """Expose authenticated, same-alias Evidence V5 operations.

    The authenticated principal, policy binding, actor-source selector, alias,
    and validity period are fixed by the composition root.  Commands passed to
    this facade contain only immutable ID/hash selectors.  Approval and current
    reads acquire the complete V5 source lock before opening the actor capture
    unit of work; the approval Application use case then owns the Evidence V5
    private UOW.
    """

    def __init__(
        self,
        *,
        using: str,
        policy_id: str,
        actors: DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
        approve: ApproveAccountOwnerAssignmentEvidenceV5,
        exact: GetExactAccountOwnerAssignmentEvidenceV5,
        current: GetCurrentAccountOwnerAssignmentEvidenceV5,
    ) -> None:
        """Bind one alias and the server-owned V5 Application use cases."""

        self._using = using
        self._policy_id = policy_id
        self._actors = actors
        self._approve = approve
        self._exact = exact
        self._current = current

    def approve(
        self, command: ApproveAccountOwnerAssignmentEvidenceV5Command
    ) -> AccountOwnerAssignmentEvidenceV5:
        """Approve or replay one inactive Evidence V5 root under current facts."""

        if type(command) is not ApproveAccountOwnerAssignmentEvidenceV5Command:
            raise TypeError("command must be an exact Evidence V5 approve command")
        command.__post_init__()
        return self._locked(lambda: self._approve.execute(command))

    def get_exact(
        self, command: GetExactAccountOwnerAssignmentEvidenceV5Command
    ) -> AccountOwnerAssignmentEvidenceV5 | None:
        """Read immutable historical Evidence V5 without current authority checks."""

        if type(command) is not GetExactAccountOwnerAssignmentEvidenceV5Command:
            raise TypeError("command must be an exact Evidence V5 exact command")
        command.__post_init__()
        return self._exact.execute(command)

    def get_current(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV5Command
    ) -> AccountOwnerAssignmentEvidenceV5 | None:
        """Read Evidence V5 only while Subject, authority, and both heads agree."""

        if type(command) is not GetCurrentAccountOwnerAssignmentEvidenceV5Command:
            raise TypeError("command must be an exact Evidence V5 current command")
        command.__post_init__()
        return self._locked(lambda: self._current.execute(command))

    def _locked(self, operation: Callable[[], _ReturnT]) -> _ReturnT:
        """Run one current operation under ordered source locks and actor UOW."""

        self._ensure_postgresql()
        try:
            with transaction.atomic(using=self._using):
                lock_account_owner_assignment_evidence_v5_sources(
                    using=self._using,
                    policy_id=self._policy_id,
                )
                with self._actors.atomic():
                    return operation()
        except DatabaseError as error:
            raise AccountOwnerAssignmentEvidenceV5Unavailable(
                "Evidence V5 write transaction is unavailable"
            ) from error

    def _ensure_postgresql(self) -> None:
        """Reject missing or non-PostgreSQL aliases before opening a UOW."""

        try:
            connection = connections[self._using]
        except (ConnectionDoesNotExist, KeyError) as error:
            raise AccountOwnerAssignmentEvidenceV5Unavailable(
                "Evidence V5 database alias is unavailable"
            ) from error
        if connection.vendor != "postgresql":
            raise AccountOwnerAssignmentEvidenceV5Unavailable(
                "Evidence V5 composition requires PostgreSQL"
            )


def build_account_owner_assignment_evidence_v5_facade(
    *,
    principal: AuthenticatedAccountPrincipalV3,
    policy_binding: SingleOwnerPolicyBinding,
    actor_source_id: str,
    actor_source_version: str,
    actor_source_content_hash: str,
    validity_period: timedelta,
    physical_row_provider: ExactPhysicalSimulatedAccountRowV2Provider,
    using: str = "default",
) -> AccountOwnerAssignmentEvidenceV5Facade:
    """Build the authenticated same-alias Evidence V5 facade.

    The caller supplies already-authenticated, server-owned facts.  This
    factory only validates and wires those facts; it never performs HTTP
    authentication and never exposes an owner-activation or execution port.
    """

    alias = _require_database_alias(using)
    if type(principal) is not AuthenticatedAccountPrincipalV3:
        raise TypeError("principal must be an exact authenticated principal")
    if type(policy_binding) is not SingleOwnerPolicyBinding:
        raise TypeError("policy_binding must be an exact server-owned policy binding")
    principal.__post_init__()
    policy_binding.__post_init__()
    if type(validity_period) is not timedelta or validity_period <= timedelta(0):
        raise ValueError("validity_period must be an exact positive timedelta")
    if not callable(getattr(physical_row_provider, "get_exact_current", None)):
        raise TypeError("physical_row_provider must expose get_exact_current")

    actors = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(using=alias)
    actor_reader = CanonicalAccountActorAuthorityRequestReader(
        current_reader=GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3(
            input_bundle_provider=DjangoAccountActorAuthorityCaptureBundleProviderV3(
                using=alias,
                require_capture_transaction=actors.require_capture_transaction,
            ),
            repository=actors,
        ),
        source_id=actor_source_id,
        source_version=actor_source_version,
        expected_content_hash=actor_source_content_hash,
    )
    policies = DjangoSingleOwnerAuthorityPolicyV1Repository(using=alias)
    participants = CurrentSingleOwnerParticipantsProvider(
        principal=principal,
        binding=policy_binding,
        policies=policies,
        actors=actor_reader,
    )

    binding_reader = GetExactCanonicalAccountCreationBindingV2(
        DjangoCanonicalAccountCreationConsumptionRepository(using=alias)
    )
    physical_reader = GetCurrentPhysicalAccountRowObservationV2(
        repository=DjangoPhysicalAccountRowObservationV2Repository(using=alias),
        row_provider=physical_row_provider,
    )
    reobservation_reader = GetCurrentCanonicalAccountOwnershipReobservationV1(
        repository=DjangoCanonicalAccountOwnershipReobservationV1Repository(using=alias),
        current_physical_reader=physical_reader,
    )
    receipt_reader = GetCurrentAccountOwnerAssignmentProvenanceReceiptV5(
        repository=DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(using=alias),
        binding_reader=binding_reader,
        policy_reader=policies,
        reobservation_reader=reobservation_reader,
    )
    subject_reader = GetCurrentAccountOwnerAssignmentSubjectV5(
        repository=DjangoAccountOwnerAssignmentSubjectV5Repository(using=alias),
        current_receipt_reader=receipt_reader,
    )
    evidence_repository = DjangoAccountOwnerAssignmentEvidenceV5Repository(using=alias)
    approve = ApproveAccountOwnerAssignmentEvidenceV5(
        subject_reader=subject_reader,
        participants_reader=participants,
        repository=evidence_repository,
        validity_period=validity_period,
    )
    exact = GetExactAccountOwnerAssignmentEvidenceV5(evidence_repository)
    current = GetCurrentAccountOwnerAssignmentEvidenceV5(
        subject_reader=subject_reader,
        participants_reader=participants,
        repository=evidence_repository,
    )
    return AccountOwnerAssignmentEvidenceV5Facade(
        using=alias,
        policy_id=policy_binding.policy_id,
        actors=actors,
        approve=approve,
        exact=exact,
        current=current,
    )


def _require_database_alias(value: object) -> str:
    """Validate one exact, bounded database alias before repository construction."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 64
        or any(character.isspace() for character in value)
    ):
        raise ValueError("using must be one exact database alias")
    return value


__all__ = [
    "AccountOwnerAssignmentEvidenceV5Facade",
    "build_account_owner_assignment_evidence_v5_facade",
]
