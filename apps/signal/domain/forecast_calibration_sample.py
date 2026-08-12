"""Canonical Signal-owned calibration sample evidence.

The definition freezes the complete forecast denominator before outcomes are
read.  A receipt then records one explicit state for every expected member;
missing outcomes therefore remain auditable rows instead of disappearing from
coverage calculations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding

DEFINITION_VERSION = "forecast-calibration-sample-definition.v1"
SOURCE_VERSION = "forecast-calibration-sample-source.v1"
EXPECTED_MEMBER_VERSION = "forecast-calibration-expected-member.v1"
OWNER_RECORD_VERSION = "forecast-calibration-entry-owner-record.v1"
RECEIPT_VERSION = "forecast-calibration-sample-receipt.v1"
MEMBER_RECEIPT_VERSION = "forecast-calibration-sample-member-receipt.v1"


def _hash_components(*components: str) -> str:
    digest = sha256()
    for component in components:
        encoded = component.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _token(value: object, field_name: str, *, maximum: int = 255) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field_name} must be nonblank and at most {maximum} characters")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field_name} contains control characters")
    return normalized


def _digest(value: object, field_name: str) -> str:
    normalized = _token(value, field_name, maximum=64).lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _positive_duration(value: object, field_name: str) -> timedelta:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise ValueError(f"{field_name} must be a positive timedelta")
    return value


def _utc_text(value: datetime) -> str:
    return _aware(value, "datetime").astimezone(UTC).isoformat(timespec="microseconds")


def _binding_copy(binding: object) -> ScenarioForecastBinding:
    if type(binding) is not ScenarioForecastBinding:
        raise ValueError("binding must be an exact ScenarioForecastBinding")
    assert isinstance(binding, ScenarioForecastBinding)
    return ScenarioForecastBinding.from_values(
        scenario_revision_id=binding.scenario_revision_id,
        scenario_set_revision_id=binding.scenario_set_revision_id,
        subjective_probability=binding.subjective_probability,
        subjective_probability_source_version=binding.subjective_probability_source_version,
        model_probability=binding.model_probability,
        model_probability_source_version=binding.model_probability_source_version,
        model_promotion_decision_id=binding.model_promotion_decision_id,
    )


def _binding_components(binding: ScenarioForecastBinding) -> tuple[str, ...]:
    return (
        str(binding.scenario_revision_id),
        "" if binding.scenario_set_revision_id is None else str(binding.scenario_set_revision_id),
        str(binding.subjective_probability),
        binding.subjective_probability_source_version,
        "" if binding.model_probability is None else str(binding.model_probability),
        binding.model_probability_source_version or "",
        binding.model_promotion_decision_id or "",
    )


def _uuid_tuple(values: object, field_name: str) -> tuple[UUID, ...]:
    if not isinstance(values, tuple) or not values:
        raise ValueError(f"{field_name} must be a non-empty tuple")
    if any(type(value) is not UUID for value in values):
        raise ValueError(f"{field_name} must contain exact UUID values")
    normalized = tuple(sorted(values, key=str))
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} contains duplicates")
    return normalized


class ForecastCalibrationResolution(StrEnum):
    """Exhaustive state of one expected forecast at one PIT cutoff."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    CENSORED = "censored"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class ForecastCalibrationInvalidationEvidence:
    """Raw invalidation evidence attached to an expected forecast member."""

    evidence_version: str
    invalidated_at: datetime
    invalidation_rule_version: str
    evidence_refs: tuple[str, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        evidence_version: str,
        invalidated_at: datetime,
        invalidation_rule_version: str,
        evidence_refs: tuple[str, ...],
    ) -> ForecastCalibrationInvalidationEvidence:
        """Create and seal immutable invalidation evidence."""

        version = _token(evidence_version, "evidence_version", maximum=64)
        clock = _aware(invalidated_at, "invalidated_at")
        rule = _token(invalidation_rule_version, "invalidation_rule_version", maximum=128)
        refs = cls._validated_refs(evidence_refs)
        content_hash = _hash_components(version, _utc_text(clock), rule, *refs)
        return cls(version, clock, rule, refs, content_hash)

    @staticmethod
    def _validated_refs(values: object) -> tuple[str, ...]:
        if not isinstance(values, tuple) or not values:
            raise ValueError("evidence_refs must be a non-empty tuple")
        normalized = tuple(_token(value, "evidence_ref", maximum=512) for value in values)
        if normalized != tuple(sorted(set(normalized))):
            raise ValueError("evidence_refs must be unique and sorted")
        return normalized

    def __post_init__(self) -> None:
        version = _token(self.evidence_version, "evidence_version", maximum=64)
        clock = _aware(self.invalidated_at, "invalidated_at")
        rule = _token(self.invalidation_rule_version, "invalidation_rule_version", maximum=128)
        refs = self._validated_refs(self.evidence_refs)
        expected = _hash_components(version, _utc_text(clock), rule, *refs)
        if _digest(self.content_hash, "content_hash") != expected:
            raise ValueError("invalidation content_hash does not match evidence")

    def validated_copy(self) -> ForecastCalibrationInvalidationEvidence:
        """Rebuild this value without trusting an instance validator."""

        if type(self) is not ForecastCalibrationInvalidationEvidence:
            raise ValueError("invalidation evidence must use the exact domain type")
        return ForecastCalibrationInvalidationEvidence.create(
            evidence_version=self.evidence_version,
            invalidated_at=self.invalidated_at,
            invalidation_rule_version=self.invalidation_rule_version,
            evidence_refs=self.evidence_refs,
        )


