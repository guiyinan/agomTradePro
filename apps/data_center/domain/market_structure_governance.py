"""Pure governance contracts shared by market-structure research services.

The module owns stable taxonomy concepts, Publication attestations, and the
validation/hash helpers used by the wider market-structure domain.  It has no
framework or I/O dependencies.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from apps.data_center.domain.research_data_foundation import InvestorFlowMeasureKind


class MarketStructureMeasureConcept(str, Enum):
    """Mutually exclusive economic concepts used by the R2 research layer."""

    FLOW = "flow"
    HOLDING = "holding"
    STOCK = "stock"
    TRANSACTION = "transaction"


class EmpiricalPercentileMethod(str, Enum):
    """Explicit historical-percentile methodology."""

    WEAK_EMPIRICAL_CDF = "weak_empirical_cdf"


class MarketStructureResearchStatus(str, Enum):
    """Availability of descriptive R2 research output."""

    AVAILABLE = "available"
    BLOCKED = "blocked"


class MarketStructureGovernanceArtifactKind(str, Enum):
    """Governance artifacts that require a canonical Publication gate."""

    ACTOR = "actor"
    SERIES = "series"
    PERIOD_CALENDAR = "period_calendar"


MARKET_STRUCTURE_TAXONOMY_DATASET = "research.market_structure_taxonomy.v1"
MARKET_STRUCTURE_CALENDAR_DATASET = "research.market_structure_calendar.v1"


MEASURE_KIND_BY_CONCEPT: dict[
    MarketStructureMeasureConcept,
    InvestorFlowMeasureKind,
] = {
    MarketStructureMeasureConcept.FLOW: InvestorFlowMeasureKind.FUND_FLOW,
    MarketStructureMeasureConcept.HOLDING: InvestorFlowMeasureKind.HOLDING_CHANGE,
    MarketStructureMeasureConcept.STOCK: InvestorFlowMeasureKind.CAPITAL_BALANCE,
    MarketStructureMeasureConcept.TRANSACTION: (InvestorFlowMeasureKind.TRANSACTION_NET_FLOW),
}


def _require_text(value: str, field_name: str, *, maximum: int) -> None:
    """Require a bounded non-blank string."""

    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")


def _require_token(value: str, field_name: str, *, maximum: int) -> None:
    """Require a compact identifier without whitespace."""

    _require_text(value, field_name, maximum=maximum)
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")


def _require_aware(value: datetime, field_name: str) -> None:
    """Require a timezone-aware timestamp."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_interval(
    effective_at: datetime,
    effective_to: datetime | None,
    *,
    field_name: str,
) -> None:
    """Validate one aware half-open effective interval."""

    _require_aware(effective_at, f"{field_name}.effective_at")
    if effective_to is not None:
        _require_aware(effective_to, f"{field_name}.effective_to")
        if effective_to <= effective_at:
            raise ValueError(f"{field_name}.effective_to must follow effective_at")


def _require_finite(value: Decimal, field_name: str) -> None:
    """Require a finite Decimal without accepting implicit float coercion."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _require_sha256(value: str, field_name: str) -> None:
    """Require a lowercase or uppercase SHA-256 hexadecimal digest."""

    if re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError(f"{field_name} must be a SHA-256 digest")


def _canonical_hash(payload: object) -> str:
    """Hash one JSON-compatible payload using stable canonical encoding."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_iso(value: datetime | None) -> str | None:
    """Serialize an aware datetime in a stable UTC representation."""

    return value.astimezone(UTC).isoformat() if value is not None else None


@dataclass(frozen=True)
class VersionedEvidenceReference:
    """Immutable reference to one canonical PIT fact or membership version."""

    dataset: str
    version_id: int
    content_hash: str

    def __post_init__(self) -> None:
        _require_token(self.dataset, "VersionedEvidenceReference.dataset", maximum=64)
        if isinstance(self.version_id, bool) or self.version_id <= 0:
            raise ValueError("VersionedEvidenceReference.version_id must be positive")
        _require_sha256(
            self.content_hash,
            "VersionedEvidenceReference.content_hash",
        )

    def to_payload(self) -> dict[str, object]:
        """Return the stable JSON representation used by evidence hashes."""

        return {
            "content_hash": self.content_hash.lower(),
            "dataset": self.dataset,
            "version_id": self.version_id,
        }


