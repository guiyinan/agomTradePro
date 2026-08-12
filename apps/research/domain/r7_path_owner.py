"""Canonical raw-source owner for R7 scenario path research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from apps.research.domain.scenario_probability_contracts import ScenarioResearchScope
from apps.research.domain.scenario_research_evidence import (
    ConditionalProbabilityEvidence,
    MultiPeriodShockEvidence,
    PointInTimeManifestFeature,
    PointInTimeManifestReference,
    ScenarioPathStudyEvidence,
    TransitionProbabilityEvidence,
)
from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_text,
    require_token,
)


def _hash(*components: str) -> str:
    value: object = hash_components(*components)
    if type(value) is not str:
        raise TypeError("R7 owner hash function returned another type")
    return value


def _utc_text(value: datetime, label: str) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _duration_text(value: timedelta, label: str) -> str:
    if type(value) is not timedelta:
        raise ValueError(f"{label} must be an exact timedelta")
    return str(value.total_seconds())


def _decimal(value: Decimal, label: str, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{label} must be an exact finite Decimal")
    if positive and value <= 0:
        raise ValueError(f"{label} must be positive")
    return value


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _positive_int(value: int, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be an exact positive integer")
    return value


def _evidence_refs(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if type(values) is not tuple or not values:
        raise ValueError(f"{label} requires evidence references")
    for value in values:
        require_text(value, f"{label} evidence_ref")
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{label} evidence references must be unique and canonical")
    return values


def _copy_scope(value: object) -> ScenarioResearchScope:
    if type(value) is not ScenarioResearchScope:
        raise TypeError("R7 owner scope must use the exact Domain type")
    ScenarioResearchScope.__post_init__(value)
    copied = ScenarioResearchScope.create(
        scope_version=value.scope_version,
        scenario_set_revision_id=value.scenario_set_revision_id,
        scenario_revision_ids=value.scenario_revision_ids,
        forecast_horizon=value.forecast_horizon,
        censoring_rule_version=value.censoring_rule_version,
        path_horizon_periods=value.path_horizon_periods,
        path_initial_state_revision_ids=value.path_initial_state_revision_ids,
    )
    if copied != value:
        raise ValueError("R7 owner scope differs after replay")
    return copied


def _copy_manifest(value: object) -> PointInTimeManifestReference:
    if type(value) is not PointInTimeManifestReference:
        raise TypeError("R7 owner manifest must use the exact Domain type")
    PointInTimeManifestReference.__post_init__(value)
    features: list[PointInTimeManifestFeature] = []
    for item in value.features:
        if type(item) is not PointInTimeManifestFeature:
            raise TypeError("R7 owner manifest feature type differs")
        PointInTimeManifestFeature.__post_init__(item)
        features.append(
            PointInTimeManifestFeature(
                feature_key=item.feature_key,
                source_version=item.source_version,
                available_at=item.available_at,
                vintage_at=item.vintage_at,
                content_hash=item.content_hash,
            )
        )
    copied = PointInTimeManifestReference.create(
        manifest_id=value.manifest_id,
        manifest_version=value.manifest_version,
        as_of=value.as_of,
        manifest_hash=value.manifest_hash,
        features=tuple(features),
    )
    if copied != value:
        raise ValueError("R7 owner manifest differs after replay")
    return copied


class PathSampleResolution(StrEnum):
    """Explicit disposition of one expected historical path member."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    CENSORED = "censored"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class PathExpectedSampleMember:
    """One versioned member required by a path sample definition."""

    member_id: str
    member_version: str
    period_index: int
    from_scenario_revision_id: UUID
    condition_key: str
    selector_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        member_id: str,
        member_version: str,
        period_index: int,
        from_scenario_revision_id: UUID,
        condition_key: str,
        selector_hash: str,
    ) -> PathExpectedSampleMember:
        values = (
            member_id,
            member_version,
            period_index,
            from_scenario_revision_id,
            condition_key,
            selector_hash,
        )
        return cls(*values, _path_expected_hash(*values))

    def __post_init__(self) -> None:
        require_token(self.member_id, "path member_id")
        require_token(self.member_version, "path member_version")
        _positive_int(self.period_index, "path member period_index")
        if type(self.from_scenario_revision_id) is not UUID:
            raise ValueError("path member origin must be an exact UUID")
        require_token(self.condition_key, "path member condition_key")
        require_sha256(self.selector_hash, "path member selector_hash")
        require_sha256(self.content_hash, "path expected member content_hash")
        if self.content_hash != _path_expected_hash(
            self.member_id,
            self.member_version,
            self.period_index,
            self.from_scenario_revision_id,
            self.condition_key,
            self.selector_hash,
        ):
            raise ValueError("path expected member content_hash mismatch")

    def validated_copy(self) -> PathExpectedSampleMember:
        if type(self) is not PathExpectedSampleMember:
            raise TypeError("path expected member type differs")
        copied = PathExpectedSampleMember.create(
            member_id=self.member_id,
            member_version=self.member_version,
            period_index=self.period_index,
            from_scenario_revision_id=self.from_scenario_revision_id,
            condition_key=self.condition_key,
            selector_hash=self.selector_hash,
        )
        if copied != self:
            raise ValueError("path expected member differs after replay")
        return copied


