"""Read-only generation-bound shadow scan for System Audit authority V3."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from django.db import DatabaseError, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.application.account_actor_authority_request_reader import (
    CanonicalAccountActorAuthorityRequestReader,
)
from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3,
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
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
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
    OwnerTenantAuthorityV3Service,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    CurrentOwnerAssignmentEvidenceV5Reader,
    CurrentOwnerTenantAuthorityV3,
    HistoricalOwnerAssignmentEvidenceV5Reader,
    OwnerTenantAuthorityV3Conflict,
    OwnerTenantAuthorityV3Unavailable,
)
from apps.account.application.physical_account_row_observation_v2 import (
    ExactPhysicalSimulatedAccountRowV2Provider,
    GetCurrentPhysicalAccountRowObservationV2,
    PhysicalAccountRowProviderIdentity,
    PhysicalAccountRowProviderIdentityScope,
    PhysicalAccountRowProviderReadClockScope,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipantsProvider,
    SingleOwnerPolicyBinding,
)
from apps.account.domain.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5,
)
from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationProof,
    AccountAuthorityGenerationUnavailable,
    capture_account_authority_snapshot_physical_provider_identity,
    capture_active_account_authority_physical_provider_identity,
    read_account_authority_generation_proof,
    require_active_account_authority_generation_fence,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_bundle_provider import (
    DjangoAccountActorAuthorityInputBundleProviderV3,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_repository import (
    DjangoAccountOwnerAssignmentEvidenceV5Repository,
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
from apps.account.infrastructure.owner_tenant_authority_v3_models import (
    _activate_owner_tenant_authority_v3_uow,
)
from apps.account.infrastructure.owner_tenant_authority_v3_read_context import (
    OwnerTenantAuthorityV3OperationReadContext,
)
from apps.account.infrastructure.owner_tenant_authority_v3_repository import (
    DjangoOwnerTenantAuthorityV3Repository,
    OwnerTenantAuthorityV3Clock,
)
from apps.account.infrastructure.physical_account_row_observation_v2_repository import (
    DjangoPhysicalAccountRowObservationV2Repository,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from shared.infrastructure.immutable_read_snapshot import suspend_immutable_read_reuse

AccountAuthorityV3CallerTransactionMode = Literal[
    "repeatable_read_read_only", "generation_fenced_read_committed_read_write"
]


class DjangoAccountAuthorityNoLockSnapshotBundleProviderV3(
    DjangoAccountActorAuthorityInputBundleProviderV3
):
    """Read actor inputs inside an exact caller-owned transaction without locks."""

    def __init__(
        self,
        *,
        using: str = "default",
        transaction_mode: AccountAuthorityV3CallerTransactionMode = ("repeatable_read_read_only"),
    ) -> None:
        """Bind the actor input reader to one exact alias and transaction mode."""

        _validate_transaction_mode(transaction_mode)
        super().__init__(using=using)
        self._transaction_mode = transaction_mode

    def _snapshot(self, connection: BaseDatabaseWrapper) -> AbstractContextManager[None]:
        """Require the selected caller transaction and return a no-op scope."""

        if self._transaction_mode == "repeatable_read_read_only":
            _require_repeatable_read_only_connection(connection, self._using)
        else:
            _require_caller_owned_transaction(connection, self._using, self._transaction_mode)
            require_active_account_authority_generation_fence(
                using=self._using,
                connection=connection,
            )
        return nullcontext()


class _GenerationFencedOwnerTenantAuthorityV3Repository(DjangoOwnerTenantAuthorityV3Repository):
    """Join the finalizer-owned generation fence for one current graph read."""

    def __init__(
        self,
        *,
        expected_generation: int,
        using: str,
        clock: OwnerTenantAuthorityV3Clock,
        assignments: DjangoAccountOwnerAssignmentEvidenceV5Repository,
        policies: DjangoSingleOwnerAuthorityPolicyV1Repository,
        actors: DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
    ) -> None:
        """Bind the read-only repository UOW to one locked generation."""

        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError("expected_generation must be one non-negative integer")
        super().__init__(
            using=using,
            clock=clock,
            assignments=assignments,
            policies=policies,
            actors=actors,
        )
        self._expected_generation = expected_generation

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Reuse the caller's outer transaction without creating a savepoint."""

        self._postgresql()
        connection = _connection(self._using)
        require_active_account_authority_generation_fence(
            using=self._using,
            connection=connection,
            generation=self._expected_generation,
        )
        if self._active:
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 UOW cannot be re-entered"
            )
        token = self._token
        self._active = True
        self._uow = token
        try:
            with _activate_owner_tenant_authority_v3_uow(token):
                yield
            require_active_account_authority_generation_fence(
                using=self._using,
                connection=connection,
                generation=self._expected_generation,
            )
        except AccountAuthorityGenerationUnavailable:
            raise
        except DatabaseError as error:
            raise OwnerTenantAuthorityV3Unavailable(
                "owner tenant authority v3 caller-owned transaction is unavailable"
            ) from error
        finally:
            self._uow = None
            self._active = False