@dataclass(frozen=True)
class ForecastCalibrationExpectedMember:
    """One immutable Forecast Ledger member in a calibration denominator."""

    source_version: str
    entry_id: str
    observation_version: str
    forecast_group_id: str
    binding: ScenarioForecastBinding
    pit_manifest_id: str
    pit_manifest_version: str
    pit_manifest_hash: str
    censoring_rule_version: str
    published_at: datetime
    horizon_end: datetime
    entry_recorded_at: datetime
    outcome_evidence_valid_until: datetime
    evidence_ref: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        entry_id: str,
        observation_version: str,
        forecast_group_id: str,
        binding: ScenarioForecastBinding,
        pit_manifest_id: str,
        pit_manifest_version: str,
        pit_manifest_hash: str,
        censoring_rule_version: str,
        published_at: datetime,
        horizon_end: datetime,
        entry_recorded_at: datetime,
        outcome_evidence_valid_until: datetime,
        evidence_ref: str,
    ) -> ForecastCalibrationExpectedMember:
        """Normalize and seal one expected member."""

        values = cls._normalize(
            entry_id=entry_id,
            observation_version=observation_version,
            forecast_group_id=forecast_group_id,
            binding=binding,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_version=pit_manifest_version,
            pit_manifest_hash=pit_manifest_hash,
            censoring_rule_version=censoring_rule_version,
            published_at=published_at,
            horizon_end=horizon_end,
            entry_recorded_at=entry_recorded_at,
            outcome_evidence_valid_until=outcome_evidence_valid_until,
            evidence_ref=evidence_ref,
        )
        return cls(EXPECTED_MEMBER_VERSION, *values, cls._seal(*values))

    @classmethod
    def _normalize(
        cls,
        *,
        entry_id: object,
        observation_version: object,
        forecast_group_id: object,
        binding: object,
        pit_manifest_id: object,
        pit_manifest_version: object,
        pit_manifest_hash: object,
        censoring_rule_version: object,
        published_at: object,
        horizon_end: object,
        entry_recorded_at: object,
        outcome_evidence_valid_until: object,
        evidence_ref: object,
    ) -> tuple[
        str,
        str,
        str,
        ScenarioForecastBinding,
        str,
        str,
        str,
        str,
        datetime,
        datetime,
        datetime,
        datetime,
        str,
    ]:
        entry = _token(entry_id, "entry_id", maximum=128)
        observation = _token(observation_version, "observation_version", maximum=128)
        group = _token(forecast_group_id, "forecast_group_id", maximum=128)
        binding_copy = _binding_copy(binding)
        manifest_id = _token(pit_manifest_id, "pit_manifest_id", maximum=128)
        manifest_version = _token(pit_manifest_version, "pit_manifest_version", maximum=128)
        manifest_hash = _digest(pit_manifest_hash, "pit_manifest_hash")
        censoring = _token(censoring_rule_version, "censoring_rule_version", maximum=128)
        published = _aware(published_at, "published_at")
        horizon = _aware(horizon_end, "horizon_end")
        recorded = _aware(entry_recorded_at, "entry_recorded_at")
        valid_until = _aware(outcome_evidence_valid_until, "outcome_evidence_valid_until")
        ref = _token(evidence_ref, "evidence_ref", maximum=512)
        if not published < horizon:
            raise ValueError("published_at must precede horizon_end")
        if recorded < published:
            raise ValueError("entry_recorded_at cannot precede published_at")
        if valid_until <= horizon:
            raise ValueError("outcome_evidence_valid_until must follow horizon_end")
        return (
            entry,
            observation,
            group,
            binding_copy,
            manifest_id,
            manifest_version,
            manifest_hash,
            censoring,
            published,
            horizon,
            recorded,
            valid_until,
            ref,
        )

    @staticmethod
    def _seal(
        entry_id: str,
        observation_version: str,
        forecast_group_id: str,
        binding: ScenarioForecastBinding,
        pit_manifest_id: str,
        pit_manifest_version: str,
        pit_manifest_hash: str,
        censoring_rule_version: str,
        published_at: datetime,
        horizon_end: datetime,
        entry_recorded_at: datetime,
        outcome_evidence_valid_until: datetime,
        evidence_ref: str,
    ) -> str:
        return _hash_components(
            EXPECTED_MEMBER_VERSION,
            entry_id,
            observation_version,
            forecast_group_id,
            *_binding_components(binding),
            pit_manifest_id,
            pit_manifest_version,
            pit_manifest_hash,
            censoring_rule_version,
            _utc_text(published_at),
            _utc_text(horizon_end),
            _utc_text(entry_recorded_at),
            _utc_text(outcome_evidence_valid_until),
            evidence_ref,
        )

    def __post_init__(self) -> None:
        if self.source_version != EXPECTED_MEMBER_VERSION:
            raise ValueError("unsupported expected-member source_version")
        values = self._normalize(
            entry_id=self.entry_id,
            observation_version=self.observation_version,
            forecast_group_id=self.forecast_group_id,
            binding=self.binding,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_version=self.pit_manifest_version,
            pit_manifest_hash=self.pit_manifest_hash,
            censoring_rule_version=self.censoring_rule_version,
            published_at=self.published_at,
            horizon_end=self.horizon_end,
            entry_recorded_at=self.entry_recorded_at,
            outcome_evidence_valid_until=self.outcome_evidence_valid_until,
            evidence_ref=self.evidence_ref,
        )
        if _digest(self.content_hash, "content_hash") != self._seal(*values):
            raise ValueError("expected-member content_hash does not match source")

    def validated_copy(self) -> ForecastCalibrationExpectedMember:
        """Rebuild this member and recursively validate its binding."""

        if type(self) is not ForecastCalibrationExpectedMember:
            raise ValueError("expected member must use the exact domain type")
        return ForecastCalibrationExpectedMember.create(
            entry_id=self.entry_id,
            observation_version=self.observation_version,
            forecast_group_id=self.forecast_group_id,
            binding=self.binding,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_version=self.pit_manifest_version,
            pit_manifest_hash=self.pit_manifest_hash,
            censoring_rule_version=self.censoring_rule_version,
            published_at=self.published_at,
            horizon_end=self.horizon_end,
            entry_recorded_at=self.entry_recorded_at,
            outcome_evidence_valid_until=self.outcome_evidence_valid_until,
            evidence_ref=self.evidence_ref,
        )


