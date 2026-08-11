"""Unit tests for owner-isolated capability-readiness evidence collection."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    is_mechanism_attestable_requirement,
    requirement_owner,
)
from apps.research.infrastructure.capability_readiness_attestations import (
    load_governed_mechanism_attestations,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "requirement",
    (
        ReadinessRequirement.EXPERIMENT_REGISTRY,
        ReadinessRequirement.GOVERNED_SCENARIO_VERSIONS,
        ReadinessRequirement.OPTIMIZER_INPUT_CONTRACT,
    ),
)
def test_explicit_mechanism_requirements_are_attestable(
    requirement: ReadinessRequirement,
) -> None:
    assert is_mechanism_attestable_requirement(requirement)


@pytest.mark.parametrize(
    "requirement",
    (
        ReadinessRequirement.COMPLETE_SCENARIO_OUTCOME_HISTORY,
        ReadinessRequirement.PORTFOLIO_CANONICAL_SNAPSHOT,
        ReadinessRequirement.EXECUTION_FEEDBACK_RECONCILED,
    ),
)
def test_live_data_and_outcome_requirements_are_not_mechanism_attestable(
    requirement: ReadinessRequirement,
) -> None:
    assert not is_mechanism_attestable_requirement(requirement)


@pytest.mark.parametrize(
    "requirement",
    (
        ReadinessRequirement.COMPLETE_SCENARIO_OUTCOME_HISTORY,
        ReadinessRequirement.PORTFOLIO_CANONICAL_SNAPSHOT,
        ReadinessRequirement.EXECUTION_FEEDBACK_RECONCILED,
    ),
)
def test_static_manifest_rejects_live_data_and_outcome_attestations(
    tmp_path: Path,
    requirement: ReadinessRequirement,
) -> None:
    manifest = tmp_path / "readiness-attestations.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "research-capability-mechanism-attestations.v1",
                "attestations": [
                    {
                        "requirement": requirement.value,
                        "owner": requirement_owner(requirement),
                        "observed_at": "2026-08-05T00:00:00+08:00",
                        "valid_until": "2026-11-05T00:00:00+08:00",
                        "evidence_ref": "repo://mechanism|test://contract",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not mechanism-attestable"):
        load_governed_mechanism_attestations(manifest)


def test_current_governed_manifest_contains_only_explicit_mechanisms() -> None:
    attestations = load_governed_mechanism_attestations()

    assert attestations
    assert all(is_mechanism_attestable_requirement(item.requirement) for item in attestations)


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