@dataclass(frozen=True, slots=True)
class AccountAuthorityShadowFingerprintV3:
    """Identity-safe comparison fields for one current authority observation."""

    authority_identity_hash: str
    authority_content_hash: str
    assignment_identity_hash: str
    assignment_content_hash: str
    policy_identity_hash: str
    policy_content_hash: str
    actor_source_identity_hash: str
    physical_source_identity_hash: str
    valid_until: datetime
    complete_graph_hash: str | None = None


@dataclass(frozen=True, slots=True)
class AccountAuthorityCurrentGraphSelectorV3:
    """Redacted selector binding for one complete current authority graph."""

    database_alias: str
    authority_selector_hash: str
    authority_content_hash: str
    actor_source_selector_hash: str
    actor_source_content_hash: str

    def __post_init__(self) -> None:
        """Reject incomplete aliases, selectors, or content hashes."""

        _require_alias(self.database_alias)
        _require_hash(self.authority_selector_hash, "authority_selector_hash")
        _require_hash(self.authority_content_hash, "authority_content_hash")
        _require_hash(self.actor_source_selector_hash, "actor_source_selector_hash")
        _require_hash(self.actor_source_content_hash, "actor_source_content_hash")


@dataclass(frozen=True, slots=True)
class AccountAuthorityShadowComparisonV3:
    """Compare only redacted hashes and the effective expiry boundary."""

    legacy: AccountAuthorityShadowFingerprintV3 | None
    shadow: AccountAuthorityShadowFingerprintV3 | None
    matches: bool
    differing_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AccountAuthorityShadowScanResultV3:
    """Bind the observed generation, cutoff, selector, and comparison to an alias.

    The selector, cutoff, and physical identity are optional only so historical
    callers that construct partial root/revocation scans remain compatible.
    Complete-graph proof capture rejects any result missing one of them.
    """

    database_alias: str
    proof_generation: int
    comparison: AccountAuthorityShadowComparisonV3
    selector: AccountAuthorityCurrentGraphSelectorV3 | None = None
    checked_at: datetime | None = None
    physical_identity: PhysicalAccountRowProviderIdentity | None = None


@dataclass(frozen=True, slots=True)
class AccountAuthorityCurrentGraphReadV3:
    """Expose a point-in-time graph projection and its single database cutoff.

    ``checked_at`` is the graph's selection cutoff. It is not an expiry lease or
    a promise that the projection remains current after this read completes.
    """

    checked_at: datetime
    authority: CurrentOwnerTenantAuthorityV3 | None
    physical_identity: PhysicalAccountRowProviderIdentity | None = None

    def __post_init__(self) -> None:
        """Reject naive cutoffs and malformed current projections."""

        if type(self.checked_at) is not datetime or not _is_aware(self.checked_at):
            raise ValueError("checked_at must be an exact aware datetime")
        if self.physical_identity is not None and type(self.physical_identity) is not (
            PhysicalAccountRowProviderIdentity
        ):
            raise TypeError("physical_identity must be an exact provider identity")
        if self.authority is not None:
            if type(self.authority) is not CurrentOwnerTenantAuthorityV3:
                raise TypeError("authority must be an exact current Authority V3 projection")
            self.authority.__post_init__()
            if self.authority.observed_at != self.checked_at:
                raise ValueError("authority projection does not use the graph cutoff")
            if self.authority.valid_until <= self.checked_at:
                raise ValueError("authority projection is expired at the graph cutoff")

    @property
    def cutoff(self) -> datetime:
        """Return the database timestamp used to select the complete graph."""

        return self.checked_at

    @property
    def fingerprint(self) -> AccountAuthorityShadowFingerprintV3 | None:
        """Return the stable, redacted full graph fingerprint when one exists."""

        return _fingerprint(self.authority)

    @property
    def valid_until(self) -> datetime | None:
        """Return the earliest validity boundary sealed by the current graph."""

        return None if self.authority is None else self.authority.valid_until


@dataclass(frozen=True, slots=True)
class _AuthorityGraphFrozenClock:
    """Serve the one database cutoff to every repository in an authority graph."""

    value: datetime

    def now(self) -> datetime:
        """Return the immutable point-in-time cutoff without consulting app time."""

        return self.value