def _path_expected_hash(
    member_id: str,
    member_version: str,
    period_index: int,
    origin: UUID,
    condition_key: str,
    selector_hash: str,
) -> str:
    return _hash(
        "r7-path-expected-member.v1",
        member_id,
        member_version,
        str(period_index),
        str(origin),
        condition_key,
        selector_hash,
    )


@dataclass(frozen=True)
class PathShockRule:
    """One expected raw shock slot in the path definition."""

    period_index: int
    scenario_revision_id: UUID
    period_start: datetime
    period_end: datetime
    shock_key: str
    unit: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        period_index: int,
        scenario_revision_id: UUID,
        period_start: datetime,
        period_end: datetime,
        shock_key: str,
        unit: str,
    ) -> PathShockRule:
        values = (period_index, scenario_revision_id, period_start, period_end, shock_key, unit)
        return cls(*values, _path_shock_rule_hash(*values))

    def __post_init__(self) -> None:
        _positive_int(self.period_index, "path shock period_index")
        if type(self.scenario_revision_id) is not UUID:
            raise ValueError("path shock scenario revision must be an exact UUID")
        _utc_text(self.period_start, "path shock period_start")
        _utc_text(self.period_end, "path shock period_end")
        if self.period_end <= self.period_start:
            raise ValueError("path shock period is empty")
        require_token(self.shock_key, "path shock_key")
        require_text(self.unit, "path shock unit", maximum=64)
        require_sha256(self.content_hash, "path shock rule content_hash")
        if self.content_hash != _path_shock_rule_hash(
            self.period_index,
            self.scenario_revision_id,
            self.period_start,
            self.period_end,
            self.shock_key,
            self.unit,
        ):
            raise ValueError("path shock rule content_hash mismatch")

    def validated_copy(self) -> PathShockRule:
        if type(self) is not PathShockRule:
            raise TypeError("path shock rule type differs")
        copied = PathShockRule.create(
            period_index=self.period_index,
            scenario_revision_id=self.scenario_revision_id,
            period_start=self.period_start,
            period_end=self.period_end,
            shock_key=self.shock_key,
            unit=self.unit,
        )
        if copied != self:
            raise ValueError("path shock rule differs after replay")
        return copied


def _path_shock_rule_hash(
    period: int,
    revision: UUID,
    start: datetime,
    end: datetime,
    key: str,
    unit: str,
) -> str:
    return _hash(
        "r7-path-shock-rule.v1",
        str(period),
        str(revision),
        _utc_text(start, "path shock period_start"),
        _utc_text(end, "path shock period_end"),
        key,
        unit,
    )