@dataclass(frozen=True)
class ForecastCalibrationSampleSource:
    """Owner-supplied, outcome-free definition source for a sample window."""

    source_version: str
    sample_id: str
    sample_version: str
    scope_content_hash: str
    scenario_set_revision_id: UUID
    scenario_revision_ids: tuple[UUID, ...]
    forecast_horizon: timedelta
    censoring_rule_version: str
    sample_window_start: datetime
    sample_window_end: datetime
    available_at: datetime
    valid_until: datetime
    evidence_ref: str
    members: tuple[ForecastCalibrationExpectedMember, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        sample_id: str,
        sample_version: str,
        scope_content_hash: str,
        scenario_set_revision_id: UUID,
        scenario_revision_ids: tuple[UUID, ...],
        forecast_horizon: timedelta,
        censoring_rule_version: str,
        sample_window_start: datetime,
        sample_window_end: datetime,
        available_at: datetime,
        valid_until: datetime,
        evidence_ref: str,
        members: tuple[ForecastCalibrationExpectedMember, ...],
    ) -> ForecastCalibrationSampleSource:
        """Create an outcome-free definition with a complete denominator."""

        values = cls._normalize(
            sample_id=sample_id,
            sample_version=sample_version,
            scope_content_hash=scope_content_hash,
            scenario_set_revision_id=scenario_set_revision_id,
            scenario_revision_ids=scenario_revision_ids,
            forecast_horizon=forecast_horizon,
            censoring_rule_version=censoring_rule_version,
            sample_window_start=sample_window_start,
            sample_window_end=sample_window_end,
            available_at=available_at,
            valid_until=valid_until,
            evidence_ref=evidence_ref,
            members=members,
        )
        return cls(SOURCE_VERSION, *values, cls._seal(*values))

    @classmethod
    def _normalize(
        cls,
        *,
        sample_id: object,
        sample_version: object,
        scope_content_hash: object,
        scenario_set_revision_id: object,
        scenario_revision_ids: object,
        forecast_horizon: object,
        censoring_rule_version: object,
        sample_window_start: object,
        sample_window_end: object,
        available_at: object,
        valid_until: object,
        evidence_ref: object,
        members: object,
    ) -> tuple[
        str,
        str,
        str,
        UUID,
        tuple[UUID, ...],
        timedelta,
        str,
        datetime,
        datetime,
        datetime,
        datetime,
        str,
        tuple[ForecastCalibrationExpectedMember, ...],
    ]:
        identity = _token(sample_id, "sample_id", maximum=128)
        version = _token(sample_version, "sample_version", maximum=128)
        scope_hash = _digest(scope_content_hash, "scope_content_hash")
        if type(scenario_set_revision_id) is not UUID:
            raise ValueError("scenario_set_revision_id must be an exact UUID")
        assert isinstance(scenario_set_revision_id, UUID)
        revisions = _uuid_tuple(scenario_revision_ids, "scenario_revision_ids")
        horizon = _positive_duration(forecast_horizon, "forecast_horizon")
        censoring = _token(censoring_rule_version, "censoring_rule_version", maximum=128)
        window_start = _aware(sample_window_start, "sample_window_start")
        window_end = _aware(sample_window_end, "sample_window_end")
        available = _aware(available_at, "available_at")
        expires = _aware(valid_until, "valid_until")
        ref = _token(evidence_ref, "evidence_ref", maximum=512)
        if not window_start < window_end <= available < expires:
            raise ValueError(
                "sample clocks must satisfy window_start < window_end <= available_at < valid_until"
            )
        if not isinstance(members, tuple) or not members:
            raise ValueError("members must be a non-empty tuple")
        rebuilt: list[ForecastCalibrationExpectedMember] = []
        for member in members:
            if type(member) is not ForecastCalibrationExpectedMember:
                raise ValueError("members must use the exact expected-member type")
            assert isinstance(member, ForecastCalibrationExpectedMember)
            rebuilt.append(member.validated_copy())
        canonical_members = tuple(sorted(rebuilt, key=lambda item: item.entry_id))
        if len({item.entry_id for item in canonical_members}) != len(canonical_members):
            raise ValueError("members contain duplicate entry_id values")
        if len(
            {item.observation_version + "\x00" + item.entry_id for item in canonical_members}
        ) != len(canonical_members):
            raise ValueError("members contain duplicate observation identities")
        expected_revisions = set(revisions)
        groups: dict[str, set[UUID]] = {}
        for member in canonical_members:
            if member.binding.scenario_set_revision_id != scenario_set_revision_id:
                raise ValueError("member scenario-set binding does not match sample")
            if member.binding.scenario_revision_id not in expected_revisions:
                raise ValueError("member scenario revision is outside the sample scope")
            if member.censoring_rule_version != censoring:
                raise ValueError("member censoring rule does not match sample")
            if member.horizon_end - member.published_at != horizon:
                raise ValueError("member forecast horizon does not match sample")
            if not window_start <= member.published_at < window_end:
                raise ValueError("member publication is outside the sample window")
            if member.entry_recorded_at > available:
                raise ValueError("source available_at precedes an expected member")
            if member.outcome_evidence_valid_until < expires:
                raise ValueError("member outcome evidence expires before the sample")
            groups.setdefault(member.forecast_group_id, set()).add(
                member.binding.scenario_revision_id
            )
        if any(group != expected_revisions for group in groups.values()):
            raise ValueError("each forecast group must contain the complete scenario membership")
        return (
            identity,
            version,
            scope_hash,
            scenario_set_revision_id,
            revisions,
            horizon,
            censoring,
            window_start,
            window_end,
            available,
            expires,
            ref,
            canonical_members,
        )

    @staticmethod
    def _seal(*values: object) -> str:
        sample_id = str(values[0])
        sample_version = str(values[1])
        scope_hash = str(values[2])
        scenario_set_revision_id = str(values[3])
        revisions = values[4]
        horizon = values[5]
        clocks = values[7:11]
        members = values[12]
        assert isinstance(revisions, tuple)
        assert isinstance(horizon, timedelta)
        assert all(isinstance(value, datetime) for value in clocks)
        assert isinstance(members, tuple)
        return _hash_components(
            SOURCE_VERSION,
            sample_id,
            sample_version,
            scope_hash,
            scenario_set_revision_id,
            *(str(value) for value in revisions),
            str(horizon.total_seconds()),
            str(values[6]),
            *(_utc_text(value) for value in clocks if isinstance(value, datetime)),
            str(values[11]),
            *(
                member.content_hash
                for member in members
                if isinstance(member, ForecastCalibrationExpectedMember)
            ),
        )

    def __post_init__(self) -> None:
        if self.source_version != SOURCE_VERSION:
            raise ValueError("unsupported calibration source_version")
        values = self._normalize(
            sample_id=self.sample_id,
            sample_version=self.sample_version,
            scope_content_hash=self.scope_content_hash,
            scenario_set_revision_id=self.scenario_set_revision_id,
            scenario_revision_ids=self.scenario_revision_ids,
            forecast_horizon=self.forecast_horizon,
            censoring_rule_version=self.censoring_rule_version,
            sample_window_start=self.sample_window_start,
            sample_window_end=self.sample_window_end,
            available_at=self.available_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
            members=self.members,
        )
        if _digest(self.content_hash, "content_hash") != self._seal(*values):
            raise ValueError("calibration source content_hash does not match source")

    def validated_copy(self) -> ForecastCalibrationSampleSource:
        """Rebuild the complete source and all nested members."""

        if type(self) is not ForecastCalibrationSampleSource:
            raise ValueError("sample source must use the exact domain type")
        return ForecastCalibrationSampleSource.create(
            sample_id=self.sample_id,
            sample_version=self.sample_version,
            scope_content_hash=self.scope_content_hash,
            scenario_set_revision_id=self.scenario_set_revision_id,
            scenario_revision_ids=self.scenario_revision_ids,
            forecast_horizon=self.forecast_horizon,
            censoring_rule_version=self.censoring_rule_version,
            sample_window_start=self.sample_window_start,
            sample_window_end=self.sample_window_end,
            available_at=self.available_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
            members=self.members,
        )