class AccountAuthorityCurrentGraphReaderV3:
    """Read the complete current Authority V3 graph in a caller-owned transaction.

    The reader never opens a transaction. Its mode must match the caller's exact
    PostgreSQL transaction settings: RR/READ ONLY for a shadow scan or
    RC/READ WRITE after a generation fence. It composes the existing Application
    service graph, including Evidence V5 parent validation. Every graph read is
    wrapped in a concrete provider identity scope bound to the caller's Django
    wrapper, DBAPI connection, backend PID, transaction xid, and execution task.
    Every repository clock in one graph read receives one checked PostgreSQL
    ``clock_timestamp()`` value. The result exposes that point-in-time cutoff;
    it is not a final expiry lease.
    """

    def __init__(
        self,
        *,
        actor_source_id: str,
        actor_source_version: str,
        actor_content_hash: str,
        physical_row_provider: ExactPhysicalSimulatedAccountRowV2Provider,
        using: str = "default",
        transaction_mode: AccountAuthorityV3CallerTransactionMode,
    ) -> None:
        """Bind current graph source selectors, provider, alias, and transaction mode."""

        _require_alias(using)
        _validate_transaction_mode(transaction_mode)
        for name, value in (
            ("actor_source_id", actor_source_id),
            ("actor_source_version", actor_source_version),
        ):
            _require_token(value, name)
        _require_hash(actor_content_hash, "actor_content_hash")
        if getattr(physical_row_provider, "database_alias", None) != using:
            raise ValueError("physical row provider must use the current graph database alias")
        if not callable(getattr(physical_row_provider, "get_exact_current", None)):
            raise TypeError("physical row provider must expose get_exact_current")
        if not callable(getattr(physical_row_provider, "bind_physical_identity", None)):
            raise TypeError("physical row provider must expose bind_physical_identity")
        if not callable(getattr(physical_row_provider, "bind_read_clock", None)):
            raise TypeError("physical row provider must expose bind_read_clock")
        self._actor_source_id = actor_source_id
        self._actor_source_version = actor_source_version
        self._actor_content_hash = actor_content_hash
        self._physical_row_provider = physical_row_provider
        self._using = using
        self._transaction_mode = transaction_mode

    def read(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
        *,
        generation: int | None = None,
    ) -> AccountAuthorityCurrentGraphReadV3:
        """Return the graph projection and one cutoff in the caller's transaction.

        Generation-fenced RC/RW callers must pass the generation yielded by
        ``caller_owned_account_authority_generation_fence``.
        """

        if type(command) is not GetCurrentOwnerTenantAuthorityV3Command:
            raise TypeError("command must be exact GetCurrentOwnerTenantAuthorityV3Command")
        command.__post_init__()
        connection = _connection(self._using)
        _require_caller_owned_transaction(connection, self._using, self._transaction_mode)
        if self._transaction_mode == "repeatable_read_read_only":
            if generation is not None:
                raise AccountAuthorityGenerationUnavailable(
                    "read-only current graph mode does not accept a generation fence"
                )
        else:
            if type(generation) is not int:
                raise AccountAuthorityGenerationUnavailable(
                    "generation-fenced current graph mode requires the locked generation"
                )
            require_active_account_authority_generation_fence(
                using=self._using,
                connection=connection,
                generation=generation,
            )
        identity = self._capture_identity(connection, generation)
        checked_at = _read_database_clock_timestamp(connection, self._using)
        if identity != self._capture_identity(connection, generation):
            raise AccountAuthorityGenerationUnavailable(
                "current graph transaction identity changed while reading its cutoff"
            )
        clock = _AuthorityGraphFrozenClock(checked_at)
        identity_scope_provider = cast(
            PhysicalAccountRowProviderIdentityScope,
            self._physical_row_provider,
        )
        clock_scope_provider = cast(
            PhysicalAccountRowProviderReadClockScope,
            self._physical_row_provider,
        )
        with identity_scope_provider.bind_physical_identity(identity):
            with clock_scope_provider.bind_read_clock(clock):
                with suspend_immutable_read_reuse():
                    result = self._read_application_graph(
                        command,
                        clock=clock,
                        generation=generation,
                    )
        if self._transaction_mode != "repeatable_read_read_only":
            require_active_account_authority_generation_fence(
                using=self._using,
                connection=connection,
                generation=generation,
            )
        if result is not None:
            if type(result) is not CurrentOwnerTenantAuthorityV3:
                raise AccountAuthorityGenerationUnavailable(
                    "current graph reader returned an invalid Authority V3 projection"
                )
            result.__post_init__()
            if result.observed_at != checked_at:
                raise AccountAuthorityGenerationUnavailable(
                    "current graph projection does not use its database cutoff"
                )
        return AccountAuthorityCurrentGraphReadV3(
            checked_at=checked_at,
            authority=result,
            physical_identity=identity,
        )

    @property
    def database_alias(self) -> str:
        """Return the exact alias used by this graph reader."""

        return self._using

    @property
    def transaction_mode(self) -> AccountAuthorityV3CallerTransactionMode:
        """Return the caller-owned transaction mode required by this reader."""

        return self._transaction_mode

    def selector_for(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> AccountAuthorityCurrentGraphSelectorV3:
        """Return a redacted selector for the command and fixed actor source."""

        if type(command) is not GetCurrentOwnerTenantAuthorityV3Command:
            raise TypeError("command must be exact GetCurrentOwnerTenantAuthorityV3Command")
        command.__post_init__()
        return AccountAuthorityCurrentGraphSelectorV3(
            database_alias=self._using,
            authority_selector_hash=_identity_digest(
                command.authority_id,
                command.authority_version,
            ),
            authority_content_hash=command.expected_content_hash,
            actor_source_selector_hash=_identity_digest(
                self._actor_source_id,
                self._actor_source_version,
            ),
            actor_source_content_hash=self._actor_content_hash,
        )

    def _capture_identity(
        self,
        connection: BaseDatabaseWrapper,
        generation: int | None,
    ) -> PhysicalAccountRowProviderIdentity:
        """Capture the exact alias, physical transaction, task, and generation."""

        if self._transaction_mode == "repeatable_read_read_only":
            return capture_account_authority_snapshot_physical_provider_identity(
                using=self._using,
                connection=connection,
            )
        return capture_active_account_authority_physical_provider_identity(
            using=self._using,
            connection=connection,
            generation=generation,
        )

    def _read_application_graph(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
        *,
        clock: _AuthorityGraphFrozenClock,
        generation: int | None,
    ) -> CurrentOwnerTenantAuthorityV3 | None:
        """Compose the existing Authority V3 Application graph and Evidence V5 readers."""

        actor_repository = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(
            using=self._using,
            clock=clock,
        )
        policies = DjangoSingleOwnerAuthorityPolicyV1Repository(using=self._using, clock=clock)
        subjects = DjangoAccountOwnerAssignmentSubjectV5Repository(using=self._using, clock=clock)
        read_context = OwnerTenantAuthorityV3OperationReadContext(
            using=self._using,
            connection_provider=lambda: connections[self._using].connection,
        )
        evidence_repository = DjangoAccountOwnerAssignmentEvidenceV5Repository(
            using=self._using,
            clock=clock,
            subjects=subjects,
            actors=actor_repository,
            read_context=read_context,
        )
        authority_repository: DjangoOwnerTenantAuthorityV3Repository
        if self._transaction_mode == "generation_fenced_read_committed_read_write":
            if type(generation) is not int:
                raise AccountAuthorityGenerationUnavailable(
                    "generation-fenced current graph repository requires the locked generation"
                )
            authority_repository = _GenerationFencedOwnerTenantAuthorityV3Repository(
                expected_generation=generation,
                using=self._using,
                clock=clock,
                assignments=evidence_repository,
                policies=policies,
                actors=actor_repository,
            )
        else:
            authority_repository = DjangoOwnerTenantAuthorityV3Repository(
                using=self._using,
                clock=clock,
                assignments=evidence_repository,
                policies=policies,
                actors=actor_repository,
            )
        provisional = authority_repository.get_winner(
            authority_id=command.authority_id,
            authority_version=command.authority_version,
            as_of=authority_repository.now(),
        )
        if provisional is None:
            return None

        actor_current_reader = GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3(
            input_bundle_provider=DjangoAccountAuthorityNoLockSnapshotBundleProviderV3(
                using=self._using,
                transaction_mode=self._transaction_mode,
            ),
            repository=actor_repository,
        )
        actor_source = actor_current_reader.execute(
            GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command(
                source_id=self._actor_source_id,
                source_version=self._actor_source_version,
                expected_content_hash=self._actor_content_hash,
                as_of=actor_repository.now(),
            )
        )
        if actor_source is None:
            return None

        principal = AuthenticatedAccountPrincipalV3(
            principal_id=actor_source.principal_id,
            user_id=actor_source.user_id,
            authentication_context_hash=actor_source.authentication_context_content_hash,
            authenticated_at=actor_source.principal_authenticated_at,
            valid_until=actor_source.principal_valid_until,
        )
        policy = provisional.authority.policy
        binding = SingleOwnerPolicyBinding(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_content_hash=policy.content_hash,
            tenant_id=policy.tenant_id,
            owner_id=policy.owner_id,
            account_namespace=policy.account_namespace,
            account_id=policy.account_id,
        )
        actor_request_reader = CanonicalAccountActorAuthorityRequestReader(
            current_reader=actor_current_reader,
            source_id=self._actor_source_id,
            source_version=self._actor_source_version,
            expected_content_hash=self._actor_content_hash,
        )
        participants = CurrentSingleOwnerParticipantsProvider(
            principal=principal,
            binding=binding,
            policies=policies,
            actors=actor_request_reader,
        )

        evidence_repository, current_evidence, exact_evidence = _build_evidence_readers(
            using=self._using,
            clock=clock,
            policies=policies,
            participants=participants,
            subjects=subjects,
            evidence_repository=evidence_repository,
            physical_row_provider=self._physical_row_provider,
        )
        service = OwnerTenantAuthorityV3Service(
            repository=authority_repository,
            current_assignments=_CurrentEvidenceReader(current_evidence),
            historical_assignments=_HistoricalEvidenceReader(exact_evidence),
            participants=participants,
            validity_period=timedelta(seconds=1),
            read_phase=read_context.phase,
        )
        return service.get_current(command)


class AccountAuthorityShadowScannerV3:
    """Compare legacy output with a full Application restore in one RR snapshot.

    This scanner is intentionally a separate shadow entry point. It does not
    authorize requests, acquire the RC final fence, publish data, or persist
    scan results. Call it only after the legacy preflight has produced its
    result; that result remains the sole decision input. The legacy observation
    and this scan use independent repository clock reads: shadow first uses a
    repository clock for provisional root selection and another for actor
    validation, then the existing service applies its own cutoff and deliberately
    rechecks sources at multiple later cutoffs. The legacy observation completed
    earlier with its own clock reads. Expiry or source changes between those
    observations are diagnostic differences and never replace the legacy result.
    """

    def __init__(
        self,
        *,
        actor_source_id: str,
        actor_source_version: str,
        actor_content_hash: str,
        physical_row_provider: ExactPhysicalSimulatedAccountRowV2Provider,
        using: str = "default",
    ) -> None:
        """Bind fixed source selectors and a verified physical-provider capability."""

        _require_alias(using)
        for name, value in (
            ("actor_source_id", actor_source_id),
            ("actor_source_version", actor_source_version),
        ):
            _require_token(value, name)
        _require_hash(actor_content_hash, "actor_content_hash")
        if getattr(physical_row_provider, "database_alias", None) != using:
            raise ValueError("physical row provider must use the shadow scan database alias")
        if not callable(getattr(physical_row_provider, "get_exact_current", None)):
            raise TypeError("physical row provider must expose get_exact_current")
        if not callable(getattr(physical_row_provider, "bind_physical_identity", None)):
            raise TypeError("physical row provider must expose bind_physical_identity")
        self._actor_source_id = actor_source_id
        self._actor_source_version = actor_source_version
        self._actor_content_hash = actor_content_hash
        self._physical_row_provider = physical_row_provider
        self._using = using

    def scan(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
        legacy_current: CurrentOwnerTenantAuthorityV3 | None,
    ) -> AccountAuthorityShadowScanResultV3:
        """Run the read-only shadow comparison without changing legacy authority."""

        if type(command) is not GetCurrentOwnerTenantAuthorityV3Command:
            raise TypeError("command must be exact GetCurrentOwnerTenantAuthorityV3Command")
        command.__post_init__()
        if legacy_current is not None:
            if type(legacy_current) is not CurrentOwnerTenantAuthorityV3:
                raise TypeError("legacy_current must be an exact current authority observation")
            legacy_current.__post_init__()
            legacy_authority = legacy_current.authority
            if (
                legacy_authority.authority_id,
                legacy_authority.authority_version,
                legacy_authority.content_hash,
            ) != (
                command.authority_id,
                command.authority_version,
                command.expected_content_hash,
            ):
                raise AccountAuthorityGenerationUnavailable(
                    "legacy authority observation selectors do not match shadow command"
                )

        connection = _connection(self._using)
        with suspend_immutable_read_reuse():
            with _read_only_repeatable_read_transaction(self._using, connection):
                proof = read_account_authority_generation_proof(using=self._using)
                if type(proof) is not AccountAuthorityGenerationProof or proof.using != self._using:
                    raise AccountAuthorityGenerationUnavailable(
                        "account authority shadow proof belongs to another database alias"
                    )
                graph_read = self._read_shadow(command)
                shadow_current = graph_read.authority
                if shadow_current is not None:
                    if type(shadow_current) is not CurrentOwnerTenantAuthorityV3:
                        raise AccountAuthorityGenerationUnavailable(
                            "account authority shadow reader returned an invalid projection"
                        )
                    shadow_current.__post_init__()

        return AccountAuthorityShadowScanResultV3(
            database_alias=self._using,
            proof_generation=proof.generation,
            comparison=_compare_current_observations(legacy_current, shadow_current),
            selector=self._graph_reader().selector_for(command),
            checked_at=graph_read.checked_at,
            physical_identity=graph_read.physical_identity,
        )

    def _read_shadow(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> AccountAuthorityCurrentGraphReadV3:
        """Restore the graph and retain its point-in-time result metadata."""

        return self._graph_reader().read(command)

    def _graph_reader(self) -> AccountAuthorityCurrentGraphReaderV3:
        """Build the read-only reader with the scanner's fixed source selectors."""

        return AccountAuthorityCurrentGraphReaderV3(
            actor_source_id=self._actor_source_id,
            actor_source_version=self._actor_source_version,
            actor_content_hash=self._actor_content_hash,
            physical_row_provider=self._physical_row_provider,
            using=self._using,
            transaction_mode="repeatable_read_read_only",
        )


class _CurrentEvidenceReader(CurrentOwnerAssignmentEvidenceV5Reader):
    """Adapt the existing Evidence V5 Application use case to the V3 port."""

    def __init__(self, use_case: GetCurrentAccountOwnerAssignmentEvidenceV5) -> None:
        """Bind one Application current-read use case."""

        self._use_case = use_case

    def execute(
        self,
        command: GetCurrentAccountOwnerAssignmentEvidenceV5Command,
    ) -> AccountOwnerAssignmentEvidenceV5 | None:
        """Execute current Evidence V5 validation without adding persistence rules."""

        return self._use_case.execute(command)


class _HistoricalEvidenceReader(HistoricalOwnerAssignmentEvidenceV5Reader):
    """Adapt the existing Evidence V5 historical-read use case to the V3 port."""

    def __init__(self, use_case: GetExactAccountOwnerAssignmentEvidenceV5) -> None:
        """Bind one Application exact-read use case."""

        self._use_case = use_case

    def execute(
        self,
        command: GetExactAccountOwnerAssignmentEvidenceV5Command,
    ) -> AccountOwnerAssignmentEvidenceV5 | None:
        """Execute exact Evidence V5 validation without adding persistence rules."""

        return self._use_case.execute(command)


def _build_evidence_readers(
    *,
    using: str,
    clock: _AuthorityGraphFrozenClock,
    policies: DjangoSingleOwnerAuthorityPolicyV1Repository,
    participants: CurrentSingleOwnerParticipantsProvider,
    subjects: DjangoAccountOwnerAssignmentSubjectV5Repository,
    evidence_repository: DjangoAccountOwnerAssignmentEvidenceV5Repository,
    physical_row_provider: ExactPhysicalSimulatedAccountRowV2Provider,
) -> tuple[
    DjangoAccountOwnerAssignmentEvidenceV5Repository,
    GetCurrentAccountOwnerAssignmentEvidenceV5,
    GetExactAccountOwnerAssignmentEvidenceV5,
]:
    """Compose existing Evidence V5 Application readers over same-alias repositories."""

    binding_repository = DjangoCanonicalAccountCreationConsumptionRepository(
        using=using,
        clock=clock,
    )
    physical_repository = DjangoPhysicalAccountRowObservationV2Repository(
        using=using,
        clock=clock,
    )
    binding_reader = GetExactCanonicalAccountCreationBindingV2(binding_repository)
    physical_reader = GetCurrentPhysicalAccountRowObservationV2(
        repository=physical_repository,
        row_provider=physical_row_provider,
    )
    reobservation_reader = GetCurrentCanonicalAccountOwnershipReobservationV1(
        repository=DjangoCanonicalAccountOwnershipReobservationV1Repository(
            using=using,
            clock=clock,
            binding_repository=binding_repository,
            physical_repository=physical_repository,
        ),
        current_physical_reader=physical_reader,
    )
    receipt_reader = GetCurrentAccountOwnerAssignmentProvenanceReceiptV5(
        repository=DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(
            using=using,
            clock=clock,
        ),
        binding_reader=binding_reader,
        policy_reader=policies,
        reobservation_reader=reobservation_reader,
    )
    subject_reader = GetCurrentAccountOwnerAssignmentSubjectV5(
        repository=subjects,
        current_receipt_reader=receipt_reader,
    )
    current_evidence = GetCurrentAccountOwnerAssignmentEvidenceV5(
        subject_reader=subject_reader,
        participants_reader=participants,
        repository=evidence_repository,
    )
    exact_evidence = GetExactAccountOwnerAssignmentEvidenceV5(evidence_repository)
    return evidence_repository, current_evidence, exact_evidence


def _read_database_clock_timestamp(
    connection: BaseDatabaseWrapper,
    using: str,
) -> datetime:
    """Read one aware PostgreSQL wall-clock timestamp on the caller's transaction."""

    if getattr(connection, "alias", None) != using or connection.vendor != "postgresql":
        raise AccountAuthorityGenerationUnavailable(
            "current graph cutoff requires its caller-owned PostgreSQL alias"
        )
    if not connection.in_atomic_block or connection.get_autocommit():
        raise AccountAuthorityGenerationUnavailable(
            "current graph cutoff requires an active caller-owned transaction"
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT clock_timestamp()")
            row = cast(tuple[object, ...] | None, cursor.fetchone())
    except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityGenerationUnavailable(
            "current graph database cutoff is unavailable"
        ) from error
    if row is None or len(row) != 1 or type(row[0]) is not datetime or not _is_aware(row[0]):
        raise AccountAuthorityGenerationUnavailable(
            "current graph database cutoff is not one aware timestamp"
        )
    return row[0]


def _is_aware(value: datetime) -> bool:
    """Return whether a datetime carries a usable UTC offset."""

    return value.tzinfo is not None and value.utcoffset() is not None


@contextmanager
def _read_only_repeatable_read_transaction(
    using: str,
    connection: BaseDatabaseWrapper,
) -> Iterator[None]:
    """Open the scanner's outermost same-alias PostgreSQL snapshot."""

    if getattr(connection, "alias", None) != using:
        raise AccountAuthorityGenerationUnavailable(
            "account authority shadow connection belongs to another database alias"
        )
    if connection.vendor != "postgresql":
        raise AccountAuthorityGenerationUnavailable(
            "account authority shadow scan requires PostgreSQL"
        )
    if connection.in_atomic_block or not connection.get_autocommit():
        raise AccountAuthorityGenerationUnavailable(
            "account authority shadow scan requires its own outer transaction"
        )
    try:
        with transaction.atomic(using=using):
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            _require_repeatable_read_only_connection(connection, using)
            yield
    except AccountAuthorityGenerationUnavailable:
        raise
    except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityGenerationUnavailable(
            "account authority shadow snapshot is unavailable"
        ) from error


def _require_repeatable_read_only_connection(
    connection: BaseDatabaseWrapper,
    using: str,
) -> None:
    """Require an active RR/READ ONLY transaction on the exact alias."""

    if getattr(connection, "alias", None) != using:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "authority no-lock snapshot connection alias differs"
        )
    if connection.vendor != "postgresql":
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "authority no-lock snapshot requires PostgreSQL"
        )
    if not connection.in_atomic_block or connection.get_autocommit():
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "authority no-lock snapshot requires an active transaction"
        )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('transaction_isolation'), "
                "current_setting('transaction_read_only')"
            )
            mode = cast(tuple[object, ...] | None, cursor.fetchone())
    except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "authority no-lock snapshot mode is unavailable"
        ) from error
    if mode != ("repeatable read", "on"):
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "authority no-lock snapshot requires repeatable read and read-only mode"
        )


