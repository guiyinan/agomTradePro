"""Owner-isolated runtime evidence collection for research capability gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.capability_readiness import (
    ReadinessEvidence,
    ReadinessRequirement,
    ReadinessState,
    ResearchCapability,
    is_mechanism_attestable_requirement,
    requirement_owner,
    requirements_for,
)


@dataclass(frozen=True)
class OwnerMechanismAttestation:
    """Time-bounded owner attestation for one implemented platform mechanism."""

    requirement: ReadinessRequirement
    owner: str
    observed_at: datetime
    valid_until: datetime
    evidence_ref: str

    def __post_init__(self) -> None:
        """Validate the attestation using the canonical evidence contract."""

        if not is_mechanism_attestable_requirement(self.requirement):
            raise ValueError(f"{self.requirement.value} is not mechanism-attestable")
        ReadinessEvidence(
            requirement=self.requirement,
            owner=self.owner,
            state=ReadinessState.VERIFIED,
            observed_at=self.observed_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
        )

    def to_evidence(self) -> ReadinessEvidence:
        """Project the attestation into immutable gate evidence."""

        return ReadinessEvidence(
            requirement=self.requirement,
            owner=self.owner,
            state=ReadinessState.VERIFIED,
            observed_at=self.observed_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
        )


class CapabilityReadinessOwnerAdapter(Protocol):
    """Owner-specific evidence adapter consumed by the runtime registry."""

    @property
    def owner(self) -> str:
        """Return the canonical owner represented by this adapter."""

    def collect(
        self,
        *,
        capability: ResearchCapability,
        requirements: tuple[ReadinessRequirement, ...],
        evaluated_at: datetime,
    ) -> tuple[ReadinessEvidence, ...]:
        """Return evidence only for the supplied owner-bound requirements."""


class OwnerEvidenceUnavailableError(RuntimeError):
    """Signal that an owner adapter is temporarily unable to attest evidence."""


class AttestedMechanismOwnerAdapter:
    """Publish explicit mechanism attestations and fail closed for every other item."""

    def __init__(
        self,
        *,
        owner: str,
        attestations: tuple[OwnerMechanismAttestation, ...],
    ) -> None:
        if not owner.strip():
            raise ValueError("readiness owner adapter requires an owner")
        by_requirement: dict[ReadinessRequirement, OwnerMechanismAttestation] = {}
        for attestation in attestations:
            if attestation.owner != owner:
                raise ValueError("owner adapter cannot contain another owner's attestation")
            if attestation.requirement in by_requirement:
                raise ValueError(f"duplicate owner attestation for {attestation.requirement.value}")
            by_requirement[attestation.requirement] = attestation
        self._owner = owner
        self._attestations = by_requirement

    @property
    def owner(self) -> str:
        """Return the canonical owner represented by this adapter."""

        return self._owner

    def collect(
        self,
        *,
        capability: ResearchCapability,
        requirements: tuple[ReadinessRequirement, ...],
        evaluated_at: datetime,
    ) -> tuple[ReadinessEvidence, ...]:
        """Return attestations without inferring data readiness from code existence."""

        evidence: list[ReadinessEvidence] = []
        for requirement in requirements:
            if requirement_owner(requirement) != self.owner:
                raise ValueError(
                    f"{self.owner} adapter received non-owned requirement {requirement.value}"
                )
            attestation = self._attestations.get(requirement)
            if attestation is None:
                evidence.append(
                    _non_verified_evidence(
                        capability=capability,
                        requirement=requirement,
                        owner=self.owner,
                        evaluated_at=evaluated_at,
                        state=ReadinessState.UNVERIFIED,
                        reason_suffix="not_attested",
                    )
                )
            elif attestation.observed_at > evaluated_at:
                evidence.append(
                    _non_verified_evidence(
                        capability=capability,
                        requirement=requirement,
                        owner=self.owner,
                        evaluated_at=evaluated_at,
                        state=ReadinessState.UNVERIFIED,
                        reason_suffix="attestation_not_yet_observed",
                    )
                )
            elif attestation.valid_until <= evaluated_at:
                evidence.append(
                    _non_verified_evidence(
                        capability=capability,
                        requirement=requirement,
                        owner=self.owner,
                        evaluated_at=evaluated_at,
                        state=ReadinessState.STALE,
                        reason_suffix="attestation_expired",
                    )
                )
            else:
                evidence.append(attestation.to_evidence())
        return tuple(evidence)


class CapabilityReadinessEvidenceRegistry:
    """Compose canonical-owner adapters into one fail-closed evidence provider."""

    def __init__(
        self,
        adapters: tuple[CapabilityReadinessOwnerAdapter, ...],
    ) -> None:
        by_owner: dict[str, CapabilityReadinessOwnerAdapter] = {}
        for adapter in adapters:
            if not adapter.owner.strip():
                raise ValueError("readiness owner adapter requires an owner")
            if adapter.owner in by_owner:
                raise ValueError(f"duplicate readiness owner adapter: {adapter.owner}")
            by_owner[adapter.owner] = adapter
        self._adapters = by_owner

    def collect(
        self,
        *,
        capability: ResearchCapability,
        requirements: tuple[ReadinessRequirement, ...],
        evaluated_at: datetime,
    ) -> tuple[ReadinessEvidence, ...]:
        """Collect the exact governed set while materializing unavailable owners."""

        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("readiness evaluated_at must be timezone-aware")
        governed = requirements_for(capability)
        if requirements != governed:
            raise ValueError("readiness provider requires the complete governed requirement set")

        requested_by_owner: dict[str, list[ReadinessRequirement]] = {}
        for requirement in requirements:
            owner = requirement_owner(requirement)
            requested_by_owner.setdefault(owner, []).append(requirement)

        supplied: dict[ReadinessRequirement, ReadinessEvidence] = {}
        for owner, owner_requirements_list in requested_by_owner.items():
            owner_requirements = tuple(owner_requirements_list)
            adapter = self._adapters.get(owner)
            if adapter is None:
                for requirement in owner_requirements:
                    supplied[requirement] = _non_verified_evidence(
                        capability=capability,
                        requirement=requirement,
                        owner=owner,
                        evaluated_at=evaluated_at,
                        state=ReadinessState.MISSING,
                        reason_suffix="owner_adapter_missing",
                    )
                continue
            try:
                owner_evidence = adapter.collect(
                    capability=capability,
                    requirements=owner_requirements,
                    evaluated_at=evaluated_at,
                )
            except OwnerEvidenceUnavailableError:
                for requirement in owner_requirements:
                    supplied[requirement] = _non_verified_evidence(
                        capability=capability,
                        requirement=requirement,
                        owner=owner,
                        evaluated_at=evaluated_at,
                        state=ReadinessState.UNVERIFIED,
                        reason_suffix="owner_evidence_unavailable",
                    )
                continue
            allowed = set(owner_requirements)
            for item in owner_evidence:
                if item.owner != owner:
                    raise ValueError("owner adapter returned evidence for another owner")
                if item.requirement not in allowed:
                    raise ValueError(
                        f"owner adapter returned unexpected evidence for {item.requirement.value}"
                    )
                if item.requirement in supplied:
                    raise ValueError(
                        f"owner adapter returned duplicate evidence for {item.requirement.value}"
                    )
                supplied[item.requirement] = item
            for requirement in owner_requirements:
                if requirement not in supplied:
                    supplied[requirement] = _non_verified_evidence(
                        capability=capability,
                        requirement=requirement,
                        owner=owner,
                        evaluated_at=evaluated_at,
                        state=ReadinessState.UNVERIFIED,
                        reason_suffix="owner_evidence_omitted",
                    )

        return tuple(supplied[requirement] for requirement in requirements)


def build_attested_evidence_registry(
    attestations: tuple[OwnerMechanismAttestation, ...],
) -> CapabilityReadinessEvidenceRegistry:
    """Build one registry with exactly the owners present in the attestations."""

    grouped: dict[str, list[OwnerMechanismAttestation]] = {}
    for attestation in attestations:
        grouped.setdefault(attestation.owner, []).append(attestation)
    adapters = tuple(
        AttestedMechanismOwnerAdapter(
            owner=owner,
            attestations=tuple(grouped[owner]),
        )
        for owner in sorted(grouped)
    )
    return CapabilityReadinessEvidenceRegistry(adapters)


def _non_verified_evidence(
    *,
    capability: ResearchCapability,
    requirement: ReadinessRequirement,
    owner: str,
    evaluated_at: datetime,
    state: ReadinessState,
    reason_suffix: str,
) -> ReadinessEvidence:
    """Create stable fail-closed evidence for an unattested prerequisite."""

    if state is ReadinessState.VERIFIED:
        raise ValueError("non-verified evidence cannot use verified state")
    return ReadinessEvidence(
        requirement=requirement,
        owner=owner,
        state=state,
        observed_at=evaluated_at,
        blocking_reason=(f"{capability.value}.{requirement.value}.runtime.{reason_suffix}"),
    )
