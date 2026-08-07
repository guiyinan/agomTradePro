"""Composition root for persisted approved R7 sample policy research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError

from apps.research.application.r7_sample_policy import (
    ExactR7SamplePolicyAuthorizationProvider,
    ExactR7SamplePolicyDefinitionProvider,
    GetExactR7SamplePolicy,
    R7SamplePolicyConflict,
    R7SamplePolicyOwnerApproval,
    R7SamplePolicyUnavailable,
    RegisterR7SamplePolicy,
    RegisterR7SamplePolicyCommand,
)
from apps.research.application.scenario_probability_research import (
    BuildScenarioProbabilityResearchPacketUseCase,
    HistoricalAnalogyEvidenceProvider,
    ScenarioForecastOutcomeEvidenceProvider,
    ScenarioPathEvidenceProvider,
)
from apps.research.domain.r7_sample_policy import (
    PersistedR7SamplePolicy,
    R7SamplePolicyAuthorization,
    r7_sample_policy_definition_hash,
)
from apps.research.infrastructure.r7_sample_policy_repository import (
    DjangoR7SamplePolicyAuthorizationProvider,
    DjangoR7SamplePolicyClock,
    DjangoR7SamplePolicyProvider,
    DjangoR7SamplePolicyRepository,
    R7SamplePolicyClock,
    _DjangoR7SamplePolicyStore,
)


class _R7SamplePolicyRegistrationWriter:
    """Private ID-only writer that rereads both owners inside one UoW."""

    def __init__(
        self,
        *,
        definition_provider: ExactR7SamplePolicyDefinitionProvider,
        authorization_provider: ExactR7SamplePolicyAuthorizationProvider,
        store: _DjangoR7SamplePolicyStore,
        clock: R7SamplePolicyClock,
    ) -> None:
        self._definition_provider = definition_provider
        self._authorization_provider = authorization_provider
        self._store = store
        self._clock = clock
        if authorization_provider.unit_of_work_key != store.unit_of_work_key:
            raise ValueError("R7 owner authorization provider uses a different unit of work")

    def register(
        self,
        command: RegisterR7SamplePolicyCommand,
    ) -> PersistedR7SamplePolicy:
        """Resolve IDs, discard self-attested approver, and append atomically."""

        try:
            with self._store.atomic():
                recorded_at = self._clock.now()
                if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
                    raise ValueError("R7 sample policy server clock must be timezone-aware")
                if command.as_of > recorded_at:
                    raise ValueError("future R7 sample policy registration cutoff")
                draft = self._definition_provider.get_exact(
                    policy_id=command.policy_id,
                    policy_version=command.policy_version,
                    as_of=command.as_of,
                )
                if draft is None:
                    raise ValueError("exact R7 sample policy definition is unavailable")
                if (
                    draft.policy_id != command.policy_id
                    or draft.policy_version != command.policy_version
                ):
                    raise ValueError("R7 sample policy definition substitution")
                definition_hash = r7_sample_policy_definition_hash(
                    scope=draft.scope,
                    policy=draft.policy_definition,
                )
                owner_approval = self._authorization_provider.get_exact(
                    authorization_id=command.authorization_id,
                    authorization_version=command.authorization_version,
                    policy_id=command.policy_id,
                    policy_version=command.policy_version,
                    scope_content_hash=draft.scope.content_hash,
                    policy_definition_hash=definition_hash,
                    # Owner authority is reread at the Research server clock;
                    # a caller PIT cannot backdate a newly registered approval.
                    as_of=recorded_at,
                )
                if owner_approval is None:
                    raise R7SamplePolicyUnavailable(
                        "Risk Center owner approval evidence is unavailable"
                    )
                if (
                    owner_approval.authorization_id != command.authorization_id
                    or owner_approval.authorization_version != command.authorization_version
                    or owner_approval.policy_id != command.policy_id
                    or owner_approval.policy_version != command.policy_version
                    or owner_approval.scope_content_hash != draft.scope.content_hash
                    or owner_approval.policy_definition_hash != definition_hash
                    or not owner_approval.issued_at <= command.as_of < owner_approval.valid_until
                    or not owner_approval.issued_at <= recorded_at < owner_approval.valid_until
                ):
                    raise ValueError("R7 owner authorization substitution or stale receipt")
                authorization = R7SamplePolicyAuthorization.create(
                    authorization_id=owner_approval.authorization_id,
                    authorization_version=owner_approval.authorization_version,
                    owner_record_id=owner_approval.owner_record_id,
                    owner_record_version=owner_approval.owner_record_version,
                    owner_record_hash=owner_approval.owner_record_hash,
                    policy_id=command.policy_id,
                    policy_version=command.policy_version,
                    scope_content_hash=draft.scope.content_hash,
                    policy_definition_hash=definition_hash,
                    approved_by=owner_approval.approved_by,
                    issued_at=owner_approval.issued_at,
                    valid_until=owner_approval.valid_until,
                )
                record = PersistedR7SamplePolicy.create(
                    policy_id=command.policy_id,
                    policy_version=command.policy_version,
                    scope=draft.scope,
                    policy_definition=draft.policy_definition,
                    authorization=authorization,
                    recorded_at=recorded_at,
                )
                return self._store.append(record)
        except IntegrityError as exc:
            raise R7SamplePolicyConflict("R7 sample policy race lost") from exc


@dataclass(frozen=True)
class DjangoR7SamplePolicyRuntime:
    """Safe public capabilities for approved R7 policy registration/query."""

    register: RegisterR7SamplePolicy
    get_exact: GetExactR7SamplePolicy
    repository: DjangoR7SamplePolicyRepository
    policy_provider: DjangoR7SamplePolicyProvider


def build_django_r7_sample_policy_runtime(
    *,
    definition_provider: ExactR7SamplePolicyDefinitionProvider,
    using: str = "default",
    clock: R7SamplePolicyClock | None = None,
) -> DjangoR7SamplePolicyRuntime:
    """Build a production runtime that fails closed until Risk Center evidence exists."""

    return _build_r7_sample_policy_runtime(
        definition_provider=definition_provider,
        authorization_provider=_UnavailableR7SamplePolicyAuthorizationProvider(using=using),
        using=using,
        clock=clock,
    )


def _build_django_r7_sample_policy_test_runtime(
    *,
    definition_provider: ExactR7SamplePolicyDefinitionProvider,
    authorization_provider: DjangoR7SamplePolicyAuthorizationProvider,
    using: str = "default",
    clock: R7SamplePolicyClock | None = None,
) -> DjangoR7SamplePolicyRuntime:
    """Test-only composition hook for injecting an owner projection fake."""

    return _build_r7_sample_policy_runtime(
        definition_provider=definition_provider,
        authorization_provider=authorization_provider,
        using=using,
        clock=clock,
    )


class _UnavailableR7SamplePolicyAuthorizationProvider:
    """Production owner port until Risk Center supplies an immutable audit query."""

    def __init__(self, *, using: str) -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        authorization_id: str,
        authorization_version: str,
        policy_id: str,
        policy_version: str,
        scope_content_hash: str,
        policy_definition_hash: str,
        as_of: datetime,
    ) -> R7SamplePolicyOwnerApproval | None:
        """Never invent owner approval while the canonical source is absent."""

        return None


def _build_r7_sample_policy_runtime(
    *,
    definition_provider: ExactR7SamplePolicyDefinitionProvider,
    authorization_provider: ExactR7SamplePolicyAuthorizationProvider,
    using: str,
    clock: R7SamplePolicyClock | None,
) -> DjangoR7SamplePolicyRuntime:
    """Assemble shared runtime capabilities for production and test composition."""

    authoritative_clock = clock or DjangoR7SamplePolicyClock()
    repository = DjangoR7SamplePolicyRepository(
        using=using,
        clock=authoritative_clock,
    )
    store = _DjangoR7SamplePolicyStore(using=using)
    if authorization_provider.unit_of_work_key != store.unit_of_work_key:
        raise ValueError("R7 owner authorization provider uses a different unit of work")
    writer = _R7SamplePolicyRegistrationWriter(
        definition_provider=definition_provider,
        authorization_provider=authorization_provider,
        store=store,
        clock=authoritative_clock,
    )
    provider = DjangoR7SamplePolicyProvider(repository)
    return DjangoR7SamplePolicyRuntime(
        register=RegisterR7SamplePolicy(writer),
        get_exact=GetExactR7SamplePolicy(repository),
        repository=repository,
        policy_provider=provider,
    )


def build_persisted_scenario_probability_research_use_case(
    *,
    policy_repository: DjangoR7SamplePolicyRepository,
    forecast_evidence_provider: ScenarioForecastOutcomeEvidenceProvider,
    historical_analogy_provider: HistoricalAnalogyEvidenceProvider,
    path_evidence_provider: ScenarioPathEvidenceProvider,
) -> BuildScenarioProbabilityResearchPacketUseCase:
    """Wire production packet construction to persisted policy evidence only."""

    return BuildScenarioProbabilityResearchPacketUseCase(
        policy_provider=DjangoR7SamplePolicyProvider(policy_repository),
        forecast_evidence_provider=forecast_evidence_provider,
        historical_analogy_provider=historical_analogy_provider,
        path_evidence_provider=path_evidence_provider,
    )


__all__ = [
    "DjangoR7SamplePolicyRuntime",
    "build_django_r7_sample_policy_runtime",
    "build_persisted_scenario_probability_research_use_case",
]