def _require_caller_owned_transaction(
    connection: BaseDatabaseWrapper,
    using: str,
    transaction_mode: AccountAuthorityV3CallerTransactionMode,
) -> None:
    """Require an exact PostgreSQL alias and caller-owned transaction mode."""

    if getattr(connection, "alias", None) != using:
        raise AccountAuthorityGenerationUnavailable(
            "current graph connection belongs to another database alias"
        )
    if connection.vendor != "postgresql":
        raise AccountAuthorityGenerationUnavailable("current graph reader requires PostgreSQL")
    if not connection.in_atomic_block or connection.get_autocommit():
        raise AccountAuthorityGenerationUnavailable(
            "current graph reader requires an active caller-owned transaction"
        )
    expected_settings = {
        "repeatable_read_read_only": ("repeatable read", "on"),
        "generation_fenced_read_committed_read_write": ("read committed", "off"),
    }[transaction_mode]
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('transaction_isolation'), "
                "current_setting('transaction_read_only')"
            )
            mode = cast(tuple[object, ...] | None, cursor.fetchone())
    except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityGenerationUnavailable(
            "current graph transaction mode is unavailable"
        ) from error
    if mode != expected_settings:
        raise AccountAuthorityGenerationUnavailable(
            "current graph transaction mode differs from the requested mode"
        )


