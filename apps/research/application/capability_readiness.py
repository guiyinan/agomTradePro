"""Application orchestration for governed research-capability start gates."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.research.domain.capability_readiness import (
    CapabilityReadinessReport,
    ReadinessEvidence,
    ReadinessRequirement,
    ResearchCapability,
    evaluate_capability_readiness,
    requirements_for,
)


class CapabilityReadinessEvidenceProvider(Protocol):
    """Read evidence from canonical owners without exposing their persistence."""

    def collect(
        self,
        *,
        capability: ResearchCapability,
        requirements: tuple[ReadinessRequirement, ...],
        evaluated_at: datetime,
    ) -> tuple[ReadinessEvidence, ...]:
        """Return available owner-attested evidence for the requested gate."""


class EvaluateCapabilityReadinessUseCase:
    """Collect owner evidence and issue one immutable fail-closed decision."""

    def __init__(self, evidence_provider: CapabilityReadinessEvidenceProvider):
        self._evidence_provider = evidence_provider

    def execute(
        self,
        *,
        capability: ResearchCapability,
        evaluated_at: datetime,
    ) -> CapabilityReadinessReport:
        """Evaluate the exact requirement set governed for the capability."""

        requirements = requirements_for(capability)
        evidence = self._evidence_provider.collect(
            capability=capability,
            requirements=requirements,
            evaluated_at=evaluated_at,
        )
        return evaluate_capability_readiness(
            capability=capability,
            evaluated_at=evaluated_at,
            evidence=evidence,
        )


class EvaluateAllCapabilityReadinessUseCase:
    """Collect one complete, ordered readiness inventory for R1--R8.

    This is a read-only aggregation over the same owner-scoped provider used
    by the single-capability gate.  It deliberately does not merge evidence
    between capabilities or infer a readiness decision from another report.
    """

    def __init__(self, evidence_provider: CapabilityReadinessEvidenceProvider) -> None:
        """Retain only the single-capability evaluator used for each report."""

        self._evaluate_one = EvaluateCapabilityReadinessUseCase(evidence_provider)

    def execute(
        self,
        *,
        evaluated_at: datetime,
    ) -> tuple[CapabilityReadinessReport, ...]:
        """Return one complete report per canonical R1--R8 capability."""

        return tuple(
            self._evaluate_one.execute(
                capability=capability,
                evaluated_at=evaluated_at,
            )
            for capability in ResearchCapability
        )