@dataclass(frozen=True)
class ScenarioPathDefinition:
    """Research-owned expected membership and shock definition for path evidence."""

    definition_id: str
    definition_version: str
    study_version: str
    scope: ScenarioResearchScope
    source_version: str
    sample_definition_version: str
    expected_members: tuple[PathExpectedSampleMember, ...]
    shock_rules: tuple[PathShockRule, ...]
    probability_sum_tolerance: Decimal
    activated_at: datetime
    valid_until: datetime
    evidence_refs: tuple[str, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        definition_id: str,
        definition_version: str,
        study_version: str,
        scope: ScenarioResearchScope,
        source_version: str,
        sample_definition_version: str,
        expected_members: tuple[PathExpectedSampleMember, ...],
        shock_rules: tuple[PathShockRule, ...],
        probability_sum_tolerance: Decimal,
        activated_at: datetime,
        valid_until: datetime,
        evidence_refs: tuple[str, ...],
    ) -> ScenarioPathDefinition:
        canonical_scope = _copy_scope(scope)
        members = tuple(
            sorted(
                (_exact_path_expected(item) for item in expected_members),
                key=_path_expected_key,
            )
        )
        rules = tuple(
            sorted((_exact_path_shock_rule(item) for item in shock_rules), key=_path_shock_key)
        )
        refs = tuple(sorted(set(evidence_refs)))
        values = (
            definition_id,
            definition_version,
            study_version,
            canonical_scope,
            source_version,
            sample_definition_version,
            members,
            rules,
            probability_sum_tolerance,
            activated_at,
            valid_until,
            refs,
        )
        return cls(*values, _path_definition_hash(*values))

    def __post_init__(self) -> None:
        for label, value in (
            ("definition_id", self.definition_id),
            ("definition_version", self.definition_version),
            ("study_version", self.study_version),
            ("source_version", self.source_version),
            ("sample_definition_version", self.sample_definition_version),
        ):
            require_token(value, f"path {label}")
        scope = _copy_scope(self.scope)
        members = _exact_path_members(self.expected_members)
        rules = _exact_path_shock_rules(self.shock_rules)
        _decimal(self.probability_sum_tolerance, "path probability_sum_tolerance")
        if not Decimal(0) <= self.probability_sum_tolerance < Decimal(1):
            raise ValueError("path probability_sum_tolerance must be in [0, 1)")
        _utc_text(self.activated_at, "path definition activated_at")
        _utc_text(self.valid_until, "path definition valid_until")
        if self.valid_until <= self.activated_at:
            raise ValueError("path definition validity is empty")
        _evidence_refs(self.evidence_refs, "path definition")
        _validate_path_definition_graph(scope, members, rules)
        require_sha256(self.content_hash, "path definition content_hash")
        if self.content_hash != _path_definition_hash(
            self.definition_id,
            self.definition_version,
            self.study_version,
            scope,
            self.source_version,
            self.sample_definition_version,
            members,
            rules,
            self.probability_sum_tolerance,
            self.activated_at,
            self.valid_until,
            self.evidence_refs,
        ):
            raise ValueError("path definition content_hash mismatch")

    def validated_copy(self) -> ScenarioPathDefinition:
        if type(self) is not ScenarioPathDefinition:
            raise TypeError("path definition type differs")
        copied = ScenarioPathDefinition.create(
            definition_id=self.definition_id,
            definition_version=self.definition_version,
            study_version=self.study_version,
            scope=self.scope,
            source_version=self.source_version,
            sample_definition_version=self.sample_definition_version,
            expected_members=self.expected_members,
            shock_rules=self.shock_rules,
            probability_sum_tolerance=self.probability_sum_tolerance,
            activated_at=self.activated_at,
            valid_until=self.valid_until,
            evidence_refs=self.evidence_refs,
        )
        if copied != self:
            raise ValueError("path definition differs after replay")
        return copied


def _exact_path_expected(value: object) -> PathExpectedSampleMember:
    if type(value) is not PathExpectedSampleMember:
        raise TypeError("path expected member type differs")
    return PathExpectedSampleMember.validated_copy(value)


def _path_expected_key(value: PathExpectedSampleMember) -> tuple[int, str, str]:
    return value.period_index, str(value.from_scenario_revision_id), value.member_id


def _exact_path_members(
    values: tuple[PathExpectedSampleMember, ...],
) -> tuple[PathExpectedSampleMember, ...]:
    if type(values) is not tuple or not values:
        raise ValueError("path definition requires expected membership")
    copied = tuple(_exact_path_expected(item) for item in values)
    if copied != tuple(sorted(copied, key=_path_expected_key)):
        raise ValueError("path expected membership must be canonical")
    if len({item.member_id for item in copied}) != len(copied):
        raise ValueError("path expected membership contains duplicate IDs")
    return copied


def _exact_path_shock_rule(value: object) -> PathShockRule:
    if type(value) is not PathShockRule:
        raise TypeError("path shock rule type differs")
    return PathShockRule.validated_copy(value)


def _path_shock_key(value: PathShockRule) -> tuple[int, str, str]:
    return value.period_index, str(value.scenario_revision_id), value.shock_key


