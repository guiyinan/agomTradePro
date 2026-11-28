"""Production-inert composition for the Research R2 trial-policy registry."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.db import transaction

from apps.data_center.application.control_plane import CanonicalPublicationRepositoryPort
from apps.data_center.application.publication_utils import member_reference, publication_hash
from apps.data_center.domain.control_plane import PublicationFactReference, PublicationState
from apps.research.application.r2_market_structure_trial_policy_registry import (
    ExactR2TrialPolicyDefinitionProvider,
    R2TrialPolicyRegistryClock,
    R2TrialPolicyRegistryUnavailable,
    RegisterR2MarketStructureTrialPolicy,
    RegisterR2MarketStructureTrialPolicyCommand,
)
from apps.research.domain.r2_market_structure_trial_contracts import (
    R2MarketStructureTrialPolicy,
    R2PublicationProjectionSeal,
    R2PublicationRef,
)
from apps.research.domain.r2_market_structure_trial_policy_registry import (
    PersistedR2MarketStructureTrialPolicy,
)
from apps.research.infrastructure.r2_market_structure_trial_monitoring_codec import (
    decode_r2_trial_policy,
)
from apps.research.infrastructure.r2_market_structure_trial_policy_repository import (
    DjangoExactR2TrialPolicyProvider,
    DjangoR2TrialPolicyDefinitionProvider,
    DjangoR2TrialPolicyRegistryClock,
    DjangoR2TrialPolicyRegistryRepository,
    _DjangoR2TrialPolicyRegistryStore,
)


class _UnavailableR2TrialPolicyRegistrationFacade:
    """State-free public writer while no canonical definition owner is composed."""

    __slots__ = ()

    def execute(
        self,
        command: RegisterR2MarketStructureTrialPolicyCommand,
    ) -> PersistedR2MarketStructureTrialPolicy:
        """Validate the ID-only selector, then fail without constructing a store."""

        try:
            if type(command) is not RegisterR2MarketStructureTrialPolicyCommand:
                raise TypeError("R2 policy registration command type differs")
            RegisterR2MarketStructureTrialPolicyCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R2TrialPolicyRegistryUnavailable(
                "R2 trial-policy registration command is invalid"
            ) from error
        raise R2TrialPolicyRegistryUnavailable(
            "R2 trial-policy canonical definition provider is unavailable"
        )


@dataclass(frozen=True, slots=True)
class R2RehearsalRelease:
    """Operator-pinned owner file and independently read projections for a local rehearsal."""

    definition_path: Path
    definition_sha256: str
    taxonomy: R2PublicationProjectionSeal
    calendar: R2PublicationProjectionSeal

    @classmethod
    def from_candidate(
        cls,
        repository: CanonicalPublicationRepositoryPort,
        *,
        publication_id: str,
        expected_hash: str,
        definition_path: Path,
        definition_sha256: str,
    ) -> R2RehearsalRelease:
        """Read both projections from one exact, restricted Data Center candidate."""
        root = repository.get_by_id(publication_id)
        if (
            root is None
            or root.publication_id != publication_id
            or root.publication_hash != expected_hash
            or root.dataset_key != "research.market_structure_rehearsal.v1"
            or root.state is not PublicationState.CANDIDATE
            or not root.must_not_use_for_decision
            or root.as_of is None
            or root.published_at is not None
        ):
            raise R2TrialPolicyRegistryUnavailable("R2 rehearsal candidate identity differs")
        members = repository.list_members(publication_id)
        coverage = root.coverage
        if (
            coverage.publication_id != publication_id
            or coverage.requested_count != coverage.selected_count
            or coverage.selected_count != root.member_count
            or root.member_count != len(members)
            or coverage.missing_count
            or coverage.conflict_count
            or root.conflict_count
        ):
            raise R2TrialPolicyRegistryUnavailable("R2 rehearsal candidate coverage differs")
        roles = {
            "asset_group": "data_center_asset_group_revision",
            "member": "data_center_pit_fact_version",
            "actor": "data_center_investor_actor_definition",
            "flow": "data_center_investor_flow_definition",
            "series": "data_center_market_structure_series",
            "observation": "data_center_pit_fact_version",
            "calendar": "data_center_market_structure_period_calendar",
        }
        by_role: dict[str, set[str]] = {role: set() for role in roles}
        references: list[PublicationFactReference] = []
        calendar: list[PublicationFactReference] = []
        taxonomy: list[PublicationFactReference] = []
        for member in sorted(members, key=lambda row: row.natural_key):
            role, _, code = member.natural_key.partition(":")
            if (
                member.publication_id != publication_id
                or member.dataset_key != root.dataset_key
                or roles.get(role) != member.fact_table
                or not code
                or code in by_role[role]
                or member.quality_status != "accepted"
                or member.observed_at is None
                or member.observed_at > root.as_of
            ):
                raise R2TrialPolicyRegistryUnavailable("R2 rehearsal member identity differs")
            by_role[role].add(code)
            reference = member_reference(member)
            references.append(reference)
            (calendar if role == "calendar" else taxonomy).append(reference)
        if (
            not all(by_role.values())
            or len(by_role["asset_group"]) != 1
            or len(calendar) != 1
            or by_role["member"] != by_role["observation"]
            or publication_hash(references) != expected_hash
        ):
            raise R2TrialPolicyRegistryUnavailable("R2 rehearsal member snapshot differs")
        version, as_of = root.policy_version, root.as_of

        def seal(items: list[PublicationFactReference]) -> R2PublicationProjectionSeal:
            digest = publication_hash(items)
            ref = R2PublicationRef("data_center", publication_id, version, expected_hash, digest)
            return R2PublicationProjectionSeal(ref, digest, as_of, as_of)

        return cls(definition_path, definition_sha256, seal(taxonomy), seal(calendar))

    def __post_init__(self) -> None:
        taxonomy = self.taxonomy.reference
        calendar = self.calendar.reference
        if (
            taxonomy.owner,
            taxonomy.publication_id,
            taxonomy.publication_version,
            taxonomy.publication_hash,
        ) != (
            calendar.owner,
            calendar.publication_id,
            calendar.publication_version,
            calendar.publication_hash,
        ):
            raise R2TrialPolicyRegistryUnavailable("R2 projections belong to different releases")


@dataclass(frozen=True, slots=True)
class _RehearsalDefinitionReader:
    release: R2RehearsalRelease
    unit_of_work_key: str

    def get_exact(
        self, *, policy_id: str, policy_version: str, as_of: datetime
    ) -> R2MarketStructureTrialPolicy | None:
        """Reread pinned owner bytes and match both independent release projections."""
        try:
            raw = self.release.definition_path.read_bytes()
        except OSError as error:
            raise R2TrialPolicyRegistryUnavailable("R2 owner file is unavailable") from error
        if hashlib.sha256(raw).hexdigest() != self.release.definition_sha256:
            raise R2TrialPolicyRegistryUnavailable("R2 owner file digest differs")
        try:
            policy = decode_r2_trial_policy(json.loads(raw))
        except ValueError as error:
            raise R2TrialPolicyRegistryUnavailable(
                "canonical R2 policy body is unavailable"
            ) from error
        if (policy.policy_id, policy.policy_version) != (policy_id, policy_version):
            return None
        if policy.registered_at > as_of:
            return None
        if (
            policy.taxonomy_projection_seal != self.release.taxonomy
            or policy.calendar_projection_seal != self.release.calendar
        ):
            raise R2TrialPolicyRegistryUnavailable(
                "R2 owner policy projection differs from release"
            )
        return policy


@dataclass(frozen=True, slots=True)
class DjangoR2TrialPolicyRegistryRuntime:
    """Inert production registration plus exact read-only provider capability."""

    register: _UnavailableR2TrialPolicyRegistrationFacade
    provider: DjangoExactR2TrialPolicyProvider
    using: str = "default"

    def rehearse(
        self, command: RegisterR2MarketStructureTrialPolicyCommand, release: R2RehearsalRelease
    ) -> PersistedR2MarketStructureTrialPolicy:
        """Exercise both owner reads and the real ledger append inside a rollback-only savepoint."""
        clock = DjangoR2TrialPolicyRegistryClock(using=self.using)
        owner = _RehearsalDefinitionReader(release, clock.unit_of_work_key)
        registration = RegisterR2MarketStructureTrialPolicy(
            definition_provider=DjangoR2TrialPolicyDefinitionProvider(owner),
            store=_DjangoR2TrialPolicyRegistryStore(using=self.using),
            clock=clock,
        )
        with transaction.atomic(using=self.using):
            result = registration.execute(command)
            transaction.set_rollback(True, using=self.using)
        return result


@dataclass(frozen=True, slots=True)
class _DjangoR2TrialPolicyRegistryTestRuntime:
    """Private injectable runtime reserved for component tests."""

    register: RegisterR2MarketStructureTrialPolicy
    provider: DjangoExactR2TrialPolicyProvider
    repository: DjangoR2TrialPolicyRegistryRepository


def build_django_r2_trial_policy_registry_runtime(
    *,
    using: str = "default",
) -> DjangoR2TrialPolicyRegistryRuntime:
    """Build a public object graph with no writer store or owner dependency."""

    repository = DjangoR2TrialPolicyRegistryRepository(using=using)
    return DjangoR2TrialPolicyRegistryRuntime(
        register=_UnavailableR2TrialPolicyRegistrationFacade(),
        provider=DjangoExactR2TrialPolicyProvider(repository),
        using=using,
    )


def _build_django_r2_trial_policy_registry_test_runtime(
    *,
    definition_provider: ExactR2TrialPolicyDefinitionProvider,
    using: str = "default",
    clock: R2TrialPolicyRegistryClock | None = None,
) -> _DjangoR2TrialPolicyRegistryTestRuntime:
    """Build the private same-UoW writer graph for synthetic component tests."""

    trusted_clock = clock or DjangoR2TrialPolicyRegistryClock(using=using)
    repository = DjangoR2TrialPolicyRegistryRepository(
        using=using,
        clock=trusted_clock,
    )
    owner = DjangoR2TrialPolicyDefinitionProvider(definition_provider)
    store = _DjangoR2TrialPolicyRegistryStore(using=using)
    keys = {
        owner.unit_of_work_key,
        store.unit_of_work_key,
        trusted_clock.unit_of_work_key,
        repository.unit_of_work_key,
    }
    if len(keys) != 1:
        raise R2TrialPolicyRegistryUnavailable(
            "R2 trial-policy runtime requires one shared unit of work"
        )
    return _DjangoR2TrialPolicyRegistryTestRuntime(
        register=RegisterR2MarketStructureTrialPolicy(
            definition_provider=owner,
            store=store,
            clock=trusted_clock,
        ),
        provider=DjangoExactR2TrialPolicyProvider(repository),
        repository=repository,
    )


__all__ = [
    "DjangoR2TrialPolicyRegistryRuntime",
    "R2RehearsalRelease",
    "build_django_r2_trial_policy_registry_runtime",
]
