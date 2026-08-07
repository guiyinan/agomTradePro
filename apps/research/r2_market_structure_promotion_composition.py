"""Concrete composition for Research-owned R2 promotion persistence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime

from apps.data_center.application.market_structure import ReadMarketStructureEvidence
from apps.data_center.domain.market_structure import ImmutableMarketStructureEvidence
from apps.data_center.infrastructure.market_structure_publication import (
    DjangoMarketStructurePublicationGate,
)
from apps.data_center.infrastructure.market_structure_repository import (
    MarketStructureResearchRepository,
)
from apps.research.application.r2_market_structure_promotion import (
    ApplyR2MarketStructurePromotionLifecycle,
    EvaluateR2MarketStructurePromotion,
    ExactR2MarketStructureDecisionAuthorizationSource,
    ExactR2MarketStructureEvidenceProvider,
    ExactR2MarketStructureLifecycleAuthorizationSource,
    ExactR2MarketStructurePromotionPolicySource,
    GetActiveR2MarketStructurePromotion,
    R2MarketStructurePolicyRegistrationWriter,
    R2MarketStructurePromotionClock,
    R2MarketStructurePromotionRepository,
    RegisterR2MarketStructurePromotionPolicy,
)
from apps.research.domain.r2_market_structure_promotion import (
    R2MarketStructureLifecycleEvent,
    R2MarketStructurePromotionDecision,
    R2MarketStructurePromotionPolicy,
    R2MarketStructurePromotionRef,
)
from apps.research.infrastructure.r2_market_structure_promotion_repository import (
    DjangoR2MarketStructurePromotionClock,
    DjangoR2MarketStructurePromotionRepository,
)


class DjangoExactR2MarketStructureEvidenceProvider:
    """Data Center Application adapter with full Publication revalidation."""

    def __init__(self, *, using: str = "default") -> None:
        if using != "default":
            raise ValueError(
                "default R2 Data Center evidence provider supports only the default database"
            )
        repository = MarketStructureResearchRepository()
        self._reader = ReadMarketStructureEvidence(repository)
        self._publication_gate = DjangoMarketStructurePublicationGate()
        self._unit_of_work_key = f"django:{using}"

    @property
    def unit_of_work_key(self) -> str:
        return self._unit_of_work_key

    def get_exact(
        self,
        evidence_ref: R2MarketStructurePromotionRef,
        *,
        as_of: datetime,
    ) -> ImmutableMarketStructureEvidence | None:
        """Return an exact evidence body after replaying every Publication proof."""

        try:
            version = int(evidence_ref.version)
        except ValueError:
            return None
        evidence = self._reader.execute_at(
            evidence_key=evidence_ref.stable_id,
            evidence_version=version,
            as_of_time=as_of,
        )
        if evidence is None:
            return None
        for attestation in evidence.governance_publications:
            if not self._publication_gate.verify_attestation(
                attestation,
                as_of_time=evidence.as_of_time,
            ):
                return None
        return evidence


class _RepositoryPort(R2MarketStructurePromotionRepository):
    """Application port that keeps payload append methods non-public on storage."""

    def __init__(self, repository: DjangoR2MarketStructurePromotionRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        return self._repository.unit_of_work_key

    def atomic(self) -> AbstractContextManager[None]:
        return self._repository.atomic()

    def get_policy(
        self,
        policy_ref: R2MarketStructurePromotionRef,
        *,
        as_of: datetime,
    ) -> R2MarketStructurePromotionPolicy | None:
        return self._repository.get_policy(policy_ref, as_of=as_of)

    def append_decision(
        self,
        decision: R2MarketStructurePromotionDecision,
    ) -> R2MarketStructurePromotionDecision:
        return self._repository._append_decision(decision)

    def get_decision(
        self,
        decision_ref: R2MarketStructurePromotionRef,
        *,
        as_of: datetime,
    ) -> R2MarketStructurePromotionDecision | None:
        return self._repository.get_decision(decision_ref, as_of=as_of)

    def append_lifecycle_event(
        self,
        event: R2MarketStructureLifecycleEvent,
    ) -> R2MarketStructureLifecycleEvent:
        return self._repository._append_lifecycle_event(event)

    def load_lifecycle_stream(
        self,
        scope_id: str,
    ) -> tuple[R2MarketStructureLifecycleEvent, ...]:
        return self._repository.load_lifecycle_stream(scope_id)

    def get_event_by_authorization(
        self,
        authorization_ref: R2MarketStructurePromotionRef,
    ) -> R2MarketStructureLifecycleEvent | None:
        return self._repository.get_event_by_authorization(authorization_ref)


@dataclass(frozen=True)
class DjangoR2MarketStructurePromotionRuntime:
    """R2 policy, decision, lifecycle and active-provider runtime."""

    register_policy: RegisterR2MarketStructurePromotionPolicy
    evaluate: EvaluateR2MarketStructurePromotion
    apply_lifecycle: ApplyR2MarketStructurePromotionLifecycle
    get_active: GetActiveR2MarketStructurePromotion


def build_django_r2_market_structure_promotion_runtime(
    *,
    policy_source: ExactR2MarketStructurePromotionPolicySource,
    decision_authorization_source: ExactR2MarketStructureDecisionAuthorizationSource,
    lifecycle_authorization_source: ExactR2MarketStructureLifecycleAuthorizationSource,
    evidence_provider: ExactR2MarketStructureEvidenceProvider | None = None,
    clock: R2MarketStructurePromotionClock | None = None,
    using: str = "default",
) -> DjangoR2MarketStructurePromotionRuntime:
    """Wire ID-only use cases without a production policy/authorization default."""

    server_clock = clock or DjangoR2MarketStructurePromotionClock()
    owner_evidence = evidence_provider or DjangoExactR2MarketStructureEvidenceProvider(using=using)
    repository = DjangoR2MarketStructurePromotionRepository(
        clock=server_clock,
        using=using,
    )
    port = _RepositoryPort(repository)
    unit_of_work_keys = {
        repository.unit_of_work_key,
        policy_source.unit_of_work_key,
        owner_evidence.unit_of_work_key,
        decision_authorization_source.unit_of_work_key,
        lifecycle_authorization_source.unit_of_work_key,
    }
    if len(unit_of_work_keys) != 1:
        raise ValueError("R2 promotion owner graph must share one unit of work")

    class PolicyWriter(R2MarketStructurePolicyRegistrationWriter):
        def register(
            self,
            policy_ref: R2MarketStructurePromotionRef,
        ) -> R2MarketStructurePromotionPolicy:
            now = server_clock.now()
            with repository.atomic():
                policy = policy_source.get_exact(policy_ref, as_of=now)
                if policy is None:
                    raise ValueError("exact R2 owner policy is unavailable")
                return repository._append_policy(policy)

    return DjangoR2MarketStructurePromotionRuntime(
        register_policy=RegisterR2MarketStructurePromotionPolicy(PolicyWriter()),
        evaluate=EvaluateR2MarketStructurePromotion(
            policy_source=policy_source,
            evidence_provider=owner_evidence,
            authorization_source=decision_authorization_source,
            repository=port,
            clock=server_clock,
        ),
        apply_lifecycle=ApplyR2MarketStructurePromotionLifecycle(
            authorization_source=lifecycle_authorization_source,
            repository=port,
            clock=server_clock,
        ),
        get_active=GetActiveR2MarketStructurePromotion(
            policy_source=policy_source,
            evidence_provider=owner_evidence,
            decision_authorization_source=decision_authorization_source,
            lifecycle_authorization_source=lifecycle_authorization_source,
            repository=port,
            clock=server_clock,
        ),
    )


__all__ = [
    "DjangoExactR2MarketStructureEvidenceProvider",
    "DjangoR2MarketStructurePromotionRuntime",
    "build_django_r2_market_structure_promotion_runtime",
]
