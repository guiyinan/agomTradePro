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
