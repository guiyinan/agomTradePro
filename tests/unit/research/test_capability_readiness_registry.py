"""Unit tests for owner-isolated capability-readiness evidence collection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.capability_readiness_registry import (
    AttestedMechanismOwnerAdapter,
    CapabilityReadinessEvidenceRegistry,
    OwnerEvidenceUnavailableError,
    OwnerMechanismAttestation,
)
from apps.research.domain.capability_readiness import (
    R3_REQUIREMENTS,
    ReadinessEvidence,
    ReadinessRequirement,
    ReadinessState,
    ResearchCapability,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def _attestation(requirement: ReadinessRequirement) -> OwnerMechanismAttestation:
    return OwnerMechanismAttestation(
        requirement=requirement,
        owner="research",
        observed_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(days=1),
        evidence_ref=f"repo://mechanism/{requirement.value}|test://contract",
    )


def test_registry_attests_only_explicit_owner_mechanisms() -> None:
    adapter = AttestedMechanismOwnerAdapter(
        owner="research",
        attestations=(_attestation(ReadinessRequirement.EXPERIMENT_REGISTRY),),
    )
    registry = CapabilityReadinessEvidenceRegistry((adapter,))

    evidence = registry.collect(
        capability=ResearchCapability.MACRO_FACTOR_NOWCAST,
        requirements=R3_REQUIREMENTS,
        evaluated_at=NOW,
    )
    by_requirement = {item.requirement: item for item in evidence}

    assert by_requirement[ReadinessRequirement.EXPERIMENT_REGISTRY].state is ReadinessState.VERIFIED
    assert (
        by_requirement[ReadinessRequirement.MULTIPLE_TEST_FAMILY].state is ReadinessState.UNVERIFIED
    )
    assert by_requirement[ReadinessRequirement.TARGET_MACRO_VINTAGES_PIT].state is (
        ReadinessState.MISSING
    )
    assert by_requirement[ReadinessRequirement.MULTIPLE_TEST_FAMILY].blocking_reason == (
        "macro_factor_nowcast.multiple_test_family.runtime.not_attested"
    )
    assert by_requirement[ReadinessRequirement.TARGET_MACRO_VINTAGES_PIT].blocking_reason == (
        "macro_factor_nowcast.target_macro_vintages_pit.runtime.owner_adapter_missing"
    )


def test_registry_requires_the_complete_governed_requirement_set() -> None:
    registry = CapabilityReadinessEvidenceRegistry(())

    with pytest.raises(ValueError, match="complete governed requirement set"):
        registry.collect(
            capability=ResearchCapability.MACRO_FACTOR_NOWCAST,
            requirements=R3_REQUIREMENTS[:-1],
            evaluated_at=NOW,
        )


def test_registry_rejects_duplicate_owner_adapters() -> None:
    adapter = AttestedMechanismOwnerAdapter(owner="research", attestations=())

    with pytest.raises(ValueError, match="duplicate readiness owner adapter"):
        CapabilityReadinessEvidenceRegistry((adapter, adapter))


class _UnavailableResearchAdapter:
    @property
    def owner(self) -> str:
        return "research"

    def collect(
        self,
        *,
        capability: ResearchCapability,
        requirements: tuple[ReadinessRequirement, ...],
        evaluated_at: datetime,
    ) -> tuple[ReadinessEvidence, ...]:
        raise OwnerEvidenceUnavailableError("temporary owner outage")


def test_registry_fails_closed_when_an_owner_is_temporarily_unavailable() -> None:
    registry = CapabilityReadinessEvidenceRegistry((_UnavailableResearchAdapter(),))

    evidence = registry.collect(
        capability=ResearchCapability.MACRO_FACTOR_NOWCAST,
        requirements=R3_REQUIREMENTS,
        evaluated_at=NOW,
    )
    research_evidence = tuple(item for item in evidence if item.owner == "research")

    assert research_evidence
    assert {item.state for item in research_evidence} == {ReadinessState.UNVERIFIED}
    assert all(
        item.blocking_reason is not None
        and item.blocking_reason.endswith(".runtime.owner_evidence_unavailable")
        for item in research_evidence
    )


class _OmittingResearchAdapter:
    @property
    def owner(self) -> str:
        return "research"

    def collect(
        self,
        *,
        capability: ResearchCapability,
        requirements: tuple[ReadinessRequirement, ...],
        evaluated_at: datetime,
    ) -> tuple[ReadinessEvidence, ...]:
        return ()


def test_registry_materializes_evidence_omitted_by_a_connected_owner() -> None:
    registry = CapabilityReadinessEvidenceRegistry((_OmittingResearchAdapter(),))

    evidence = registry.collect(
        capability=ResearchCapability.MACRO_FACTOR_NOWCAST,
        requirements=R3_REQUIREMENTS,
        evaluated_at=NOW,
    )
    experiment = next(
        item for item in evidence if item.requirement is ReadinessRequirement.EXPERIMENT_REGISTRY
    )

    assert experiment.state is ReadinessState.UNVERIFIED
    assert experiment.blocking_reason is not None
    assert experiment.blocking_reason.endswith(".runtime.owner_evidence_omitted")


def test_historical_evaluation_does_not_use_a_future_attestation() -> None:
    adapter = AttestedMechanismOwnerAdapter(
        owner="research",
        attestations=(_attestation(ReadinessRequirement.EXPERIMENT_REGISTRY),),
    )
    registry = CapabilityReadinessEvidenceRegistry((adapter,))

    evidence = registry.collect(
        capability=ResearchCapability.MACRO_FACTOR_NOWCAST,
        requirements=R3_REQUIREMENTS,
        evaluated_at=NOW - timedelta(days=1),
    )
    experiment = next(
        item for item in evidence if item.requirement is ReadinessRequirement.EXPERIMENT_REGISTRY
    )

    assert experiment.state is ReadinessState.UNVERIFIED
    assert experiment.blocking_reason is not None
    assert experiment.blocking_reason.endswith(".runtime.attestation_not_yet_observed")