def _exact_path_shock_rules(values: tuple[PathShockRule, ...]) -> tuple[PathShockRule, ...]:
    if type(values) is not tuple or not values:
        raise ValueError("path definition requires shock rules")
    copied = tuple(_exact_path_shock_rule(item) for item in values)
    if copied != tuple(sorted(copied, key=_path_shock_key)):
        raise ValueError("path shock rules must be canonical")
    keys = {_path_shock_key(item) for item in copied}
    if len(keys) != len(copied):
        raise ValueError("path definition contains duplicate shock rules")
    return copied


def _validate_path_definition_graph(
    scope: ScenarioResearchScope,
    members: tuple[PathExpectedSampleMember, ...],
    rules: tuple[PathShockRule, ...],
) -> None:
    periods = set(range(1, scope.path_horizon_periods + 1))
    expected_groups = {
        (period, origin) for period in periods for origin in scope.path_initial_state_revision_ids
    }
    actual_groups = {(item.period_index, item.from_scenario_revision_id) for item in members}
    if actual_groups != expected_groups:
        raise ValueError("path expected membership does not cover every period and initial state")
    if any(item.period_index not in periods for item in members):
        raise ValueError("path expected member period exceeds scope horizon")
    counts = {
        group: sum(
            1 for item in members if (item.period_index, item.from_scenario_revision_id) == group
        )
        for group in expected_groups
    }
    if len(set(counts.values())) != 1:
        raise ValueError("path expected membership must have balanced group denominators")
    rule_periods = {item.period_index for item in rules}
    if rule_periods != periods:
        raise ValueError("path shock rules must cover the exact path horizon")
    if any(item.scenario_revision_id not in scope.scenario_revision_ids for item in rules):
        raise ValueError("path shock rule scenario is outside scope")
    boundaries: dict[int, tuple[datetime, datetime]] = {}
    for item in rules:
        current = (item.period_start, item.period_end)
        prior = boundaries.setdefault(item.period_index, current)
        if prior != current:
            raise ValueError("path shock rules in one period have different boundaries")
    ordered = tuple(boundaries[index] for index in sorted(boundaries))
    for prior, current in zip(ordered, ordered[1:], strict=False):
        if current[0] < prior[1]:
            raise ValueError("path shock periods overlap")


def _path_definition_hash(
    definition_id: str,
    definition_version: str,
    study_version: str,
    scope: ScenarioResearchScope,
    source_version: str,
    sample_definition_version: str,
    members: tuple[PathExpectedSampleMember, ...],
    rules: tuple[PathShockRule, ...],
    tolerance: Decimal,
    activated_at: datetime,
    valid_until: datetime,
    evidence_refs: tuple[str, ...],
) -> str:
    return _hash(
        "r7-scenario-path-definition.v1",
        definition_id,
        definition_version,
        study_version,
        scope.content_hash,
        source_version,
        sample_definition_version,
        *(
            [item.content_hash for item in members]
            + [item.content_hash for item in rules]
            + [
                _decimal_text(tolerance),
                _utc_text(activated_at, "path definition activated_at"),
                _utc_text(valid_until, "path definition valid_until"),
                *evidence_refs,
            ]
        ),
    )