@dataclass(frozen=True)
class ForecastCalibrationSampleDefinition:
    """Registered canonical definition for one calibration sample."""

    definition_version: str
    source: ForecastCalibrationSampleSource
    registered_at: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        source: ForecastCalibrationSampleSource,
        registered_at: datetime,
    ) -> ForecastCalibrationSampleDefinition:
        """Register a validated source without adding outcome facts."""

        if type(source) is not ForecastCalibrationSampleSource:
            raise ValueError("source must use the exact calibration source type")
        source_copy = source.validated_copy()
        clock = _aware(registered_at, "registered_at")
        if not source_copy.available_at <= clock < source_copy.valid_until:
            raise ValueError("registered_at must be within source validity")
        content_hash = _hash_components(
            DEFINITION_VERSION, source_copy.content_hash, _utc_text(clock)
        )
        return cls(DEFINITION_VERSION, source_copy, clock, content_hash)

    def __post_init__(self) -> None:
        if self.definition_version != DEFINITION_VERSION:
            raise ValueError("unsupported definition_version")
        if type(self.source) is not ForecastCalibrationSampleSource:
            raise ValueError("source must use the exact calibration source type")
        source_copy = self.source.validated_copy()
        clock = _aware(self.registered_at, "registered_at")
        if not source_copy.available_at <= clock < source_copy.valid_until:
            raise ValueError("registered_at must be within source validity")
        expected = _hash_components(DEFINITION_VERSION, source_copy.content_hash, _utc_text(clock))
        if _digest(self.content_hash, "content_hash") != expected:
            raise ValueError("definition content_hash does not match source")

    @property
    def research_only(self) -> bool:
        """Declare that this evidence is not a production decision output."""

        return True

    @property
    def must_not_use_for_decision(self) -> bool:
        """Prevent calibration evidence from becoming current advice."""

        return True

    @property
    def must_not_execute(self) -> bool:
        """Prevent calibration evidence from reaching execution."""

        return True

    def validated_copy(self) -> ForecastCalibrationSampleDefinition:
        """Rebuild this definition recursively."""

        if type(self) is not ForecastCalibrationSampleDefinition:
            raise ValueError("definition must use the exact domain type")
        return ForecastCalibrationSampleDefinition.create(
            source=self.source,
            registered_at=self.registered_at,
        )


