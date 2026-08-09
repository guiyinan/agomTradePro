"""Immutable evidence contracts for R2 market-structure research.

The module intentionally contains no investor catalog, asset list, data source,
or empirical threshold.  Those inputs are versioned governance data supplied
by callers.  Outputs remain descriptive, research-only evidence and can never
be promoted to an execution or decision instruction by this bounded context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from apps.data_center.domain.market_structure import (
    MarketStructurePeriodCalendar,
    MarketStructureResearchRequest,
    MarketStructureSeriesDefinition,
    MarketStructureSnapshot,
)
from apps.data_center.domain.market_structure_governance import (
    InvestorActorDefinition,
    MarketStructureGovernanceArtifactKind,
    MarketStructurePublicationAttestation,
    MarketStructureResearchStatus,
    VersionedEvidenceReference,
    _canonical_hash,
    _require_aware,
    _require_sha256,
    _require_token,
    _utc_iso,
)


@dataclass(frozen=True)
class ImmutableMarketStructureEvidence:
    """Versioned, hash-sealed and non-decision R2 research evidence."""

    evidence_key: str
    evidence_version: int
    as_of_time: datetime
    group_code: str
    group_revision: int
    method_version: str
    policy_code: str
    policy_version: int
    status: MarketStructureResearchStatus
    input_hash: str
    output_hash: str
    evidence_hash: str
    payload_json: str
    source_evidence: tuple[VersionedEvidenceReference, ...]
    research_only: bool
    must_not_use_for_decision: bool
    must_not_execute: bool

    def __post_init__(self) -> None:
        for value, field_name, maximum in (
            (self.evidence_key, "evidence_key", 128),
            (self.group_code, "group_code", 64),
            (self.method_version, "method_version", 64),
            (self.policy_code, "policy_code", 64),
        ):
            _require_token(
                value,
                f"ImmutableMarketStructureEvidence.{field_name}",
                maximum=maximum,
            )
        for version_value, field_name in (
            (self.evidence_version, "evidence_version"),
            (self.group_revision, "group_revision"),
            (self.policy_version, "policy_version"),
        ):
            if isinstance(version_value, bool) or version_value <= 0:
                raise ValueError(f"ImmutableMarketStructureEvidence.{field_name} must be positive")
        _require_aware(self.as_of_time, "ImmutableMarketStructureEvidence.as_of_time")
        for value, field_name in (
            (self.input_hash, "input_hash"),
            (self.output_hash, "output_hash"),
            (self.evidence_hash, "evidence_hash"),
        ):
            _require_sha256(value, f"ImmutableMarketStructureEvidence.{field_name}")
        if (
            not self.research_only
            or not self.must_not_use_for_decision
            or not self.must_not_execute
        ):
            raise ValueError("market-structure evidence must remain research-only")
        identities = {
            (reference.dataset, reference.version_id) for reference in self.source_evidence
        }
        if len(identities) != len(self.source_evidence):
            raise ValueError("source_evidence cannot contain duplicate versions")
        try:
            parsed = json.loads(self.payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("payload_json must encode canonical evidence") from exc
        if not isinstance(parsed, dict):
            raise ValueError("payload_json must encode an object")
        payload = cast(dict[str, object], parsed)
        input_payload = payload.get("input")
        output_payload = payload.get("output")
        if not isinstance(input_payload, dict) or not isinstance(output_payload, dict):
            raise ValueError("payload_json must contain input and output objects")
        raw_publications = input_payload.get("governance_publications")
        if not isinstance(raw_publications, list):
            raise ValueError("market-structure governance publications must be a list")
        publications: list[MarketStructurePublicationAttestation] = []
        for raw_publication in raw_publications:
            if not isinstance(raw_publication, dict):
                raise ValueError("market-structure governance publication is invalid")
            publication = MarketStructurePublicationAttestation.from_payload(
                cast(dict[str, object], raw_publication)
            )
            if (
                publication.published_at > self.as_of_time
                or publication.publication_as_of > self.as_of_time
            ):
                raise ValueError("market-structure governance publication is from the future")
            publications.append(publication)
        publication_identities = {
            (item.artifact_kind, item.member_natural_key) for item in publications
        }
        if len(publication_identities) != len(publications):
            raise ValueError("market-structure governance publications contain duplicates")
        if _canonical_hash(input_payload) != self.input_hash:
            raise ValueError("market-structure input_hash mismatch")
        embedded_source_evidence = input_payload.get("source_evidence")
        expected_source_evidence = [
            reference.to_payload()
            for reference in sorted(
                self.source_evidence,
                key=lambda item: (item.dataset, item.version_id, item.content_hash.lower()),
            )
        ]
        if embedded_source_evidence != expected_source_evidence:
            raise ValueError("market-structure source_evidence conflicts with sealed input")
        if _canonical_hash(output_payload) != self.output_hash:
            raise ValueError("market-structure output_hash mismatch")
        if output_payload.get("status") != self.status.value:
            raise ValueError("market-structure status conflicts with output payload")
        if output_payload.get("deterministic_conclusion") is not None:
            raise ValueError("market-structure evidence cannot contain a conclusion")
        expected_hash = market_structure_evidence_hash(
            evidence_key=self.evidence_key,
            evidence_version=self.evidence_version,
            as_of_time=self.as_of_time,
            group_code=self.group_code,
            group_revision=self.group_revision,
            method_version=self.method_version,
            policy_code=self.policy_code,
            policy_version=self.policy_version,
            status=self.status,
            input_hash=self.input_hash,
            output_hash=self.output_hash,
        )
        if expected_hash != self.evidence_hash:
            raise ValueError("market-structure evidence_hash mismatch")
        if self.status is MarketStructureResearchStatus.AVAILABLE and not self.source_evidence:
            raise ValueError("available market-structure evidence requires source versions")
        if self.status is MarketStructureResearchStatus.AVAILABLE:
            artifact_kinds = {item.artifact_kind for item in publications}
            if artifact_kinds != {
                MarketStructureGovernanceArtifactKind.ACTOR,
                MarketStructureGovernanceArtifactKind.SERIES,
                MarketStructureGovernanceArtifactKind.PERIOD_CALENDAR,
            }:
                raise ValueError(
                    "available market-structure evidence requires published taxonomy and calendar"
                )
            calendar_payload = input_payload.get("period_calendar")
            actor_payloads = input_payload.get("actor_definitions")
            series_payloads = input_payload.get("series_definitions")
            if (
                not isinstance(calendar_payload, dict)
                or not isinstance(actor_payloads, list)
                or not isinstance(series_payloads, list)
            ):
                raise ValueError("available market-structure governance payload is incomplete")
            embedded_hashes = {
                (
                    MarketStructureGovernanceArtifactKind.PERIOD_CALENDAR,
                    calendar_payload.get("calendar_hash"),
                ),
                *(
                    (
                        MarketStructureGovernanceArtifactKind.ACTOR,
                        item.get("definition_hash"),
                    )
                    for item in actor_payloads
                    if isinstance(item, dict)
                ),
                *(
                    (
                        MarketStructureGovernanceArtifactKind.SERIES,
                        item.get("definition_hash"),
                    )
                    for item in series_payloads
                    if isinstance(item, dict)
                ),
            }
            attested_hashes = {(item.artifact_kind, item.artifact_hash) for item in publications}
            if embedded_hashes != attested_hashes:
                raise ValueError(
                    "market-structure governance publications do not cover exact artifacts"
                )

    @property
    def governance_publications(
        self,
    ) -> tuple[MarketStructurePublicationAttestation, ...]:
        """Restore the exact Publication proofs sealed into this evidence."""

        parsed = json.loads(self.payload_json)
        if not isinstance(parsed, dict):
            raise ValueError("payload_json must encode an object")
        input_payload = parsed.get("input")
        if not isinstance(input_payload, dict):
            raise ValueError("payload_json must contain an input object")
        raw_publications = input_payload.get("governance_publications")
        if not isinstance(raw_publications, list):
            raise ValueError("market-structure governance publications must be a list")
        restored: list[MarketStructurePublicationAttestation] = []
        for raw_publication in raw_publications:
            if not isinstance(raw_publication, dict):
                raise ValueError("market-structure governance publication is invalid")
            restored.append(
                MarketStructurePublicationAttestation.from_payload(
                    cast(dict[str, object], raw_publication)
                )
            )
        return tuple(restored)


def market_structure_evidence_hash(
    *,
    evidence_key: str,
    evidence_version: int,
    as_of_time: datetime,
    group_code: str,
    group_revision: int,
    method_version: str,
    policy_code: str,
    policy_version: int,
    status: MarketStructureResearchStatus,
    input_hash: str,
    output_hash: str,
) -> str:
    """Seal one evidence identity, version, clocks, method and I/O hashes."""

    return _canonical_hash(
        {
            "as_of_time": _utc_iso(as_of_time),
            "evidence_key": evidence_key,
            "evidence_version": evidence_version,
            "group_code": group_code,
            "group_revision": group_revision,
            "input_hash": input_hash,
            "method_version": method_version,
            "output_hash": output_hash,
            "policy_code": policy_code,
            "policy_version": policy_version,
            "status": status.value,
        }
    )


def build_market_structure_evidence(
    *,
    request: MarketStructureResearchRequest,
    snapshot: MarketStructureSnapshot,
    period_calendar: MarketStructurePeriodCalendar | None,
    actor_definitions: tuple[InvestorActorDefinition, ...],
    series_definitions: tuple[MarketStructureSeriesDefinition, ...],
    source_evidence: tuple[VersionedEvidenceReference, ...],
    governance_publications: tuple[MarketStructurePublicationAttestation, ...],
) -> ImmutableMarketStructureEvidence:
    """Build a canonical immutable evidence record for an R2 run."""

    unique_evidence = {
        (reference.dataset, reference.version_id, reference.content_hash.lower()): reference
        for reference in source_evidence
    }
    ordered_evidence = tuple(
        unique_evidence[key]
        for key in sorted(unique_evidence, key=lambda item: (item[0], item[1], item[2]))
    )
    input_payload: dict[str, object] = {
        "actor_definitions": [
            {
                **definition.to_payload(),
                "definition_hash": definition.definition_hash,
            }
            for definition in sorted(
                actor_definitions,
                key=lambda item: (
                    item.taxonomy_code,
                    item.taxonomy_version,
                    item.actor_code,
                ),
            )
        ],
        "governance_publications": [
            item.to_payload()
            for item in sorted(
                governance_publications,
                key=lambda item: (item.artifact_kind.value, item.member_natural_key),
            )
        ],
        "period_calendar": (
            {
                **period_calendar.to_payload(),
                "calendar_hash": period_calendar.calendar_hash,
            }
            if period_calendar is not None
            else None
        ),
        "request": request.to_payload(),
        "series_definitions": [
            {
                **definition.to_payload(),
                "definition_hash": definition.definition_hash,
            }
            for definition in sorted(
                series_definitions,
                key=lambda item: (item.series_code, item.series_version),
            )
        ],
        "source_evidence": [reference.to_payload() for reference in ordered_evidence],
    }
    output_payload = snapshot.to_payload()
    input_hash = _canonical_hash(input_payload)
    output_hash = _canonical_hash(output_payload)
    evidence_hash = market_structure_evidence_hash(
        evidence_key=request.evidence_key,
        evidence_version=request.evidence_version,
        as_of_time=request.as_of_time,
        group_code=request.group_code,
        group_revision=request.group_revision,
        method_version=request.method_version,
        policy_code=request.policy.policy_code,
        policy_version=request.policy.policy_version,
        status=snapshot.status,
        input_hash=input_hash,
        output_hash=output_hash,
    )
    return ImmutableMarketStructureEvidence(
        evidence_key=request.evidence_key,
        evidence_version=request.evidence_version,
        as_of_time=request.as_of_time,
        group_code=request.group_code,
        group_revision=request.group_revision,
        method_version=request.method_version,
        policy_code=request.policy.policy_code,
        policy_version=request.policy.policy_version,
        status=snapshot.status,
        input_hash=input_hash,
        output_hash=output_hash,
        evidence_hash=evidence_hash,
        payload_json=json.dumps(
            {"input": input_payload, "output": output_payload},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        source_evidence=ordered_evidence,
        research_only=True,
        must_not_use_for_decision=True,
        must_not_execute=True,
    )


__all__ = [
    "ImmutableMarketStructureEvidence",
    "market_structure_evidence_hash",
    "build_market_structure_evidence",
]
