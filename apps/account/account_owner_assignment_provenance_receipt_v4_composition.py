"""Locked, same-alias composition for policy-bound owner receipt issuance."""

from __future__ import annotations

from datetime import timedelta

from django.db import DatabaseError, connections, transaction
from django.db.models import Model
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
from apps.account.application.account_owner_assignment_provenance_receipt_v4 import (
    IssueAccountOwnerAssignmentProvenanceReceiptV4,
    IssueAccountOwnerAssignmentProvenanceReceiptV4Command,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipantsProvider,
    SingleOwnerPolicyBinding,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v4 import (
    AccountOwnerAssignmentProvenanceReceiptV4,
)
from apps.account.infrastructure.account_actor_authority_capture_snapshot import (
    DjangoAccountActorAuthorityCaptureBundleProviderV3,
)
from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountAuthenticationContextSourceV3Model,
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
    AccountUserAuthoritySourceV3AnchorModel,
    AccountUserAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_models import (
    AccountOwnerAssignmentProvenanceReceiptV4Model,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v4_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_models import (
    AllocatedPhysicalAccountRowObservationV3Model,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_repository import (
    DjangoAllocatedPhysicalAccountRowObservationV3Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
    CanonicalAccountCreationConsumptionClaimModel,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)


class _LockedAccountOwnerAssignmentProvenanceReceiptV4Issuer:
    """Keep all closed-world reads stable until the receipt transaction commits.

    Locks deliberately cover whole evidence ledgers because their readers validate
    the whole world. EXCLUSIVE permits ordinary readers but excludes both writers
    and SELECT FOR UPDATE. NOWAIT avoids waiting cycles with independent legacy
    writers. This service produces evidence only, never an approval or scope grant.
    """

    def __init__(
        self,
        *,
        using: str,
        policy_id: str,
        actors: DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
        issue: IssueAccountOwnerAssignmentProvenanceReceiptV4,
    ) -> None:
        """Bind the transaction to the exact actor UOW used by its input reader."""
        self._using = using
        self._policy_id = policy_id
        self._actors = actors
        self._issue = issue

    def execute(
        self, command: IssueAccountOwnerAssignmentProvenanceReceiptV4Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV4:
        """Lock before the first current read and retain locks in any outer transaction."""
        if type(command) is not IssueAccountOwnerAssignmentProvenanceReceiptV4Command:
            raise TypeError("command must be an exact v4 issue command")
        command.__post_init__()
        try:
            connection = connections[self._using]
        except (ConnectionDoesNotExist, KeyError) as error:
            raise AccountOwnerAssignmentUnavailable(
                "receipt database alias is unavailable"
            ) from error
        if connection.vendor != "postgresql":
            raise AccountOwnerAssignmentUnavailable("locked receipt issuance requires PostgreSQL")
        try:
            with transaction.atomic(using=self._using), self._actors.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SHOW transaction_isolation")
                    if cursor.fetchone() != ("read committed",):
                        raise AccountOwnerAssignmentUnavailable(
                            "locked receipt issuance requires READ COMMITTED"
                        )
                    for key in ("receipt-v4:" + command.receipt_id, self._policy_id):
                        cursor.execute(
                            "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", [key]
                        )
                        if cursor.fetchone() != (True,):
                            raise AccountOwnerAssignmentUnavailable("receipt source writer is busy")
                    tables = sorted(
                        connection.ops.quote_name(model._meta.db_table) for model in _LOCK_MODELS
                    )
                    cursor.execute(f"LOCK TABLE {', '.join(tables)} IN EXCLUSIVE MODE NOWAIT")
                return self._issue.execute(command)
        except DatabaseError as error:
            raise AccountOwnerAssignmentUnavailable(
                "locked receipt sources are unavailable"
            ) from error


def build_account_owner_assignment_provenance_receipt_v4_issuer(
    *,
    principal: AuthenticatedAccountPrincipalV3,
    policy_binding: SingleOwnerPolicyBinding,
    actor_source_id: str,
    actor_source_version: str,
    actor_source_content_hash: str,
    validity_period: timedelta,
    using: str = "default",
) -> _LockedAccountOwnerAssignmentProvenanceReceiptV4Issuer:
    """Assemble server-selected policy and exact actor sources on one write alias."""
    if type(using) is not str or not using or using.strip() != using:
        raise ValueError("using must be an exact database alias")
    actors = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(using=using)
    reader = CanonicalAccountActorAuthorityRequestReader(
        current_reader=GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3(
            input_bundle_provider=DjangoAccountActorAuthorityCaptureBundleProviderV3(
                using=using, require_capture_transaction=actors.require_capture_transaction
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
        actors=reader,
    )
    issue = IssueAccountOwnerAssignmentProvenanceReceiptV4(
        binding_provider=AccountExactCanonicalAccountCreationBindingV2Provider(
            DjangoCanonicalAccountCreationConsumptionRepository(using=using)
        ),
        root_provider=AccountExactCurrentAllocatedPhysicalAccountRowObservationV3Provider(
            DjangoAllocatedPhysicalAccountRowObservationV3Repository(using=using)
        ),
        participants_reader=participants,
        repository=DjangoAccountOwnerAssignmentProvenanceReceiptV4Repository(using=using),
        validity_period=validity_period,
    )
    return _LockedAccountOwnerAssignmentProvenanceReceiptV4Issuer(
        using=using, policy_id=policy_binding.policy_id, actors=actors, issue=issue
    )


_LOCK_MODELS: tuple[type[Model], ...] = (
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountAuthenticationContextSourceV3Model,
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
    AccountUserAuthoritySourceV3AnchorModel,
    AccountUserAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
    CanonicalAccountCreationAllocationModel,
    AllocatedPhysicalAccountRowObservationV3Model,
    CanonicalAccountCreationConsumptionClaimModel,
    CanonicalAccountCreationBindingModel,
    CanonicalAccountCreationBindingV2Model,
    SingleOwnerAuthorityPolicyV1Model,
    AccountOwnerAssignmentProvenanceReceiptV4Model,
)