@dataclass(frozen=True)
class ForecastCalibrationEntryOwnerRecord:
    """Exact reread of one immutable Forecast Ledger entry and outcome."""

    source_version: str
    entry_id: str
    binding: ScenarioForecastBinding
    pit_manifest_id: str
    published_at: datetime
    horizon_end: datetime
    entry_recorded_at: datetime
    resolution: ForecastCalibrationResolution
    scenario_realized: bool | None
    outcome_recorded_at: datetime | None
    outcome_source_type: str | None
    outcome_source_hash: str | None
    invalidation: ForecastCalibrationInvalidationEvidence | None
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        entry_id: str,
        binding: ScenarioForecastBinding,
        pit_manifest_id: str,
        published_at: datetime,
        horizon_end: datetime,
        entry_recorded_at: datetime,
        resolution: ForecastCalibrationResolution,
        scenario_realized: bool | None,
        outcome_recorded_at: datetime | None,
        outcome_source_type: str | None,
        outcome_source_hash: str | None,
        invalidation: ForecastCalibrationInvalidationEvidence | None,
    ) -> ForecastCalibrationEntryOwnerRecord:
        """Create a sealed owner record with an explicit resolution state."""

        values = cls._normalize(
            entry_id=entry_id,
            binding=binding,
            pit_manifest_id=pit_manifest_id,
            published_at=published_at,
            horizon_end=horizon_end,
            entry_recorded_at=entry_recorded_at,
            resolution=resolution,
            scenario_realized=scenario_realized,
            outcome_recorded_at=outcome_recorded_at,
            outcome_source_type=outcome_source_type,
            outcome_source_hash=outcome_source_hash,
            invalidation=invalidation,
        )
        return cls(OWNER_RECORD_VERSION, *values, cls._seal(*values))

    @classmethod
    def _normalize(
        cls,
        *,
        entry_id: object,
        binding: object,
        pit_manifest_id: object,
        published_at: object,
        horizon_end: object,
        entry_recorded_at: object,
        resolution: object,
        scenario_realized: object,
        outcome_recorded_at: object,
        outcome_source_type: object,
        outcome_source_hash: object,
        invalidation: object,
    ) -> tuple[
        str,
        ScenarioForecastBinding,
        str,
        datetime,
        datetime,
        datetime,
        ForecastCalibrationResolution,
        bool | None,
        datetime | None,
        str | None,
        str | None,
        ForecastCalibrationInvalidationEvidence | None,
    ]:
        entry = _token(entry_id, "entry_id", maximum=128)
        binding_copy = _binding_copy(binding)
        manifest_id = _token(pit_manifest_id, "pit_manifest_id", maximum=128)
        published = _aware(published_at, "published_at")
        horizon = _aware(horizon_end, "horizon_end")
        entry_clock = _aware(entry_recorded_at, "entry_recorded_at")
        if type(resolution) is not ForecastCalibrationResolution:
            raise ValueError("resolution must use the exact enum type")
        assert isinstance(resolution, ForecastCalibrationResolution)
        if type(scenario_realized) is not bool and scenario_realized is not None:
            raise ValueError("scenario_realized must be bool or None")
        outcome_clock = (
            None
            if outcome_recorded_at is None
            else _aware(outcome_recorded_at, "outcome_recorded_at")
        )
        source_type = (
            None
            if outcome_source_type is None
            else _token(outcome_source_type, "outcome_source_type", maximum=128)
        )
        source_hash = (
            None
            if outcome_source_hash is None
            else _digest(outcome_source_hash, "outcome_source_hash")
        )
        invalidation_copy: ForecastCalibrationInvalidationEvidence | None
        if invalidation is None:
            invalidation_copy = None
        else:
            if type(invalidation) is not ForecastCalibrationInvalidationEvidence:
                raise ValueError("invalidation must use the exact evidence type")
            assert isinstance(invalidation, ForecastCalibrationInvalidationEvidence)
            invalidation_copy = invalidation.validated_copy()
        if not published < horizon or entry_clock < published:
            raise ValueError("Forecast Ledger clocks are inconsistent")
        raw_fields = (outcome_clock, source_type, source_hash)
        if resolution is ForecastCalibrationResolution.UNRESOLVED:
            if (
                scenario_realized is not None
                or any(value is not None for value in raw_fields)
                or invalidation_copy is not None
            ):
                raise ValueError("unresolved owner record cannot contain outcome evidence")
        elif resolution is ForecastCalibrationResolution.RESOLVED:
            if (
                type(scenario_realized) is not bool
                or any(value is None for value in raw_fields)
                or invalidation_copy is not None
            ):
                raise ValueError(
                    "resolved owner record requires a boolean and raw outcome evidence"
                )
            if outcome_clock is not None and outcome_clock < horizon:
                raise ValueError("resolved outcome cannot precede horizon_end")
        elif resolution is ForecastCalibrationResolution.CENSORED:
            if (
                scenario_realized is not None
                or any(value is None for value in raw_fields)
                or invalidation_copy is not None
            ):
                raise ValueError("censored owner record requires raw censoring evidence")
            if outcome_clock is not None and outcome_clock < horizon:
                raise ValueError("censoring record cannot precede horizon_end")
        else:
            if (
                scenario_realized is not None
                or any(value is None for value in raw_fields)
                or invalidation_copy is None
            ):
                raise ValueError("invalidated owner record requires raw invalidation evidence")
            if (
                invalidation_copy is not None
                and not published <= invalidation_copy.invalidated_at < horizon
            ):
                raise ValueError("invalidation clock must fall before horizon_end")
            if (
                outcome_clock is not None
                and invalidation_copy is not None
                and outcome_clock < invalidation_copy.invalidated_at
            ):
                raise ValueError("outcome_recorded_at cannot precede invalidation evidence")
        return (
            entry,
            binding_copy,
            manifest_id,
            published,
            horizon,
            entry_clock,
            resolution,
            scenario_realized if isinstance(scenario_realized, bool) else None,
            outcome_clock,
            source_type,
            source_hash,
            invalidation_copy,
        )

    @staticmethod
    def _seal(*values: object) -> str:
        binding = values[1]
        assert isinstance(binding, ScenarioForecastBinding)
        invalidation = values[11]
        return _hash_components(
            OWNER_RECORD_VERSION,
            str(values[0]),
            *_binding_components(binding),
            str(values[2]),
            *(_utc_text(value) for value in values[3:6] if isinstance(value, datetime)),
            str(getattr(values[6], "value", values[6])),
            "" if values[7] is None else str(values[7]),
            (
                ""
                if values[8] is None
                else _utc_text(values[8]) if isinstance(values[8], datetime) else str(values[8])
            ),
            "" if values[9] is None else str(values[9]),
            "" if values[10] is None else str(values[10]),
            (
                ""
                if invalidation is None
                else (
                    invalidation.content_hash
                    if isinstance(invalidation, ForecastCalibrationInvalidationEvidence)
                    else str(invalidation)
                )
            ),
        )

    def __post_init__(self) -> None:
        if self.source_version != OWNER_RECORD_VERSION:
            raise ValueError("unsupported owner-record source_version")
        values = self._normalize(
            entry_id=self.entry_id,
            binding=self.binding,
            pit_manifest_id=self.pit_manifest_id,
            published_at=self.published_at,
            horizon_end=self.horizon_end,
            entry_recorded_at=self.entry_recorded_at,
            resolution=self.resolution,
            scenario_realized=self.scenario_realized,
            outcome_recorded_at=self.outcome_recorded_at,
            outcome_source_type=self.outcome_source_type,
            outcome_source_hash=self.outcome_source_hash,
            invalidation=self.invalidation,
        )
        if _digest(self.content_hash, "content_hash") != self._seal(*values):
            raise ValueError("owner-record content_hash does not match source")

    def validated_copy(self) -> ForecastCalibrationEntryOwnerRecord:
        """Rebuild this owner record recursively."""

        if type(self) is not ForecastCalibrationEntryOwnerRecord:
            raise ValueError("owner record must use the exact domain type")
        return ForecastCalibrationEntryOwnerRecord.create(
            entry_id=self.entry_id,
            binding=self.binding,
            pit_manifest_id=self.pit_manifest_id,
            published_at=self.published_at,
            horizon_end=self.horizon_end,
            entry_recorded_at=self.entry_recorded_at,
            resolution=self.resolution,
            scenario_realized=self.scenario_realized,
            outcome_recorded_at=self.outcome_recorded_at,
            outcome_source_type=self.outcome_source_type,
            outcome_source_hash=self.outcome_source_hash,
            invalidation=self.invalidation,
        )


