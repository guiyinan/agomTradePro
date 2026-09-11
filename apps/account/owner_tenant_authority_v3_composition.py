"""Same-alias composition for authenticated owner/tenant Authority V3.

The composition root binds the authenticated principal, one server-selected
single-owner policy, one actor-authority source, and one PostgreSQL alias.  It
does not authenticate requests or create execution permissions.  Authority V3
is an evidence-read boundary over an inactive Evidence V5 decision.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import TypeVar

from django.db import DatabaseError, connections, transaction
from django.utils.connection import ConnectionDoesNotExist

from apps.account.account_owner_assignment_evidence_v5_composition import (
    AccountOwnerAssignmentEvidenceV5Facade,
    build_account_owner_assignment_evidence_v5_facade,
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
from apps.account.application.account_owner_assignment_evidence_v5 import (
    GetCurrentAccountOwnerAssignmentEvidenceV5Command,
    GetExactAccountOwnerAssignmentEvidenceV5Command,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
    GetExactOwnerTenantAuthorityV3Command,
    IssueOwnerTenantAuthorityV3Command,
    OwnerTenantAuthorityV3Service,
    RevokeOwnerTenantAuthorityV3Command,
    SupersedeOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    CurrentOwnerTenantAuthorityV3,
    OwnerTenantAuthorityV3Conflict,
    OwnerTenantAuthorityV3Corruption,
    OwnerTenantAuthorityV3Unavailable,
)
from apps.account.application.physical_account_row_observation_v2 import (
    ExactPhysicalSimulatedAccountRowV2Provider,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipantsProvider,
    SingleOwnerPolicyBinding,
)
from apps.account.domain.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5,
)
from apps.account.domain.owner_tenant_authority_v3 import (
    OwnerTenantAuthorityV3,
    OwnerTenantAuthorityV3Revocation,
)
from apps.account.infrastructure.account_actor_authority_capture_snapshot import (
    DjangoAccountActorAuthorityCaptureBundleProviderV3,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.owner_tenant_authority_v3_repository import (
    DjangoOwnerTenantAuthorityV3Repository,
    lock_owner_tenant_authority_v3_sources,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)

_ReturnT = TypeVar("_ReturnT")


class _CurrentAssignmentV5Reader:
    """Adapt the public Evidence V5 current facade to the V3 reader port."""

    def __init__(self, facade: AccountOwnerAssignmentEvidenceV5Facade) -> None:
        """Bind the already-composed public Evidence V5 facade."""

        self._facade = facade

    def execute(
        self,
        command: GetCurrentAccountOwnerAssignmentEvidenceV5Command,
    ) -> AccountOwnerAssignmentEvidenceV5 | None:
        """Read the selected current Evidence V5 through its public facade."""

        return self._facade.get_current(command)


class _HistoricalAssignmentV5Reader:
    """Adapt the public Evidence V5 exact facade to the V3 reader port."""

    def __init__(self, facade: AccountOwnerAssignmentEvidenceV5Facade) -> None:
        """Bind the already-composed public Evidence V5 facade."""

        self._facade = facade

    def execute(
        self,
        command: GetExactAccountOwnerAssignmentEvidenceV5Command,
    ) -> AccountOwnerAssignmentEvidenceV5 | None:
        """Read the selected historical Evidence V5 through its public facade."""

        return self._facade.get_exact(command)


class OwnerTenantAuthorityV3Facade:
    """Expose authenticated Authority V3 operations on one source-locked alias.

    The principal, policy, actor source, and alias are fixed at construction.
    Current observations are short-lived values.  ``with_current`` invokes a
    synchronous callback while the source transaction remains open and checks
    the authority, authentication, and source projection again afterwards;
    callers must materialize any read result inside that callback.
    """

    def __init__(
        self,
        *,
        using: str,
        policy_id: str,
        actors: DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
        service: OwnerTenantAuthorityV3Service,
    ) -> None:
        """Bind one database alias and the server-owned Authority V3 service."""

        self._using = using
        self._policy_id = policy_id
        self._actors = actors
        self._service = service

    @property
    def unit_of_work_key(self) -> str:
        """Return the transaction identity used by this composition root."""

        return f"django:{self._using}"

    def issue(
        self,
        command: IssueOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3:
        """Issue or replay one immutable Authority V3 root."""

        return self._locked(lambda: self._service.issue(command))

    def supersede(
        self,
        command: SupersedeOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3:
        """Append or replay one immutable Authority V3 successor."""

        return self._locked(lambda: self._service.supersede(command))

    def successor(
        self,
        command: SupersedeOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3:
        """Expose the explicit successor spelling for the same lifecycle step."""

        return self._locked(lambda: self._service.successor(command))

    def get_current(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> CurrentOwnerTenantAuthorityV3 | None:
        """Return one finite observation after current source revalidation."""

        return self._locked(lambda: self._service.get_current(command))

    def get_exact(
        self,
        command: GetExactOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3 | None:
        """Return one immutable historical Authority V3 by exact selector."""

        return self._locked(lambda: self._service.get_exact(command))

    def with_current(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
        operation: Callable[[CurrentOwnerTenantAuthorityV3], _ReturnT],
    ) -> _ReturnT | None:
        """Materialize a read while rejecting authority or source drift.

        The callback receives only the current observation and runs inside the
        source transaction.  The observation is re-read after the callback;
        expiry, authority changes, authentication changes, and source-clock
        regressions discard the callback result.  No reusable grant is made.
        """

        if not callable(operation):
            raise TypeError("operation must be callable")

        def read_current() -> _ReturnT | None:
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
                or final.authority.assignment != initial.authority.assignment
                or final.authority.policy != initial.authority.policy
                or final.authentication.source_content_hash
                != initial.authentication.source_content_hash
            ):
                return None
            return result

        return self._locked(read_current)

    def revoke(
        self,
        command: RevokeOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3Revocation:
        """Append or replay one immutable Authority V3 revocation."""

        return self._locked(lambda: self._service.revoke(command))

    def _locked(self, operation: Callable[[], _ReturnT]) -> _ReturnT:
        """Run one operation under V5/V3 locks followed by actor capture UOW."""

        self._ensure_postgresql()
        try:
            with transaction.atomic(using=self._using):
                lock_owner_tenant_authority_v3_sources(
                    using=self._using,
                    policy_id=self._policy_id,
                )
                with self._actors.atomic():
                    return operation()
        except (
            OwnerTenantAuthorityV3Corruption,
            AccountOwnerAssignmentCorruption,
            AccountOwnerAssignmentActorAuthoritySourceV3Corruption,
        ) as error:
            if isinstance(error, OwnerTenantAuthorityV3Corruption):
                raise
            raise OwnerTenantAuthorityV3Corruption(
                "owner authority source graph is corrupt"
            ) from error
        except (
            OwnerTenantAuthorityV3Conflict,
            AccountOwnerAssignmentConflict,
            AccountOwnerAssignmentActorAuthoritySourceV3Conflict,
        ) as error:
            if isinstance(error, OwnerTenantAuthorityV3Conflict):
                raise
            raise OwnerTenantAuthorityV3Conflict("owner authority source graph changed") from error
        except (
            OwnerTenantAuthorityV3Unavailable,
            AccountOwnerAssignmentUnavailable,
            AccountOwnerAssignmentActorAuthoritySourceV3Unavailable,
            DatabaseError,
            ConnectionDoesNotExist,
        ) as error:
            if isinstance(error, OwnerTenantAuthorityV3Unavailable):
                raise
            raise OwnerTenantAuthorityV3Unavailable(
                "owner authority source transaction unavailable"
            ) from error

    def _ensure_postgresql(self) -> None:
        """Reject a missing or non-PostgreSQL alias before opening a UOW."""

        try:
            connection = connections[self._using]
        except (ConnectionDoesNotExist, DatabaseError, KeyError) as error:
            raise OwnerTenantAuthorityV3Unavailable(
                "owner authority database alias is unavailable"
            ) from error
        if connection.vendor != "postgresql":
            raise OwnerTenantAuthorityV3Unavailable(
                "owner authority composition requires PostgreSQL"
            )


def build_owner_tenant_authority_v3_facade(
    *,
    principal: AuthenticatedAccountPrincipalV3,
    policy_binding: SingleOwnerPolicyBinding,
    actor_source_id: str,
    actor_source_version: str,
    actor_source_content_hash: str,
    validity_period: timedelta,
    physical_row_provider: ExactPhysicalSimulatedAccountRowV2Provider,
    using: str = "default",
) -> OwnerTenantAuthorityV3Facade:
    """Build one authenticated same-alias Authority V3 facade.

    All identity, policy, actor-source, and database selections are supplied
    by the server composition boundary.  The returned facade exposes only
    inactive evidence-read authority and never an HTTP or execution port.
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
    participants = CurrentSingleOwnerParticipantsProvider(
        principal=principal,
        binding=policy_binding,
        policies=DjangoSingleOwnerAuthorityPolicyV1Repository(using=alias),
        actors=actor_reader,
    )
    evidence = build_account_owner_assignment_evidence_v5_facade(
        principal=principal,
        policy_binding=policy_binding,
        actor_source_id=actor_source_id,
        actor_source_version=actor_source_version,
        actor_source_content_hash=actor_source_content_hash,
        validity_period=validity_period,
        physical_row_provider=physical_row_provider,
        using=alias,
    )
    service = OwnerTenantAuthorityV3Service(
        repository=DjangoOwnerTenantAuthorityV3Repository(using=alias),
        current_assignments=_CurrentAssignmentV5Reader(evidence),
        historical_assignments=_HistoricalAssignmentV5Reader(evidence),
        participants=participants,
        validity_period=validity_period,
    )
    return OwnerTenantAuthorityV3Facade(
        using=alias,
        policy_id=policy_binding.policy_id,
        actors=actors,
        service=service,
    )


def _require_database_alias(value: object) -> str:
    """Validate one exact, bounded database alias before construction."""

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
    "OwnerTenantAuthorityV3Facade",
    "build_owner_tenant_authority_v3_facade",
]