@dataclass(frozen=True)
class PathObservedSampleMember:
    """Raw disposition and target for one exact expected sample member."""

    expected: PathExpectedSampleMember
    resolution: PathSampleResolution
    to_scenario_revision_id: UUID | None
    observed_at: datetime | None
    available_at: datetime
    source_version: str
    source_hash: str
    evidence_ref: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        expected: PathExpectedSampleMember,
        resolution: PathSampleResolution,
        to_scenario_revision_id: UUID | None,
        observed_at: datetime | None,
        available_at: datetime,
        source_version: str,
        source_hash: str,
        evidence_ref: str,
    ) -> PathObservedSampleMember:
        canonical_expected = _exact_path_expected(expected)
        values = (
            canonical_expected,
            resolution,
            to_scenario_revision_id,
            observed_at,
            available_at,
            source_version,
            source_hash,
            evidence_ref,
        )
        return cls(*values, _path_observed_hash(*values))

    def __post_init__(self) -> None:
        expected = _exact_path_expected(self.expected)
        if type(self.resolution) is not PathSampleResolution:
            raise ValueError("path sample resolution must use the exact enum")
        is_resolved = self.resolution is PathSampleResolution.RESOLVED
        has_result = self.to_scenario_revision_id is not None and self.observed_at is not None
        if is_resolved != has_result:
            raise ValueError(
                "resolved path sample must contain an exact target and observation clock"
            )
        if (
            self.to_scenario_revision_id is not None
            and type(self.to_scenario_revision_id) is not UUID
        ):
            raise ValueError("path sample target must be an exact UUID")
        if self.observed_at is not None:
            _utc_text(self.observed_at, "path sample observed_at")
        _utc_text(self.available_at, "path sample available_at")
        if self.observed_at is not None and self.available_at < self.observed_at:
            raise ValueError("path sample cannot be available before it was observed")
        require_token(self.source_version, "path sample source_version")
        require_sha256(self.source_hash, "path sample source_hash")
        require_text(self.evidence_ref, "path sample evidence_ref")
        require_sha256(self.content_hash, "path observed member content_hash")
        if self.content_hash != _path_observed_hash(
            expected,
            self.resolution,
            self.to_scenario_revision_id,
            self.observed_at,
            self.available_at,
            self.source_version,
            self.source_hash,
            self.evidence_ref,
        ):
            raise ValueError("path observed member content_hash mismatch")

    def validated_copy(self) -> PathObservedSampleMember:
        if type(self) is not PathObservedSampleMember:
            raise TypeError("path observed member type differs")
        copied = PathObservedSampleMember.create(
            expected=self.expected,
            resolution=self.resolution,
            to_scenario_revision_id=self.to_scenario_revision_id,
            observed_at=self.observed_at,
            available_at=self.available_at,
            source_version=self.source_version,
            source_hash=self.source_hash,
            evidence_ref=self.evidence_ref,
        )
        if copied != self:
            raise ValueError("path observed member differs after replay")
        return copied


def _path_observed_hash(
    expected: PathExpectedSampleMember,
    resolution: PathSampleResolution,
    target: UUID | None,
    observed_at: datetime | None,
    available_at: datetime,
    source_version: str,
    source_hash: str,
    evidence_ref: str,
) -> str:
    return _hash(
        "r7-path-observed-member.v1",
        expected.content_hash,
        resolution.value,
        str(target or ""),
        _utc_text(observed_at, "path sample observed_at") if observed_at is not None else "",
        _utc_text(available_at, "path sample available_at"),
        source_version,
        source_hash,
        evidence_ref,
    )


@dataclass(frozen=True)
class PathShockObservation:
    """One raw shock magnitude bound to an expected shock rule."""

    rule: PathShockRule
    magnitude: Decimal
    source_version: str
    available_at: datetime
    source_hash: str
    evidence_ref: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        rule: PathShockRule,
        magnitude: Decimal,
        source_version: str,
        available_at: datetime,
        source_hash: str,
        evidence_ref: str,
    ) -> PathShockObservation:
        canonical_rule = _exact_path_shock_rule(rule)
        values = (
            canonical_rule,
            magnitude,
            source_version,
            available_at,
            source_hash,
            evidence_ref,
        )
        return cls(*values, _path_shock_observation_hash(*values))

    def __post_init__(self) -> None:
        rule = _exact_path_shock_rule(self.rule)
        _decimal(self.magnitude, "path shock magnitude")
        require_token(self.source_version, "path shock observation source_version")
        _utc_text(self.available_at, "path shock observation available_at")
        if self.available_at < rule.period_end:
            raise ValueError("path shock cannot be available before its period ends")
        require_sha256(self.source_hash, "path shock observation source_hash")
        require_text(self.evidence_ref, "path shock observation evidence_ref")
        require_sha256(self.content_hash, "path shock observation content_hash")
        if self.content_hash != _path_shock_observation_hash(
            rule,
            self.magnitude,
            self.source_version,
            self.available_at,
            self.source_hash,
            self.evidence_ref,
        ):
            raise ValueError("path shock observation content_hash mismatch")

    def validated_copy(self) -> PathShockObservation:
        if type(self) is not PathShockObservation:
            raise TypeError("path shock observation type differs")
        copied = PathShockObservation.create(
            rule=self.rule,
            magnitude=self.magnitude,
            source_version=self.source_version,
            available_at=self.available_at,
            source_hash=self.source_hash,
            evidence_ref=self.evidence_ref,
        )
        if copied != self:
            raise ValueError("path shock observation differs after replay")
        return copied


def _path_shock_observation_hash(
    rule: PathShockRule,
    magnitude: Decimal,
    source_version: str,
    available_at: datetime,
    source_hash: str,
    evidence_ref: str,
) -> str:
    return _hash(
        "r7-path-shock-observation.v1",
        rule.content_hash,
        _decimal_text(magnitude),
        source_version,
        _utc_text(available_at, "path shock observation available_at"),
        source_hash,
        evidence_ref,
    )