@dataclass(frozen=True)
class ForecastCalibrationSampleMemberReceipt:
    """One expected member joined to its exact owner state."""

    receipt_version: str
    expected: ForecastCalibrationExpectedMember
    owner: ForecastCalibrationEntryOwnerRecord
    recorded_at: datetime
    content_hash: str

    @classmethod
    def from_sources(
        cls,
        *,
        expected: ForecastCalibrationExpectedMember,
        owner: ForecastCalibrationEntryOwnerRecord,
        recorded_at: datetime,
    ) -> ForecastCalibrationSampleMemberReceipt:
        """Join exact expected and owner identities without caller-supplied facts."""

        if type(expected) is not ForecastCalibrationExpectedMember:
            raise ValueError("expected member must use the exact domain type")
        if type(owner) is not ForecastCalibrationEntryOwnerRecord:
            raise ValueError("owner record must use the exact domain type")
        expected_binding = _binding_copy(expected.binding)
        owner_binding = _binding_copy(owner.binding)
        if (
            expected.entry_id != owner.entry_id
            or expected_binding != owner_binding
            or expected.pit_manifest_id != owner.pit_manifest_id
            or expected.published_at != owner.published_at
            or expected.horizon_end != owner.horizon_end
            or expected.entry_recorded_at != owner.entry_recorded_at
        ):
            raise ValueError("owner binding or clocks do not match expected membership")
        expected_copy = expected.validated_copy()
        owner_copy = owner.validated_copy()
        clock = _aware(recorded_at, "recorded_at")
        latest_owner_clock = owner_copy.outcome_recorded_at or owner_copy.entry_recorded_at
        if clock < latest_owner_clock:
            raise ValueError("recorded_at cannot precede raw owner evidence")
        content_hash = _hash_components(
            MEMBER_RECEIPT_VERSION,
            expected_copy.content_hash,
            owner_copy.content_hash,
            _utc_text(clock),
        )
        return cls(MEMBER_RECEIPT_VERSION, expected_copy, owner_copy, clock, content_hash)

    def __post_init__(self) -> None:
        if self.receipt_version != MEMBER_RECEIPT_VERSION:
            raise ValueError("unsupported member receipt_version")
        if type(self.expected) is not ForecastCalibrationExpectedMember:
            raise ValueError("expected member must use the exact domain type")
        if type(self.owner) is not ForecastCalibrationEntryOwnerRecord:
            raise ValueError("owner record must use the exact domain type")
        expected_copy = self.expected.validated_copy()
        owner_copy = self.owner.validated_copy()
        if (
            expected_copy.entry_id != owner_copy.entry_id
            or expected_copy.binding != owner_copy.binding
            or expected_copy.pit_manifest_id != owner_copy.pit_manifest_id
            or expected_copy.published_at != owner_copy.published_at
            or expected_copy.horizon_end != owner_copy.horizon_end
            or expected_copy.entry_recorded_at != owner_copy.entry_recorded_at
        ):
            raise ValueError("owner binding or clocks do not match expected membership")
        clock = _aware(self.recorded_at, "recorded_at")
        latest_owner_clock = owner_copy.outcome_recorded_at or owner_copy.entry_recorded_at
        if clock < latest_owner_clock:
            raise ValueError("recorded_at cannot precede raw owner evidence")
        expected_hash = _hash_components(
            MEMBER_RECEIPT_VERSION,
            expected_copy.content_hash,
            owner_copy.content_hash,
            _utc_text(clock),
        )
        if _digest(self.content_hash, "content_hash") != expected_hash:
            raise ValueError("member receipt content_hash does not match sources")

    @property
    def entry_id(self) -> str:
        """Return the immutable Forecast Ledger entry identity."""

        return self.expected.entry_id

    @property
    def resolution(self) -> ForecastCalibrationResolution:
        """Return the explicit owner resolution state."""

        return self.owner.resolution

    @property
    def scenario_realized(self) -> bool | None:
        """Return the raw boolean only for resolved observations."""

        return self.owner.scenario_realized

    @property
    def outcome_recorded_at(self) -> datetime | None:
        """Return the owner outcome clock without request-time substitution."""

        return self.owner.outcome_recorded_at

    @property
    def invalidation(self) -> ForecastCalibrationInvalidationEvidence | None:
        """Return structured invalidation evidence when present."""

        return self.owner.invalidation

    def validated_copy(self) -> ForecastCalibrationSampleMemberReceipt:
        """Rebuild this member receipt recursively."""

        if type(self) is not ForecastCalibrationSampleMemberReceipt:
            raise ValueError("member receipt must use the exact domain type")
        return ForecastCalibrationSampleMemberReceipt.from_sources(
            expected=self.expected,
            owner=self.owner,
            recorded_at=self.recorded_at,
        )