def _connection(using: str) -> BaseDatabaseWrapper:
    """Resolve one Django connection without falling back to another alias."""

    _require_alias(using)
    try:
        connection = connections[using]
    except (ConnectionDoesNotExist, KeyError) as error:
        raise AccountAuthorityGenerationUnavailable(
            "account authority shadow database alias is unavailable"
        ) from error
    if getattr(connection, "alias", None) != using:
        raise AccountAuthorityGenerationUnavailable(
            "account authority shadow connection alias differs"
        )
    return connection


def _compare_current_observations(
    legacy: CurrentOwnerTenantAuthorityV3 | None,
    shadow: CurrentOwnerTenantAuthorityV3 | None,
) -> AccountAuthorityShadowComparisonV3:
    """Compare only opaque identity hashes, content hashes, and expiry."""

    legacy_fingerprint = _fingerprint(legacy)
    shadow_fingerprint = _fingerprint(shadow)
    if legacy_fingerprint is None or shadow_fingerprint is None:
        differences: tuple[str, ...] = (
            () if legacy_fingerprint is shadow_fingerprint else ("availability",)
        )
    else:
        differences = tuple(
            field_name
            for field_name in (
                "authority_identity_hash",
                "authority_content_hash",
                "assignment_identity_hash",
                "assignment_content_hash",
                "policy_identity_hash",
                "policy_content_hash",
                "actor_source_identity_hash",
                "physical_source_identity_hash",
                "valid_until",
                "complete_graph_hash",
            )
            if getattr(legacy_fingerprint, field_name) != getattr(shadow_fingerprint, field_name)
        )
    return AccountAuthorityShadowComparisonV3(
        legacy=legacy_fingerprint,
        shadow=shadow_fingerprint,
        matches=not differences,
        differing_fields=differences,
    )