@dataclass(frozen=True)
class ScenarioPathRawSource:
    """Complete raw sample membership and shocks from a canonical source."""

    pit_manifest: PointInTimeManifestReference
    sample_members: tuple[PathObservedSampleMember, ...]
    shocks: tuple[PathShockObservation, ...]
    available_at: datetime
    evidence_refs: tuple[str, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        pit_manifest: PointInTimeManifestReference,
        sample_members: tuple[PathObservedSampleMember, ...],
        shocks: tuple[PathShockObservation, ...],
        available_at: datetime,
        evidence_refs: tuple[str, ...],
        expected_definition: ScenarioPathDefinition | None = None,
    ) -> ScenarioPathRawSource:
        manifest = _copy_manifest(pit_manifest)
        members = tuple(
            sorted((_exact_path_observed(item) for item in sample_members), key=_path_observed_key)
        )
        canonical_shocks = tuple(
            sorted(
                (_exact_path_shock_observation(item) for item in shocks),
                key=lambda item: _path_shock_key(item.rule),
            )
        )
        refs = tuple(sorted(set(evidence_refs)))
        values = (manifest, members, canonical_shocks, available_at, refs)
        source = cls(*values, _path_raw_source_hash(*values))
        if expected_definition is not None:
            _match_path_source(expected_definition.validated_copy(), source)
        return source

    def __post_init__(self) -> None:
        manifest = _copy_manifest(self.pit_manifest)
        members = _exact_path_observed_members(self.sample_members)
        shocks = _exact_path_shock_observations(self.shocks)
        _utc_text(self.available_at, "path raw source available_at")
        if self.available_at < manifest.as_of:
            raise ValueError("path source cannot be available before PIT as_of")
        if any(item.available_at > self.available_at for item in members + shocks):
            raise ValueError("path raw member is future-dated relative to source")
        _evidence_refs(self.evidence_refs, "path raw source")
        require_sha256(self.content_hash, "path raw source content_hash")
        if self.content_hash != _path_raw_source_hash(
            manifest, members, shocks, self.available_at, self.evidence_refs
        ):
            raise ValueError("path raw source content_hash mismatch")

    def validated_copy(self) -> ScenarioPathRawSource:
        if type(self) is not ScenarioPathRawSource:
            raise TypeError("path raw source type differs")
        copied = ScenarioPathRawSource.create(
            pit_manifest=self.pit_manifest,
            sample_members=self.sample_members,
            shocks=self.shocks,
            available_at=self.available_at,
            evidence_refs=self.evidence_refs,
        )
        if copied != self:
            raise ValueError("path raw source differs after replay")
        return copied


def _exact_path_observed(value: object) -> PathObservedSampleMember:
    if type(value) is not PathObservedSampleMember:
        raise TypeError("path observed member type differs")
    return PathObservedSampleMember.validated_copy(value)


def _path_observed_key(value: PathObservedSampleMember) -> tuple[int, str, str]:
    return _path_expected_key(value.expected)


def _exact_path_observed_members(
    values: tuple[PathObservedSampleMember, ...],
) -> tuple[PathObservedSampleMember, ...]:
    if type(values) is not tuple or not values:
        raise ValueError("path raw source requires sample members")
    copied = tuple(_exact_path_observed(item) for item in values)
    if copied != tuple(sorted(copied, key=_path_observed_key)):
        raise ValueError("path raw sample members must be canonical")
    if len({item.expected.member_id for item in copied}) != len(copied):
        raise ValueError("path raw source contains duplicate sample members")
    return copied


def _exact_path_shock_observation(value: object) -> PathShockObservation:
    if type(value) is not PathShockObservation:
        raise TypeError("path shock observation type differs")
    return PathShockObservation.validated_copy(value)


def _exact_path_shock_observations(
    values: tuple[PathShockObservation, ...],
) -> tuple[PathShockObservation, ...]:
    if type(values) is not tuple or not values:
        raise ValueError("path raw source requires shock observations")
    copied = tuple(_exact_path_shock_observation(item) for item in values)
    if copied != tuple(sorted(copied, key=lambda item: _path_shock_key(item.rule))):
        raise ValueError("path shock observations must be canonical")
    if len({_path_shock_key(item.rule) for item in copied}) != len(copied):
        raise ValueError("path raw source contains duplicate shock observations")
    return copied