@dataclass(frozen=True)
class ForecastCalibrationSampleReceipt:
    """PIT receipt containing every member of a canonical definition."""

    receipt_version: str
    receipt_id: str
    definition: ForecastCalibrationSampleDefinition
    pit_as_of: datetime
    recorded_at: datetime
    members: tuple[ForecastCalibrationSampleMemberReceipt, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        definition: ForecastCalibrationSampleDefinition,
        pit_as_of: datetime,
        recorded_at: datetime,
        members: tuple[ForecastCalibrationSampleMemberReceipt, ...],
    ) -> ForecastCalibrationSampleReceipt:
        """Create an exhaustive PIT receipt for a registered definition."""

        if type(definition) is not ForecastCalibrationSampleDefinition:
            raise ValueError("definition must use the exact domain type")
        definition_copy = definition.validated_copy()
        pit_clock = _aware(pit_as_of, "pit_as_of")
        record_clock = _aware(recorded_at, "recorded_at")
        if (
            not definition_copy.registered_at
            <= pit_clock
            <= record_clock
            < definition_copy.source.valid_until
        ):
            raise ValueError("receipt clocks fall outside definition validity")
        if not isinstance(members, tuple):
            raise ValueError("members must be a tuple")
        rebuilt: list[ForecastCalibrationSampleMemberReceipt] = []
        for member in members:
            if type(member) is not ForecastCalibrationSampleMemberReceipt:
                raise ValueError("members must use the exact receipt-member type")
            assert isinstance(member, ForecastCalibrationSampleMemberReceipt)
            copy = member.validated_copy()
            if copy.recorded_at != record_clock:
                raise ValueError("member recorded_at must equal receipt recorded_at")
            if copy.outcome_recorded_at is not None and copy.outcome_recorded_at > pit_clock:
                raise ValueError("receipt contains outcome evidence after pit_as_of")
            rebuilt.append(copy)
        canonical = tuple(sorted(rebuilt, key=lambda item: item.entry_id))
        expected_by_id = {
            item.entry_id: item.content_hash for item in definition_copy.source.members
        }
        actual_by_id = {item.entry_id: item.expected.content_hash for item in canonical}
        if len(canonical) != len(actual_by_id) or actual_by_id != expected_by_id:
            raise ValueError("receipt members must exactly equal the expected membership")
        receipt_id = _hash_components(
            definition_copy.source.sample_id,
            definition_copy.source.sample_version,
            definition_copy.content_hash,
            _utc_text(pit_clock),
        )
        content_hash = _hash_components(
            RECEIPT_VERSION,
            receipt_id,
            definition_copy.content_hash,
            _utc_text(pit_clock),
            _utc_text(record_clock),
            *(item.content_hash for item in canonical),
        )
        return cls(
            RECEIPT_VERSION,
            receipt_id,
            definition_copy,
            pit_clock,
            record_clock,
            canonical,
            content_hash,
        )

    def __post_init__(self) -> None:
        if self.receipt_version != RECEIPT_VERSION:
            raise ValueError("unsupported sample receipt_version")
        if type(self.definition) is not ForecastCalibrationSampleDefinition:
            raise ValueError("definition must use the exact domain type")
        definition_copy = self.definition.validated_copy()
        pit_clock = _aware(self.pit_as_of, "pit_as_of")
        record_clock = _aware(self.recorded_at, "recorded_at")
        if (
            not definition_copy.registered_at
            <= pit_clock
            <= record_clock
            < definition_copy.source.valid_until
        ):
            raise ValueError("receipt clocks fall outside definition validity")
        if not isinstance(self.members, tuple):
            raise ValueError("members must be a tuple")
        rebuilt_members: list[ForecastCalibrationSampleMemberReceipt] = []
        for member in self.members:
            if type(member) is not ForecastCalibrationSampleMemberReceipt:
                raise ValueError("members must use the exact receipt-member type")
            assert isinstance(member, ForecastCalibrationSampleMemberReceipt)
            copy = member.validated_copy()
            if copy.recorded_at != record_clock:
                raise ValueError("member recorded_at must equal receipt recorded_at")
            if copy.outcome_recorded_at is not None and copy.outcome_recorded_at > pit_clock:
                raise ValueError("receipt contains outcome evidence after pit_as_of")
            rebuilt_members.append(copy)
        canonical = tuple(sorted(rebuilt_members, key=lambda item: item.entry_id))
        expected_by_id = {
            item.entry_id: item.content_hash for item in definition_copy.source.members
        }
        actual_by_id = {item.entry_id: item.expected.content_hash for item in canonical}
        if len(canonical) != len(actual_by_id) or actual_by_id != expected_by_id:
            raise ValueError("receipt members must exactly equal the expected membership")
        expected_receipt_id = _hash_components(
            definition_copy.source.sample_id,
            definition_copy.source.sample_version,
            definition_copy.content_hash,
            _utc_text(pit_clock),
        )
        if self.receipt_id != expected_receipt_id:
            raise ValueError("receipt_id does not match definition and PIT clock")
        expected_content_hash = _hash_components(
            RECEIPT_VERSION,
            expected_receipt_id,
            definition_copy.content_hash,
            _utc_text(pit_clock),
            _utc_text(record_clock),
            *(item.content_hash for item in canonical),
        )
        if _digest(self.content_hash, "content_hash") != expected_content_hash:
            raise ValueError("sample receipt content_hash does not match sources")

    @property
    def research_only(self) -> bool:
        """Declare that this receipt is calibration evidence only."""

        return True

    @property
    def must_not_use_for_decision(self) -> bool:
        """Prevent receipt use as a current decision input."""

        return True

    @property
    def must_not_execute(self) -> bool:
        """Prevent receipt use as an execution instruction."""

        return True

    def validated_copy(self) -> ForecastCalibrationSampleReceipt:
        """Rebuild this receipt and its complete nested graph."""

        if type(self) is not ForecastCalibrationSampleReceipt:
            raise ValueError("sample receipt must use the exact domain type")
        return ForecastCalibrationSampleReceipt.create(
            definition=self.definition,
            pit_as_of=self.pit_as_of,
            recorded_at=self.recorded_at,
            members=self.members,
        )
