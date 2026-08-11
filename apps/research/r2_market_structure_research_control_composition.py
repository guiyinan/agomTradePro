"""Production read-only composition for the R2 research-control preflight."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.research.application.r2_market_structure_research_control_preflight import (
    EvaluateR2ResearchControlPreflight,
)
from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2AuditExplanatoryOutcome,
    R2CanonicalPublicationEvidence,
    R2CyclePITEvidence,
    R2EvidenceRef,
    R2MonitoringRawFact,
    R2PublicationKind,
    R2PublicationRef,
)
from apps.research.infrastructure.r2_market_structure_research_control_repository import (
    DjangoR2ResearchControlReadRepository,
)
from apps.research.r2_market_structure_trial_policy_composition import (
    build_django_r2_trial_policy_registry_runtime,
)


class _UnavailableR2PublicationProvider:
    """Explicit absence until Data Center exposes the complete R2 projection."""

    __slots__ = ("_key",)

    def __init__(self, key: str) -> None:
        self._key = key

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

        return self._key

    def get_exact(
        self,
        *,
        kind: R2PublicationKind,
        reference: R2PublicationRef,
        expected_projection_hash: str,
        expected_available_at: datetime,
        expected_recorded_at: datetime,
        as_of: datetime,
    ) -> R2CanonicalPublicationEvidence | None:
        """Return absence without manufacturing a Publication projection."""

        del (
            kind,
            reference,
            expected_projection_hash,
            expected_available_at,
            expected_recorded_at,
            as_of,
        )
        return None


class _UnavailableR2CycleProvider:
    """Explicit absence until canonical complete-cycle PIT receipts exist."""

    __slots__ = ("_key",)

    def __init__(self, key: str) -> None:
        self._key = key

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

        return self._key

    def get_exact(
        self,
        *,
        evidence_ref: R2EvidenceRef,
        taxonomy_publication_ref: R2PublicationRef,
        calendar_publication_ref: R2PublicationRef,
        as_of: datetime,
    ) -> R2CyclePITEvidence | None:
        """Return absence without projecting synthetic cycle evidence."""

        del (
            evidence_ref,
            taxonomy_publication_ref,
            calendar_publication_ref,
            as_of,
        )
        return None


class _UnavailableR2AuditOutcomeProvider:
    """Explicit absence because Audit owns no authoritative R2 outcome ledger."""

    __slots__ = ("_key",)

    def __init__(self, key: str) -> None:
        self._key = key

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

        return self._key

    def get_exact(
        self,
        *,
        policy_ref: R2EvidenceRef,
        audit_plan_ref: R2EvidenceRef,
        cycle_evidence_refs: tuple[R2EvidenceRef, ...],
        expected_outcome_id: str,
        expected_outcome_version: str,
        as_of: datetime,
    ) -> R2AuditExplanatoryOutcome | None:
        """Return absence without treating Research persistence as Audit truth."""

        del (
            policy_ref,
            audit_plan_ref,
            cycle_evidence_refs,
            expected_outcome_id,
            expected_outcome_version,
            as_of,
        )
        return None


class _UnavailableR2MonitoringFactProvider:
    """Explicit absence because Audit owns no canonical R2 monitoring facts."""

    __slots__ = ("_key",)

    def __init__(self, key: str) -> None:
        self._key = key

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

        return self._key

    def list_exact(
        self,
        *,
        policy_ref: R2EvidenceRef,
        taxonomy_publication_ref: R2PublicationRef,
        calendar_publication_ref: R2PublicationRef,
        expected_fact_identities: tuple[tuple[str, str], ...],
        as_of: datetime,
    ) -> tuple[R2MonitoringRawFact, ...]:
        """Return no facts without copying 0016 observations into Audit."""

        del (
            policy_ref,
            taxonomy_publication_ref,
            calendar_publication_ref,
            expected_fact_identities,
            as_of,
        )
        return ()


@dataclass(frozen=True, slots=True)
class DjangoR2ResearchControlRuntime:
    """One read-only preflight with no mutation or consumer capability."""

    preflight: EvaluateR2ResearchControlPreflight


def build_django_r2_research_control_runtime(
    *,
    using: str = "default",
) -> DjangoR2ResearchControlRuntime:
    """Compose exact Research reads and explicit missing owner boundaries."""

    if type(using) is not str or not using.strip() or len(using) > 192:
        raise ValueError("R2 research-control database alias is invalid")
    key = f"django:{using}"
    read_repository = DjangoR2ResearchControlReadRepository(using=using)
    policy_provider = build_django_r2_trial_policy_registry_runtime(using=using).provider
    return DjangoR2ResearchControlRuntime(
        preflight=EvaluateR2ResearchControlPreflight(
            policy_provider=policy_provider,
            publication_provider=_UnavailableR2PublicationProvider(key),
            cycle_provider=_UnavailableR2CycleProvider(key),
            latest_complete_provider=read_repository,
            audit_provider=_UnavailableR2AuditOutcomeProvider(key),
            monitoring_fact_provider=_UnavailableR2MonitoringFactProvider(key),
            unit_of_work=read_repository,
        )
    )


__all__ = [
    "DjangoR2ResearchControlRuntime",
    "build_django_r2_research_control_runtime",
]