def _fingerprint(
    value: CurrentOwnerTenantAuthorityV3 | None,
) -> AccountAuthorityShadowFingerprintV3 | None:
    """Project one checked current result without exposing actor or account IDs."""

    if value is None:
        return None
    value.__post_init__()
    authority = value.authority
    assignment = authority.assignment
    policy = authority.policy
    physical = assignment.subject.reobservation.current_physical
    return AccountAuthorityShadowFingerprintV3(
        authority_identity_hash=authority.identity_hash,
        authority_content_hash=authority.content_hash,
        assignment_identity_hash=assignment.identity_hash,
        assignment_content_hash=assignment.content_hash,
        policy_identity_hash=policy.identity_hash,
        policy_content_hash=policy.content_hash,
        actor_source_identity_hash=_identity_digest(
            value.authentication.source_id,
            value.authentication.source_version,
            value.authentication.source_content_hash,
        ),
        physical_source_identity_hash=_identity_digest(
            physical.source_id,
            physical.source_version,
            physical.source_content_hash,
        ),
        valid_until=value.valid_until,
        complete_graph_hash=_complete_graph_digest(
            (authority, value.authentication, value.valid_until)
        ),
    )


def _complete_graph_digest(value: object) -> str:
    """Hash every stable dataclass field in a current graph without exposing it."""

    def normalize(item: object) -> object:
        if type(item) is datetime:
            if not _is_aware(item):
                raise ValueError("complete graph fingerprint contains a naive datetime")
            return {"datetime": item.astimezone(UTC).isoformat().replace("+00:00", "Z")}
        if is_dataclass(item) and not isinstance(item, type):
            return {field.name: normalize(getattr(item, field.name)) for field in fields(item)}
        if type(item) is tuple:
            return [normalize(value) for value in item]
        if item is None or type(item) in (str, int, bool):
            return item
        raise TypeError(f"complete graph fingerprint cannot normalize {type(item).__name__}")

    payload = json.dumps(
        normalize(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(
        b"account-authority-current-graph-v3\x00" + payload.encode("utf-8")
    ).hexdigest()


def _identity_digest(*values: str) -> str:
    """Hash a small ordered tuple of identity selectors before comparison."""

    return hashlib.sha256("\x00".join(values).encode("utf-8")).hexdigest()


def _require_alias(value: object) -> None:
    """Require one exact database alias token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError("using must be one exact database alias")


def _require_token(value: object, name: str) -> None:
    """Require one bounded canonical source selector token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _require_hash(value: object, name: str) -> None:
    """Require one complete lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _validate_transaction_mode(value: object) -> AccountAuthorityV3CallerTransactionMode:
    """Return one exact supported caller transaction mode token."""

    if type(value) is not str or value not in (
        "repeatable_read_read_only",
        "generation_fenced_read_committed_read_write",
    ):
        raise ValueError("transaction_mode must be an exact supported mode token")
    return cast(AccountAuthorityV3CallerTransactionMode, value)


__all__ = [
    "AccountAuthorityCurrentGraphReadV3",
    "AccountAuthorityCurrentGraphReaderV3",
    "AccountAuthorityCurrentGraphSelectorV3",
    "AccountAuthorityShadowComparisonV3",
    "AccountAuthorityShadowFingerprintV3",
    "AccountAuthorityShadowScanResultV3",
    "AccountAuthorityShadowScannerV3",
    "AccountAuthorityV3CallerTransactionMode",
    "DjangoAccountAuthorityNoLockSnapshotBundleProviderV3",
]
