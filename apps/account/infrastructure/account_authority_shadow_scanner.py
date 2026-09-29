"""Read-only generation-bound shadow scan for System Audit authority V3."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

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
from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationProof,
    AccountAuthorityGenerationUnavailable,
    read_account_authority_generation_proof,
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
from apps.account.infrastructure.owner_tenant_authority_v3_read_context import (
    OwnerTenantAuthorityV3OperationReadContext,
)
from apps.account.infrastructure.owner_tenant_authority_v3_repository import (
    DjangoOwnerTenantAuthorityV3Repository,
)
from apps.account.infrastructure.physical_account_row_observation_v2_repository import (
    DjangoPhysicalAccountRowObservationV2Repository,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from shared.infrastructure.immutable_read_snapshot import suspend_immutable_read_reuse


class DjangoAccountAuthorityNoLockSnapshotBundleProviderV3(
    DjangoAccountActorAuthorityInputBundleProviderV3
):
    """Read actor inputs inside a caller-owned RR/READ ONLY snapshot without locks."""

    def _snapshot(self, connection: BaseDatabaseWrapper) -> AbstractContextManager[None]:
        """Require the scanner's exact transaction and return a no-op scope."""

        _require_repeatable_read_only_connection(connection, self._using)
        return nullcontext()


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


@dataclass(frozen=True, slots=True)
class AccountAuthorityShadowComparisonV3:
    """Compare only redacted hashes and the effective expiry boundary."""

    legacy: AccountAuthorityShadowFingerprintV3 | None
    shadow: AccountAuthorityShadowFingerprintV3 | None
    matches: bool
    differing_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AccountAuthorityShadowScanResultV3:
    """Bind the observed generation and comparison to the database alias."""

    database_alias: str
    proof_generation: int
    comparison: AccountAuthorityShadowComparisonV3


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
        """Bind fixed source selectors and a declared physical-provider alias.

        ``unit_of_work_key`` is a trusted composition contract. This scanner can
        verify the declared alias, but cannot prove that a provider does not
        spoof that key or use a different physical connection. Keep this scanner
        outside the production decision path until provider connection identity
        can be enforced.
        """

        _require_alias(using)
        for name, value in (
            ("actor_source_id", actor_source_id),
            ("actor_source_version", actor_source_version),
        ):
            _require_token(value, name)
        _require_hash(actor_content_hash, "actor_content_hash")
        if getattr(physical_row_provider, "unit_of_work_key", None) != f"django:{using}":
            raise ValueError("physical row provider must use the shadow scan database alias")
        if not callable(getattr(physical_row_provider, "get_exact_current", None)):
            raise TypeError("physical row provider must expose get_exact_current")
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
                shadow_current = self._read_shadow(command)
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
        )

    def _read_shadow(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> CurrentOwnerTenantAuthorityV3 | None:
        """Restore current authority with the existing Application service graph."""

        connection = _connection(self._using)
        _require_repeatable_read_only_connection(connection, self._using)

        authority_repository = DjangoOwnerTenantAuthorityV3Repository(using=self._using)
        provisional = authority_repository.get_winner(
            authority_id=command.authority_id,
            authority_version=command.authority_version,
            as_of=authority_repository.now(),
        )
        if provisional is None:
            return None

        actor_repository = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(
            using=self._using
        )
        actor_current_reader = GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3(
            input_bundle_provider=DjangoAccountAuthorityNoLockSnapshotBundleProviderV3(
                using=self._using
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
        policies = DjangoSingleOwnerAuthorityPolicyV1Repository(using=self._using)
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

        read_context = OwnerTenantAuthorityV3OperationReadContext(
            using=self._using,
            connection_provider=lambda: connections[self._using].connection,
        )
        evidence_repository, current_evidence, exact_evidence = _build_evidence_readers(
            using=self._using,
            actors=actor_repository,
            policies=policies,
            participants=participants,
            physical_row_provider=self._physical_row_provider,
            read_context=read_context,
        )
        service = OwnerTenantAuthorityV3Service(
            repository=DjangoOwnerTenantAuthorityV3Repository(
                using=self._using,
                assignments=evidence_repository,
                policies=policies,
                actors=actor_repository,
            ),
            current_assignments=_CurrentEvidenceReader(current_evidence),
            historical_assignments=_HistoricalEvidenceReader(exact_evidence),
            participants=participants,
            validity_period=timedelta(seconds=1),
            read_phase=read_context.phase,
        )
        return service.get_current(command)


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
    actors: DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
    policies: DjangoSingleOwnerAuthorityPolicyV1Repository,
    participants: CurrentSingleOwnerParticipantsProvider,
    physical_row_provider: ExactPhysicalSimulatedAccountRowV2Provider,
    read_context: OwnerTenantAuthorityV3OperationReadContext,
) -> tuple[
    DjangoAccountOwnerAssignmentEvidenceV5Repository,
    GetCurrentAccountOwnerAssignmentEvidenceV5,
    GetExactAccountOwnerAssignmentEvidenceV5,
]:
    """Compose existing Evidence V5 Application readers over same-alias repositories."""

    binding_reader = GetExactCanonicalAccountCreationBindingV2(
        DjangoCanonicalAccountCreationConsumptionRepository(using=using)
    )
    physical_reader = GetCurrentPhysicalAccountRowObservationV2(
        repository=DjangoPhysicalAccountRowObservationV2Repository(using=using),
        row_provider=physical_row_provider,
    )
    reobservation_reader = GetCurrentCanonicalAccountOwnershipReobservationV1(
        repository=DjangoCanonicalAccountOwnershipReobservationV1Repository(using=using),
        current_physical_reader=physical_reader,
    )
    receipt_reader = GetCurrentAccountOwnerAssignmentProvenanceReceiptV5(
        repository=DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(using=using),
        binding_reader=binding_reader,
        policy_reader=policies,
        reobservation_reader=reobservation_reader,
    )
    subjects = DjangoAccountOwnerAssignmentSubjectV5Repository(using=using)
    subject_reader = GetCurrentAccountOwnerAssignmentSubjectV5(
        repository=subjects,
        current_receipt_reader=receipt_reader,
    )
    evidence_repository = DjangoAccountOwnerAssignmentEvidenceV5Repository(
        using=using,
        subjects=subjects,
        actors=actors,
        read_context=read_context,
    )
    current_evidence = GetCurrentAccountOwnerAssignmentEvidenceV5(
        subject_reader=subject_reader,
        participants_reader=participants,
        repository=evidence_repository,
    )
    exact_evidence = GetExactAccountOwnerAssignmentEvidenceV5(evidence_repository)
    return evidence_repository, current_evidence, exact_evidence


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
    )


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


__all__ = [
    "AccountAuthorityShadowComparisonV3",
    "AccountAuthorityShadowFingerprintV3",
    "AccountAuthorityShadowScanResultV3",
    "AccountAuthorityShadowScannerV3",
    "DjangoAccountAuthorityNoLockSnapshotBundleProviderV3",
]