def _path_raw_source_hash(
    manifest: PointInTimeManifestReference,
    members: tuple[PathObservedSampleMember, ...],
    shocks: tuple[PathShockObservation, ...],
    available_at: datetime,
    evidence_refs: tuple[str, ...],
) -> str:
    return _hash(
        "r7-scenario-path-raw-source.v1",
        manifest.reference_hash,
        *(
            [item.content_hash for item in members]
            + [item.content_hash for item in shocks]
            + [_utc_text(available_at, "path raw source available_at"), *evidence_refs]
        ),
    )


@dataclass(frozen=True)
class ScenarioPathReceipt:
    """Append-only receipt that derives frequencies from resolved raw members."""

    receipt_id: str
    receipt_version: str
    definition: ScenarioPathDefinition
    source: ScenarioPathRawSource
    recorded_at: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        receipt_id: str,
        receipt_version: str,
        definition: ScenarioPathDefinition,
        source: ScenarioPathRawSource,
        recorded_at: datetime,
    ) -> ScenarioPathReceipt:
        canonical_definition = definition.validated_copy()
        canonical_source = source.validated_copy()
        values = (receipt_id, receipt_version, canonical_definition, canonical_source, recorded_at)
        return cls(*values, _path_receipt_hash(*values))

    def __post_init__(self) -> None:
        require_token(self.receipt_id, "path receipt_id")
        require_token(self.receipt_version, "path receipt_version")
        if self.receipt_version != "r7-path-receipt.v1":
            raise ValueError("path receipt version is unsupported")
        definition = _exact_path_definition(self.definition)
        source = _exact_path_source(self.source)
        _utc_text(self.recorded_at, "path receipt recorded_at")
        if not definition.activated_at <= self.recorded_at < definition.valid_until:
            raise ValueError("path definition is not active at receipt time")
        if source.available_at > self.recorded_at:
            raise ValueError("path raw source is future-dated")
        _match_path_source(definition, source)
        require_sha256(self.content_hash, "path receipt content_hash")
        if self.content_hash != _path_receipt_hash(
            self.receipt_id, self.receipt_version, definition, source, self.recorded_at
        ):
            raise ValueError("path receipt content_hash mismatch")

    def validated_copy(self) -> ScenarioPathReceipt:
        if type(self) is not ScenarioPathReceipt:
            raise TypeError("path receipt type differs")
        copied = ScenarioPathReceipt.create(
            receipt_id=self.receipt_id,
            receipt_version=self.receipt_version,
            definition=self.definition,
            source=self.source,
            recorded_at=self.recorded_at,
        )
        if copied != self:
            raise ValueError("path receipt differs after replay")
        return copied

    def to_study_evidence(self) -> ScenarioPathStudyEvidence:
        """Derive conditional and transition frequencies from raw resolved rows."""

        receipt = self.validated_copy()
        definition = receipt.definition
        source = receipt.source
        resolved = tuple(
            item
            for item in source.sample_members
            if item.resolution is PathSampleResolution.RESOLVED
        )
        conditional: list[ConditionalProbabilityEvidence] = []
        transition: list[TransitionProbabilityEvidence] = []
        for period in range(1, definition.scope.path_horizon_periods + 1):
            condition_keys = sorted(
                {
                    item.condition_key
                    for item in definition.expected_members
                    if item.period_index == period
                }
            )
            for condition_key in condition_keys:
                group = tuple(
                    item
                    for item in resolved
                    if item.expected.period_index == period
                    and item.expected.condition_key == condition_key
                )
                _resolved_denominator(group, f"path conditional {period}:{condition_key}")
                for target in definition.scope.scenario_revision_ids:
                    conditional.append(
                        ConditionalProbabilityEvidence(
                            condition_key=condition_key,
                            target_scenario_revision_id=target,
                            probability=_frequency(group, target),
                            observation_count=len(group),
                            source_version=definition.source_version,
                            sample_definition_version=definition.sample_definition_version,
                            pit_manifest_id=source.pit_manifest.manifest_id,
                            pit_manifest_version=source.pit_manifest.manifest_version,
                            pit_manifest_hash=source.pit_manifest.manifest_hash,
                            period_index=period,
                        )
                    )
            for origin in definition.scope.path_initial_state_revision_ids:
                group = tuple(
                    item
                    for item in resolved
                    if item.expected.period_index == period
                    and item.expected.from_scenario_revision_id == origin
                )
                _resolved_denominator(group, f"path transition {period}:{origin}")
                for target in definition.scope.scenario_revision_ids:
                    transition.append(
                        TransitionProbabilityEvidence(
                            from_scenario_revision_id=origin,
                            to_scenario_revision_id=target,
                            horizon_periods=period,
                            probability=_frequency(group, target),
                            observation_count=len(group),
                            source_version=definition.source_version,
                            sample_definition_version=definition.sample_definition_version,
                            pit_manifest_id=source.pit_manifest.manifest_id,
                            pit_manifest_version=source.pit_manifest.manifest_version,
                            pit_manifest_hash=source.pit_manifest.manifest_hash,
                        )
                    )
        shocks = tuple(
            MultiPeriodShockEvidence(
                period_index=item.rule.period_index,
                scenario_revision_id=item.rule.scenario_revision_id,
                period_start=item.rule.period_start,
                period_end=item.rule.period_end,
                shock_key=item.rule.shock_key,
                magnitude=item.magnitude,
                unit=item.rule.unit,
                source_version=item.source_version,
            )
            for item in source.shocks
        )
        return ScenarioPathStudyEvidence.create(
            study_version=definition.study_version,
            scope=definition.scope,
            pit_manifest=source.pit_manifest,
            shocks=shocks,
            conditional_probabilities=tuple(conditional),
            transition_probabilities=tuple(transition),
            generated_at=receipt.recorded_at,
            valid_until=definition.valid_until,
            evidence_refs=tuple(sorted(set(definition.evidence_refs + source.evidence_refs))),
            probability_sum_tolerance=definition.probability_sum_tolerance,
        )


