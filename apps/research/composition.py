"""Composition root for the Research registry and capability-readiness gates."""

from apps.research.application.capability_readiness import (
    EvaluateAllCapabilityReadinessUseCase,
    EvaluateCapabilityReadinessUseCase,
)
from apps.research.application.capability_readiness_registry import (
    CapabilityReadinessEvidenceRegistry,
    build_attested_evidence_registry,
)
from apps.research.application.use_cases import EvaluatePromotion, RegisterExperiment, RunTrial
from apps.research.infrastructure.capability_readiness_attestations import (
    load_governed_mechanism_attestations,
)
from apps.research.infrastructure.repositories import ResearchRegistryRepository


def make_register_experiment() -> RegisterExperiment:
    return RegisterExperiment(ResearchRegistryRepository())


def make_run_trial() -> RunTrial:
    return RunTrial(ResearchRegistryRepository())


def make_evaluate_promotion() -> EvaluatePromotion:
    return EvaluatePromotion(ResearchRegistryRepository())


def make_capability_readiness_evidence_provider() -> CapabilityReadinessEvidenceRegistry:
    """Compose the runtime provider from explicit governed owner attestations."""

    return build_attested_evidence_registry(load_governed_mechanism_attestations())


def make_evaluate_capability_readiness() -> EvaluateCapabilityReadinessUseCase:
    """Compose the fail-closed research-capability readiness use case."""

    return EvaluateCapabilityReadinessUseCase(make_capability_readiness_evidence_provider())


def make_evaluate_all_capability_readiness() -> EvaluateAllCapabilityReadinessUseCase:
    """Compose the read-only R1--R8 readiness inventory use case."""

    return EvaluateAllCapabilityReadinessUseCase(make_capability_readiness_evidence_provider())