@dataclass(frozen=True)
class MarketStructurePublicationAttestation:
    """Exact canonical Publication/member proof for one governance artifact."""

    artifact_kind: MarketStructureGovernanceArtifactKind
    dataset_key: str
    publication_key: str
    publication_id: str
    publication_hash: str
    publication_as_of: datetime
    published_at: datetime
    member_id: str
    member_natural_key: str
    fact_table: str
    fact_pk: str
    artifact_hash: str
    member_observed_at: datetime
    attestation_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_kind, MarketStructureGovernanceArtifactKind):
            raise ValueError("market-structure publication artifact_kind is invalid")
        for value, field_name, maximum in (
            (self.dataset_key, "dataset_key", 128),
            (self.publication_key, "publication_key", 200),
            (self.publication_id, "publication_id", 100),
            (self.member_id, "member_id", 100),
            (self.member_natural_key, "member_natural_key", 300),
            (self.fact_table, "fact_table", 128),
            (self.fact_pk, "fact_pk", 100),
        ):
            _require_token(
                value,
                f"MarketStructurePublicationAttestation.{field_name}",
                maximum=maximum,
            )
        expected_dataset = (
            MARKET_STRUCTURE_CALENDAR_DATASET
            if self.artifact_kind is MarketStructureGovernanceArtifactKind.PERIOD_CALENDAR
            else MARKET_STRUCTURE_TAXONOMY_DATASET
        )
        if self.dataset_key != expected_dataset:
            raise ValueError("market-structure publication dataset/artifact mismatch")
        for value, field_name in (
            (self.publication_hash, "publication_hash"),
            (self.artifact_hash, "artifact_hash"),
            (self.attestation_hash, "attestation_hash"),
        ):
            _require_sha256(
                value,
                f"MarketStructurePublicationAttestation.{field_name}",
            )
        _require_aware(
            self.publication_as_of,
            "MarketStructurePublicationAttestation.publication_as_of",
        )
        _require_aware(
            self.published_at,
            "MarketStructurePublicationAttestation.published_at",
        )
        _require_aware(
            self.member_observed_at,
            "MarketStructurePublicationAttestation.member_observed_at",
        )
        if self.publication_as_of > self.published_at:
            raise ValueError("market-structure publication as_of exceeds published_at")
        if self.member_observed_at > self.publication_as_of:
            raise ValueError("market-structure publication member exceeds as_of")
        if self.attestation_hash != market_structure_publication_attestation_hash(self):
            raise ValueError("market-structure publication attestation hash mismatch")

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical publication proof."""

        return {
            "artifact_hash": self.artifact_hash.lower(),
            "artifact_kind": self.artifact_kind.value,
            "attestation_hash": self.attestation_hash.lower(),
            "dataset_key": self.dataset_key,
            "fact_pk": self.fact_pk,
            "fact_table": self.fact_table,
            "member_id": self.member_id,
            "member_natural_key": self.member_natural_key,
            "member_observed_at": _utc_iso(self.member_observed_at),
            "publication_as_of": _utc_iso(self.publication_as_of),
            "publication_hash": self.publication_hash.lower(),
            "publication_id": self.publication_id,
            "publication_key": self.publication_key,
            "published_at": _utc_iso(self.published_at),
        }

    @classmethod
    def create(
        cls,
        *,
        artifact_kind: MarketStructureGovernanceArtifactKind,
        dataset_key: str,
        publication_key: str,
        publication_id: str,
        publication_hash: str,
        publication_as_of: datetime,
        published_at: datetime,
        member_id: str,
        member_natural_key: str,
        fact_table: str,
        fact_pk: str,
        artifact_hash: str,
        member_observed_at: datetime,
    ) -> MarketStructurePublicationAttestation:
        """Create a hash-sealed attestation from authoritative Publication rows."""

        values: dict[str, object] = {
            "artifact_hash": artifact_hash.lower(),
            "artifact_kind": artifact_kind.value,
            "dataset_key": dataset_key,
            "fact_pk": fact_pk,
            "fact_table": fact_table,
            "member_id": member_id,
            "member_natural_key": member_natural_key,
            "member_observed_at": _utc_iso(member_observed_at),
            "publication_as_of": _utc_iso(publication_as_of),
            "publication_hash": publication_hash.lower(),
            "publication_id": publication_id,
            "publication_key": publication_key,
            "published_at": _utc_iso(published_at),
        }
        return cls(
            artifact_kind=artifact_kind,
            dataset_key=dataset_key,
            publication_key=publication_key,
            publication_id=publication_id,
            publication_hash=publication_hash,
            publication_as_of=publication_as_of,
            published_at=published_at,
            member_id=member_id,
            member_natural_key=member_natural_key,
            fact_table=fact_table,
            fact_pk=fact_pk,
            artifact_hash=artifact_hash,
            member_observed_at=member_observed_at,
            attestation_hash=_canonical_hash(values),
        )

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, object],
    ) -> MarketStructurePublicationAttestation:
        """Strictly restore one attestation from canonical evidence JSON."""

        expected_fields = {
            "artifact_hash",
            "artifact_kind",
            "attestation_hash",
            "dataset_key",
            "fact_pk",
            "fact_table",
            "member_id",
            "member_natural_key",
            "member_observed_at",
            "publication_as_of",
            "publication_hash",
            "publication_id",
            "publication_key",
            "published_at",
        }
        if set(payload) != expected_fields:
            raise ValueError("market-structure publication attestation contains unsupported fields")

        def required_text(name: str) -> str:
            value = payload.get(name)
            if not isinstance(value, str):
                raise ValueError(f"market-structure publication {name} is invalid")
            return value

        try:
            artifact_kind = MarketStructureGovernanceArtifactKind(required_text("artifact_kind"))
            return cls(
                artifact_kind=artifact_kind,
                dataset_key=required_text("dataset_key"),
                publication_key=required_text("publication_key"),
                publication_id=required_text("publication_id"),
                publication_hash=required_text("publication_hash"),
                publication_as_of=datetime.fromisoformat(required_text("publication_as_of")),
                published_at=datetime.fromisoformat(required_text("published_at")),
                member_id=required_text("member_id"),
                member_natural_key=required_text("member_natural_key"),
                fact_table=required_text("fact_table"),
                fact_pk=required_text("fact_pk"),
                artifact_hash=required_text("artifact_hash"),
                member_observed_at=datetime.fromisoformat(required_text("member_observed_at")),
                attestation_hash=required_text("attestation_hash"),
            )
        except ValueError as error:
            raise ValueError("market-structure publication attestation is invalid") from error


def market_structure_publication_attestation_hash(
    attestation: MarketStructurePublicationAttestation,
) -> str:
    """Seal a Publication identity, member identity, clocks and artifact hash."""

    return _canonical_hash(
        {
            "artifact_hash": attestation.artifact_hash.lower(),
            "artifact_kind": attestation.artifact_kind.value,
            "dataset_key": attestation.dataset_key,
            "fact_pk": attestation.fact_pk,
            "fact_table": attestation.fact_table,
            "member_id": attestation.member_id,
            "member_natural_key": attestation.member_natural_key,
            "member_observed_at": _utc_iso(attestation.member_observed_at),
            "publication_as_of": _utc_iso(attestation.publication_as_of),
            "publication_hash": attestation.publication_hash.lower(),
            "publication_id": attestation.publication_id,
            "publication_key": attestation.publication_key,
            "published_at": _utc_iso(attestation.published_at),
        }
    )


@dataclass(frozen=True)
class InvestorActorDefinition:
    """One caller-governed investor classification entry and version."""

    taxonomy_code: str
    taxonomy_version: int
    actor_code: str
    actor_name: str
    source: str
    revision_policy_ref: str
    effective_at: datetime
    available_at: datetime
    effective_to: datetime | None = None
    expires_at: datetime | None = None
    parent_actor_code: str = ""
    description: str = ""
    is_active: bool = True

    def __post_init__(self) -> None:
        _require_token(
            self.taxonomy_code,
            "InvestorActorDefinition.taxonomy_code",
            maximum=64,
        )
        if isinstance(self.taxonomy_version, bool) or self.taxonomy_version <= 0:
            raise ValueError("InvestorActorDefinition.taxonomy_version must be positive")
        _require_token(
            self.actor_code,
            "InvestorActorDefinition.actor_code",
            maximum=64,
        )
        _require_text(
            self.actor_name,
            "InvestorActorDefinition.actor_name",
            maximum=160,
        )
        _require_token(self.source, "InvestorActorDefinition.source", maximum=100)
        _require_text(
            self.revision_policy_ref,
            "InvestorActorDefinition.revision_policy_ref",
            maximum=300,
        )
        _require_interval(
            self.effective_at,
            self.effective_to,
            field_name="InvestorActorDefinition",
        )
        _require_aware(self.available_at, "InvestorActorDefinition.available_at")
        if self.available_at < self.effective_at:
            raise ValueError("investor actor cannot be available before effective_at")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "InvestorActorDefinition.expires_at")
            if self.expires_at <= self.available_at:
                raise ValueError("investor actor expires_at must follow available_at")
        if self.parent_actor_code:
            _require_token(
                self.parent_actor_code,
                "InvestorActorDefinition.parent_actor_code",
                maximum=64,
            )
            if self.parent_actor_code == self.actor_code:
                raise ValueError("investor actor cannot be its own parent")
        if not isinstance(self.is_active, bool):
            raise ValueError("InvestorActorDefinition.is_active must be a boolean")

    def to_payload(self) -> dict[str, object]:
        """Return all immutable classification semantics for hashing."""

        return {
            "actor_code": self.actor_code,
            "actor_name": self.actor_name,
            "available_at": _utc_iso(self.available_at),
            "description": self.description,
            "effective_at": _utc_iso(self.effective_at),
            "effective_to": _utc_iso(self.effective_to),
            "expires_at": _utc_iso(self.expires_at),
            "is_active": self.is_active,
            "parent_actor_code": self.parent_actor_code,
            "revision_policy_ref": self.revision_policy_ref,
            "source": self.source,
            "taxonomy_code": self.taxonomy_code,
            "taxonomy_version": self.taxonomy_version,
        }

    @property
    def definition_hash(self) -> str:
        """Return the stable content hash of this classification version."""

        return _canonical_hash(self.to_payload())


__all__ = [
    "InvestorActorDefinition",
    "MEASURE_KIND_BY_CONCEPT",
    "MARKET_STRUCTURE_CALENDAR_DATASET",
    "MARKET_STRUCTURE_TAXONOMY_DATASET",
    "EmpiricalPercentileMethod",
    "MarketStructureGovernanceArtifactKind",
    "MarketStructureMeasureConcept",
    "MarketStructurePublicationAttestation",
    "MarketStructureResearchStatus",
    "VersionedEvidenceReference",
    "market_structure_publication_attestation_hash",
]
