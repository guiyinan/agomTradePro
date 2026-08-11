"""Immutable Signal-owner registry definitions for R7 realization sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from re import fullmatch

from apps.signal.domain.forecast_realization_owner import (
    ForecastRealizationManifestSource,
    ForecastRealizationMemberSource,
)

_DEFINITION_VERSION = "signal-r7-realization-source-definition.v1"
_OWNER = "signal.forecast_ledger"


def _hash_components(*components: str) -> str:
    digest = sha256()
    for component in components:
        encoded = component.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big", signed=False))
        digest.update(encoded)
    return digest.hexdigest()


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _utc(value: datetime, field_name: str) -> datetime:
    _require_aware(value, field_name)
    return value.astimezone(UTC)


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def validated_manifest_source_copy(
    value: ForecastRealizationManifestSource,
) -> ForecastRealizationManifestSource:
    """Class-bound validate and rebuild every nested source value."""

    if type(value) is not ForecastRealizationManifestSource:
        raise TypeError("realization manifest source must use the exact Domain type")
    ForecastRealizationManifestSource.__post_init__(value)
    members: list[ForecastRealizationMemberSource] = []
    for member in value.members:
        if type(member) is not ForecastRealizationMemberSource:
            raise TypeError("realization member source must use the exact Domain type")
        ForecastRealizationMemberSource.__post_init__(member)
        members.append(
            ForecastRealizationMemberSource.create(
                entry_id=member.entry_id,
                observation_id=member.observation_id,
                observation_version=member.observation_version,
                expected_observation_hash=member.expected_observation_hash,
                forecast_group_id=member.forecast_group_id,
                pit_manifest_version=member.pit_manifest_version,
                pit_manifest_hash=member.pit_manifest_hash,
                censoring_rule_version=member.censoring_rule_version,
                outcome_evidence_valid_until=_utc(
                    member.outcome_evidence_valid_until,
                    "member outcome_evidence_valid_until",
                ),
                available_at=_utc(member.available_at, "member available_at"),
                evidence_ref=member.evidence_ref,
            )
        )
    rebuilt = ForecastRealizationManifestSource.create(
        owner_record_id=value.owner_record_id,
        owner_record_version=value.owner_record_version,
        result_id=value.result_id,
        result_version=value.result_version,
        result_hash=value.result_hash,
        calendar_id=value.calendar_id,
        calendar_version=value.calendar_version,
        period_id=value.period_id,
        period_version=value.period_version,
        period_hash=value.period_hash,
        period_start=_utc(value.period_start, "source period_start"),
        period_end=_utc(value.period_end, "source period_end"),
        available_at=_utc(value.available_at, "source available_at"),
        valid_until=_utc(value.valid_until, "source valid_until"),
        evidence_ref=value.evidence_ref,
        members=tuple(members),
    )
    if rebuilt.content_hash != value.content_hash:
        raise ValueError("realization manifest source is noncanonical")
    return rebuilt


@dataclass(frozen=True)
class ForecastRealizationSourceDefinition:
    """Versioned, append-only definition of one complete realization source."""

    definition_version: str
    owner: str
    source: ForecastRealizationManifestSource
    registered_at: datetime
    research_only: bool
    must_not_use_for_decision: bool
    must_not_execute: bool
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        source: ForecastRealizationManifestSource,
        registered_at: datetime,
    ) -> ForecastRealizationSourceDefinition:
        """Seal a canonical source using only a trusted registration clock."""

        canonical_source = validated_manifest_source_copy(source)
        canonical_registered_at = _utc(registered_at, "registered_at")
        values = (
            _DEFINITION_VERSION,
            _OWNER,
            canonical_source,
            canonical_registered_at,
            True,
            True,
            True,
        )
        return cls(*values, _definition_hash(*values))

    def __post_init__(self) -> None:
        if self.definition_version != _DEFINITION_VERSION or self.owner != _OWNER:
            raise ValueError("realization source definition owner or version is invalid")
        source = validated_manifest_source_copy(self.source)
        if source != self.source:
            raise ValueError("realization source definition contains a noncanonical source")
        _require_aware(self.registered_at, "registered_at")
        if not source.available_at <= self.registered_at < source.valid_until:
            raise ValueError("realization source definition clocks are invalid")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("realization source definition must remain research-only")
        _require_sha256(self.content_hash, "definition content_hash")
        if self.content_hash != _definition_hash(
            self.definition_version,
            self.owner,
            source,
            self.registered_at,
            self.research_only,
            self.must_not_use_for_decision,
            self.must_not_execute,
        ):
            raise ValueError("realization source definition content hash mismatch")

    def validated_copy(self) -> ForecastRealizationSourceDefinition:
        """Return an exact, recursively rebuilt Domain value."""

        if type(self) is not ForecastRealizationSourceDefinition:
            raise TypeError("definition must use the exact Domain type")
        ForecastRealizationSourceDefinition.__post_init__(self)
        copied = ForecastRealizationSourceDefinition.create(
            source=validated_manifest_source_copy(self.source),
            registered_at=self.registered_at,
        )
        if copied.content_hash != self.content_hash:
            raise ValueError("realization source definition is noncanonical")
        return copied


def _definition_hash(
    definition_version: str,
    owner: str,
    source: ForecastRealizationManifestSource,
    registered_at: datetime,
    research_only: bool,
    must_not_use_for_decision: bool,
    must_not_execute: bool,
) -> str:
    return _hash_components(
        definition_version,
        owner,
        source.content_hash,
        _utc(registered_at, "registered_at").isoformat(),
        "true" if research_only else "false",
        "true" if must_not_use_for_decision else "false",
        "true" if must_not_execute else "false",
    )


__all__ = [
    "ForecastRealizationSourceDefinition",
    "validated_manifest_source_copy",
]