def _exact_path_definition(value: object) -> ScenarioPathDefinition:
    if type(value) is not ScenarioPathDefinition:
        raise TypeError("path definition type differs")
    return ScenarioPathDefinition.validated_copy(value)


def _exact_path_source(value: object) -> ScenarioPathRawSource:
    if type(value) is not ScenarioPathRawSource:
        raise TypeError("path raw source type differs")
    return ScenarioPathRawSource.validated_copy(value)


def _match_path_source(definition: ScenarioPathDefinition, source: ScenarioPathRawSource) -> None:
    expected = {item.member_id: item for item in definition.expected_members}
    actual = {item.expected.member_id: item.expected for item in source.sample_members}
    if actual != expected:
        raise ValueError("path raw source differs from expected membership")
    rules = {_path_shock_key(item): item for item in definition.shock_rules}
    actual_rules = {_path_shock_key(item.rule): item.rule for item in source.shocks}
    if actual_rules != rules:
        raise ValueError("path raw source differs from expected shock rules")
    if any(item.source_version != definition.source_version for item in source.sample_members):
        raise ValueError("path sample source version differs from definition")
    if any(item.source_version != definition.source_version for item in source.shocks):
        raise ValueError("path shock source version differs from definition")
    if any(
        item.to_scenario_revision_id not in definition.scope.scenario_revision_ids
        for item in source.sample_members
        if item.resolution is PathSampleResolution.RESOLVED
    ):
        raise ValueError("path resolved target is outside scenario scope")


def _resolved_denominator(values: tuple[PathObservedSampleMember, ...], label: str) -> None:
    if not values:
        raise ValueError(f"{label} has no resolved denominator")


def _frequency(values: tuple[PathObservedSampleMember, ...], target: UUID) -> Decimal:
    numerator = sum(1 for item in values if item.to_scenario_revision_id == target)
    return Decimal(numerator) / Decimal(len(values))


def _path_receipt_hash(
    receipt_id: str,
    receipt_version: str,
    definition: ScenarioPathDefinition,
    source: ScenarioPathRawSource,
    recorded_at: datetime,
) -> str:
    return _hash(
        "r7-scenario-path-receipt.v1",
        receipt_id,
        receipt_version,
        definition.content_hash,
        source.content_hash,
        _utc_text(recorded_at, "path receipt recorded_at"),
    )


__all__ = [
    "PathExpectedSampleMember",
    "PathObservedSampleMember",
    "PathSampleResolution",
    "PathShockObservation",
    "PathShockRule",
    "ScenarioPathDefinition",
    "ScenarioPathRawSource",
    "ScenarioPathReceipt",
]
