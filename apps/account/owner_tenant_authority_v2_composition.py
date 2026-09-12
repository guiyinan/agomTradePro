"""Same-alias, source-locked composition for explicit owner decisions and reads."""

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from typing import TypeVar

from django.db import DatabaseError, connections, transaction
from django.utils.connection import ConnectionDoesNotExist

from apps.account.account_owner_assignment_evidence_v4_composition import (
    AccountOwnerAssignmentEvidenceV4Facade,
    build_account_owner_assignment_evidence_v4_facade,
)
from apps.account.application.account_actor_authority_request_reader import (
    CanonicalAccountActorAuthorityRequestReader,
)
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
    AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
    AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_evidence_v4 import (
    GetCurrentAccountOwnerAssignmentEvidenceV4Command,
    GetExactAccountOwnerAssignmentEvidenceV4,
)
from apps.account.application.owner_tenant_authority_v2 import (
    CurrentOwnerTenantAuthorityV2,
    GetCurrentOwnerTenantAuthorityV2Command,
    IssueOwnerTenantAuthorityV2Command,
    OwnerTenantAuthorityV2Service,
    RevokeOwnerTenantAuthorityV2Command,
)
from apps.account.application.owner_tenant_authority_v2_contracts import (
    CurrentOwnerPhysicalRowReader,
    OwnerTenantAuthorityV2Conflict,
    OwnerTenantAuthorityV2Corruption,
    OwnerTenantAuthorityV2Unavailable,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipantsProvider,
    SingleOwnerPolicyBinding,
)
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4,
)
from apps.account.domain.owner_tenant_authority_v2 import (
    OwnerTenantAuthorityV2,
    OwnerTenantAuthorityV2Revocation,
)
from apps.account.infrastructure.account_actor_authority_capture_snapshot import (
    DjangoAccountActorAuthorityCaptureBundleProviderV3,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_repository import (
    DjangoAccountOwnerAssignmentEvidenceV4Repository,
)
from apps.account.infrastructure.owner_tenant_authority_v2_repository import (
    DjangoOwnerTenantAuthorityV2Repository,
    lock_owner_tenant_authority_v2_sources,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)

_Result = TypeVar("_Result")


class _CurrentAssignment:
    def __init__(self, facade: AccountOwnerAssignmentEvidenceV4Facade) -> None:
        self._facade = facade

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV4Command
    ) -> AccountOwnerAssignmentEvidenceV4 | None:
        """Retain the full V4 source locks through the owner's outer transaction."""
        return self._facade.get_current(command)


class OwnerTenantAuthorityV2Facade:
    """Expose owner operations with server-bound identity, policy and physical reader.

    This is an internal composition boundary. Calling issue or revoke is an
    explicit application action; building this facade does not record approval.
    Historical audit access remains a separate application capability.
    """

    def __init__(
        self,
        *,
        using: str,
        policy_id: str,
        actors: DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
        service: OwnerTenantAuthorityV2Service,
    ) -> None:
        """Bind the closed server context used by every operation."""
        self._using = using
        self._policy_id = policy_id
        self._actors = actors
        self._service = service

    @property
    def unit_of_work_key(self) -> str:
        """Expose the server-bound transaction identity for integration checks."""
        return f"django:{self._using}"

    def with_current(
        self,
        command: GetCurrentOwnerTenantAuthorityV2Command,
        operation: Callable[[CurrentOwnerTenantAuthorityV2], _Result],
    ) -> _Result | None:
        """Keep current authority locked through a trusted synchronous read.

        Integration must materialize its result inside the callback, enforce
        its own exact artifact and shorter scope lifetime, and never expose a
        reusable grant or lazy read. Rechecking after the callback also rejects
        wall-clock expiry and source changes made within the same transaction.
        """

        def read_current() -> _Result | None:
            initial = self._service.get_current(command)
            if initial is None:
                return None
            result = operation(initial)
            final = self._service.get_current(command)
            if (
                final is None
                or not initial.observed_at <= final.observed_at < initial.valid_until
                or final.valid_until > initial.valid_until
                or final.authority != initial.authority
                or final.authentication != initial.authentication
                or final.physical.observed_at < initial.physical.observed_at
                or replace(initial.physical, observed_at=final.physical.observed_at)
                != final.physical
            ):
                return None
            return result

        return self._locked(read_current)

    def issue(self, command: IssueOwnerTenantAuthorityV2Command) -> OwnerTenantAuthorityV2:
        """Approve or revalidate one immutable decision under all current sources."""
        return self._locked(lambda: self._service.issue(command))

    def get_current(
        self, command: GetCurrentOwnerTenantAuthorityV2Command
    ) -> CurrentOwnerTenantAuthorityV2 | None:
        """Observe current ownership through fresh authenticated source reads."""
        return self._locked(lambda: self._service.get_current(command))

    def revoke(
        self, command: RevokeOwnerTenantAuthorityV2Command
    ) -> OwnerTenantAuthorityV2Revocation:
        """Record an explicit immutable revocation by the current authenticated owner."""
        return self._locked(lambda: self._service.revoke(command))

    def _locked(self, operation: Callable[[], _Result]) -> _Result:
        try:
            if connections[self._using].vendor != "postgresql":
                raise OwnerTenantAuthorityV2Unavailable("owner composition requires PostgreSQL")
            with transaction.atomic(using=self._using):
                lock_owner_tenant_authority_v2_sources(using=self._using, policy_id=self._policy_id)
                with self._actors.atomic():
                    return operation()
        except (
            AccountOwnerAssignmentCorruption,
            AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
        ) as error:
            raise OwnerTenantAuthorityV2Corruption("owner source graph is corrupt") from error
        except (
            AccountOwnerAssignmentConflict,
            AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
        ) as error:
            raise OwnerTenantAuthorityV2Conflict("owner source graph changed") from error
        except (
            AccountOwnerAssignmentUnavailable,
            AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
            DatabaseError,
            ConnectionDoesNotExist,
        ) as error:
            raise OwnerTenantAuthorityV2Unavailable(
                "owner source transaction unavailable"
            ) from error


def build_owner_tenant_authority_v2_facade(
    *,
    principal: AuthenticatedAccountPrincipalV3,
    policy_binding: SingleOwnerPolicyBinding,
    actor_source_id: str,
    actor_source_version: str,
    actor_source_content_hash: str,
    physical: CurrentOwnerPhysicalRowReader,
    validity_period: timedelta,
    using: str = "default",
) -> OwnerTenantAuthorityV2Facade:
    """Compose one server-selected scope with a same-alias live physical account port.

    The outer integration root supplies the physical reader through its public
    application protocol. No cross-app Infrastructure dependency or client
    identity, policy, clock or execution permission is introduced here.
    """
    repository = DjangoOwnerTenantAuthorityV2Repository(using=using)
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
    assignment = build_account_owner_assignment_evidence_v4_facade(
        principal=principal,
        policy_binding=policy_binding,
        actor_source_id=actor_source_id,
        actor_source_version=actor_source_version,
        actor_source_content_hash=actor_source_content_hash,
        validity_period=validity_period,
        using=using,
    )
    service = OwnerTenantAuthorityV2Service(
        repository=repository,
        current_assignments=_CurrentAssignment(assignment),
        historical_assignments=GetExactAccountOwnerAssignmentEvidenceV4(
            DjangoAccountOwnerAssignmentEvidenceV4Repository(using=using)
        ),
        participants=participants,
        physical=physical,
        validity_period=validity_period,
    )
    return OwnerTenantAuthorityV2Facade(
        using=using, policy_id=policy_binding.policy_id, actors=actors, service=service
    )
