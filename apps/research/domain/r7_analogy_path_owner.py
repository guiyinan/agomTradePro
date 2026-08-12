"""Canonical raw-source owner for R7 historical analogy research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.research.domain.r7_path_owner import (
    PathExpectedSampleMember,
    PathObservedSampleMember,
    PathSampleResolution,
    PathShockObservation,
    PathShockRule,
    ScenarioPathDefinition,
    ScenarioPathRawSource,
    ScenarioPathReceipt,
)
from apps.research.domain.scenario_probability_contracts import ScenarioResearchScope
from apps.research.domain.scenario_research_evidence import (
    HistoricalAnalogyCandidateEvidence,
    HistoricalAnalogyStudyEvidence,
    PointInTimeFeatureValue,
    PointInTimeManifestFeature,
    PointInTimeManifestReference,
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


@dataclass(frozen=True)
class AnalogyFeatureRule:
    """One immutable raw-feature distance rule; it contains no result score."""

    feature_key: str
    unit: str
    weight: Decimal
    scale: Decimal
    content_hash: str

    @classmethod
    def create(
        cls, *, feature_key: str, unit: str, weight: Decimal, scale: Decimal
    ) -> AnalogyFeatureRule:
        return cls(
            feature_key, unit, weight, scale, _analogy_rule_hash(feature_key, unit, weight, scale)
        )

    def __post_init__(self) -> None:
        require_token(self.feature_key, "analogy feature_key")
        require_text(self.unit, "analogy feature unit", maximum=64)
        _decimal(self.weight, "analogy feature weight", positive=True)
        _decimal(self.scale, "analogy feature scale", positive=True)
        require_sha256(self.content_hash, "analogy feature rule content_hash")
        if self.content_hash != _analogy_rule_hash(
            self.feature_key, self.unit, self.weight, self.scale
        ):
            raise ValueError("analogy feature rule content_hash mismatch")

    def validated_copy(self) -> AnalogyFeatureRule:
        if type(self) is not AnalogyFeatureRule:
            raise TypeError("analogy feature rule type differs")
        copied = AnalogyFeatureRule.create(
            feature_key=self.feature_key, unit=self.unit, weight=self.weight, scale=self.scale
        )
        if copied != self:
            raise ValueError("analogy feature rule differs after replay")
        return copied


def _analogy_rule_hash(key: str, unit: str, weight: Decimal, scale: Decimal) -> str:
    return _hash(
        "r7-analogy-feature-rule.v1",
        key,
        unit,
        _decimal_text(weight),
        _decimal_text(scale),
    )


@dataclass(frozen=True)
class AnalogyFeatureObservation:
    """One exact raw PIT feature observation from its canonical source."""

    feature_key: str
    value: Decimal
    unit: str
    source_version: str
    available_at: datetime
    vintage_at: datetime
    source_hash: str
    evidence_ref: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        feature_key: str,
        value: Decimal,
        unit: str,
        source_version: str,
        available_at: datetime,
        vintage_at: datetime,
        source_hash: str,
        evidence_ref: str,
    ) -> AnalogyFeatureObservation:
        values = (
            feature_key,
            value,
            unit,
            source_version,
            available_at,
            vintage_at,
            source_hash,
            evidence_ref,
        )
        return cls(*values, _analogy_observation_hash(*values))

    def __post_init__(self) -> None:
        require_token(self.feature_key, "analogy observation feature_key")
        _decimal(self.value, "analogy observation value")
        require_text(self.unit, "analogy observation unit", maximum=64)
        require_token(self.source_version, "analogy observation source_version")
        _utc_text(self.available_at, "analogy observation available_at")
        _utc_text(self.vintage_at, "analogy observation vintage_at")
        require_sha256(self.source_hash, "analogy observation source_hash")
        require_text(self.evidence_ref, "analogy observation evidence_ref")
        require_sha256(self.content_hash, "analogy observation content_hash")
        if self.content_hash != _analogy_observation_hash(
            self.feature_key,
            self.value,
            self.unit,
            self.source_version,
            self.available_at,
            self.vintage_at,
            self.source_hash,
            self.evidence_ref,
        ):
            raise ValueError("analogy feature observation content_hash mismatch")

    def validated_copy(self) -> AnalogyFeatureObservation:
        if type(self) is not AnalogyFeatureObservation:
            raise TypeError("analogy feature observation type differs")
        copied = AnalogyFeatureObservation.create(
            feature_key=self.feature_key,
            value=self.value,
            unit=self.unit,
            source_version=self.source_version,
            available_at=self.available_at,
            vintage_at=self.vintage_at,
            source_hash=self.source_hash,
            evidence_ref=self.evidence_ref,
        )
        if copied != self:
            raise ValueError("analogy feature observation differs after replay")
        return copied


def _analogy_observation_hash(
    key: str,
    value: Decimal,
    unit: str,
    source_version: str,
    available_at: datetime,
    vintage_at: datetime,
    source_hash: str,
    evidence_ref: str,
) -> str:
    return _hash(
        "r7-analogy-feature-observation.v1",
        key,
        _decimal_text(value),
        unit,
        source_version,
        _utc_text(available_at, "analogy observation available_at"),
        _utc_text(vintage_at, "analogy observation vintage_at"),
        source_hash,
        evidence_ref,
    )


@dataclass(frozen=True)
class HistoricalAnalogyDefinition:
    """Research-owned definition for deriving analogy similarity from raw facts."""

    definition_id: str
    definition_version: str
    study_version: str
    scope: ScenarioResearchScope
    feature_definition_version: str
    similarity_method_version: str
    feature_rules: tuple[AnalogyFeatureRule, ...]
    allowed_release_lag: timedelta
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
        feature_definition_version: str,
        similarity_method_version: str,
        feature_rules: tuple[AnalogyFeatureRule, ...],
        allowed_release_lag: timedelta,
        activated_at: datetime,
        valid_until: datetime,
        evidence_refs: tuple[str, ...],
    ) -> HistoricalAnalogyDefinition:
        canonical_scope = _copy_scope(scope)
        canonical_rules = tuple(
            sorted(
                (item.validated_copy() for item in feature_rules), key=lambda item: item.feature_key
            )
        )
        canonical_refs = tuple(sorted(set(evidence_refs)))
        values = (
            definition_id,
            definition_version,
            study_version,
            canonical_scope,
            feature_definition_version,
            similarity_method_version,
            canonical_rules,
            allowed_release_lag,
            activated_at,
            valid_until,
            canonical_refs,
        )
        return cls(*values, _analogy_definition_hash(*values))

    def __post_init__(self) -> None:
        for label, value in (
            ("definition_id", self.definition_id),
            ("definition_version", self.definition_version),
            ("study_version", self.study_version),
            ("feature_definition_version", self.feature_definition_version),
        ):
            require_token(value, f"analogy {label}")
        if self.similarity_method_version != "weighted-normalized-l1.v1":
            raise ValueError("analogy similarity method is unsupported")
        _copy_scope(self.scope)
        if type(self.feature_rules) is not tuple or not self.feature_rules:
            raise ValueError("analogy definition requires feature rules")
        copied_rules = tuple(_exact_analogy_rule(item) for item in self.feature_rules)
        if copied_rules != tuple(sorted(copied_rules, key=lambda item: item.feature_key)):
            raise ValueError("analogy feature rules must be canonical")
        if len({item.feature_key for item in copied_rules}) != len(copied_rules):
            raise ValueError("analogy definition contains duplicate feature rules")
        if sum((item.weight for item in copied_rules), Decimal(0)) != Decimal(1):
            raise ValueError("analogy feature weights must sum exactly to one")
        if self.allowed_release_lag < timedelta(0):
            raise ValueError("analogy allowed release lag cannot be negative")
        _utc_text(self.activated_at, "analogy activated_at")
        _utc_text(self.valid_until, "analogy valid_until")
        if self.valid_until <= self.activated_at:
            raise ValueError("analogy definition validity is empty")
        _evidence_refs(self.evidence_refs, "analogy definition")
        require_sha256(self.content_hash, "analogy definition content_hash")
        if self.content_hash != _analogy_definition_hash(
            self.definition_id,
            self.definition_version,
            self.study_version,
            self.scope,
            self.feature_definition_version,
            self.similarity_method_version,
            copied_rules,
            self.allowed_release_lag,
            self.activated_at,
            self.valid_until,
            self.evidence_refs,
        ):
            raise ValueError("analogy definition content_hash mismatch")

    def validated_copy(self) -> HistoricalAnalogyDefinition:
        if type(self) is not HistoricalAnalogyDefinition:
            raise TypeError("analogy definition type differs")
        copied = HistoricalAnalogyDefinition.create(
            definition_id=self.definition_id,
            definition_version=self.definition_version,
            study_version=self.study_version,
            scope=self.scope,
            feature_definition_version=self.feature_definition_version,
            similarity_method_version=self.similarity_method_version,
            feature_rules=self.feature_rules,
            allowed_release_lag=self.allowed_release_lag,
            activated_at=self.activated_at,
            valid_until=self.valid_until,
            evidence_refs=self.evidence_refs,
        )
        if copied != self:
            raise ValueError("analogy definition differs after replay")
        return copied


def _exact_analogy_rule(value: object) -> AnalogyFeatureRule:
    if type(value) is not AnalogyFeatureRule:
        raise TypeError("analogy feature rule type differs")
    return AnalogyFeatureRule.validated_copy(value)


def _analogy_definition_hash(
    definition_id: str,
    definition_version: str,
    study_version: str,
    scope: ScenarioResearchScope,
    feature_definition_version: str,
    method_version: str,
    rules: tuple[AnalogyFeatureRule, ...],
    allowed_release_lag: timedelta,
    activated_at: datetime,
    valid_until: datetime,
    evidence_refs: tuple[str, ...],
) -> str:
    return _hash(
        "r7-historical-analogy-definition.v1",
        definition_id,
        definition_version,
        study_version,
        scope.content_hash,
        feature_definition_version,
        method_version,
        *(
            [item.content_hash for item in rules]
            + [
                _duration_text(allowed_release_lag, "analogy allowed_release_lag"),
                _utc_text(activated_at, "analogy activated_at"),
                _utc_text(valid_until, "analogy valid_until"),
                *evidence_refs,
            ]
        ),
    )


@dataclass(frozen=True)
class AnalogyCandidateRawEvidence:
    """One historical candidate containing raw features but no caller score."""

    candidate_id: str
    candidate_version: str
    window_start: datetime
    window_end: datetime
    decision_cutoff: datetime
    pit_manifest: PointInTimeManifestReference
    features: tuple[AnalogyFeatureObservation, ...]
    evidence_refs: tuple[str, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        candidate_id: str,
        candidate_version: str,
        window_start: datetime,
        window_end: datetime,
        decision_cutoff: datetime,
        pit_manifest: PointInTimeManifestReference,
        features: tuple[AnalogyFeatureObservation, ...],
        evidence_refs: tuple[str, ...],
    ) -> AnalogyCandidateRawEvidence:
        manifest = _copy_manifest(pit_manifest)
        canonical_features = tuple(
            sorted(
                (_exact_analogy_observation(item) for item in features),
                key=lambda item: item.feature_key,
            )
        )
        canonical_refs = tuple(sorted(set(evidence_refs)))
        values = (
            candidate_id,
            candidate_version,
            window_start,
            window_end,
            decision_cutoff,
            manifest,
            canonical_features,
            canonical_refs,
        )
        return cls(*values, _analogy_candidate_raw_hash(*values))

    def __post_init__(self) -> None:
        require_token(self.candidate_id, "analogy candidate_id")
        require_token(self.candidate_version, "analogy candidate_version")
        _utc_text(self.window_start, "analogy candidate window_start")
        _utc_text(self.window_end, "analogy candidate window_end")
        _utc_text(self.decision_cutoff, "analogy candidate decision_cutoff")
        if not self.window_start < self.window_end <= self.decision_cutoff:
            raise ValueError("analogy candidate window or cutoff is invalid")
        manifest = _copy_manifest(self.pit_manifest)
        if manifest.as_of != self.decision_cutoff:
            raise ValueError("analogy candidate manifest must match decision cutoff")
        features = _exact_analogy_features(self.features, "analogy candidate")
        _match_analogy_manifest(manifest, features)
        _evidence_refs(self.evidence_refs, "analogy candidate")
        require_sha256(self.content_hash, "analogy candidate raw content_hash")
        if self.content_hash != _analogy_candidate_raw_hash(
            self.candidate_id,
            self.candidate_version,
            self.window_start,
            self.window_end,
            self.decision_cutoff,
            manifest,
            features,
            self.evidence_refs,
        ):
            raise ValueError("analogy candidate raw content_hash mismatch")

    def validated_copy(self) -> AnalogyCandidateRawEvidence:
        if type(self) is not AnalogyCandidateRawEvidence:
            raise TypeError("analogy candidate raw type differs")
        copied = AnalogyCandidateRawEvidence.create(
            candidate_id=self.candidate_id,
            candidate_version=self.candidate_version,
            window_start=self.window_start,
            window_end=self.window_end,
            decision_cutoff=self.decision_cutoff,
            pit_manifest=self.pit_manifest,
            features=self.features,
            evidence_refs=self.evidence_refs,
        )
        if copied != self:
            raise ValueError("analogy candidate raw differs after replay")
        return copied


def _exact_analogy_observation(value: object) -> AnalogyFeatureObservation:
    if type(value) is not AnalogyFeatureObservation:
        raise TypeError("analogy observation type differs")
    return AnalogyFeatureObservation.validated_copy(value)


def _exact_analogy_features(
    values: tuple[AnalogyFeatureObservation, ...], label: str
) -> tuple[AnalogyFeatureObservation, ...]:
    if type(values) is not tuple or not values:
        raise ValueError(f"{label} requires raw features")
    copied = tuple(_exact_analogy_observation(item) for item in values)
    if copied != tuple(sorted(copied, key=lambda item: item.feature_key)):
        raise ValueError(f"{label} raw features must be canonical")
    if len({item.feature_key for item in copied}) != len(copied):
        raise ValueError(f"{label} contains duplicate raw features")
    return copied


def _match_analogy_manifest(
    manifest: PointInTimeManifestReference,
    features: tuple[AnalogyFeatureObservation, ...],
) -> None:
    manifest_by_key = {item.feature_key: item for item in manifest.features}
    if set(manifest_by_key) != {item.feature_key for item in features}:
        raise ValueError("analogy manifest does not exactly cover raw features")
    for item in features:
        manifest_item = manifest_by_key[item.feature_key]
        if (
            manifest_item.source_version != item.source_version
            or manifest_item.available_at != item.available_at
            or manifest_item.vintage_at != item.vintage_at
            or manifest_item.content_hash != item.source_hash
        ):
            raise ValueError("analogy raw feature differs from its PIT manifest")


def _analogy_candidate_raw_hash(
    candidate_id: str,
    candidate_version: str,
    window_start: datetime,
    window_end: datetime,
    decision_cutoff: datetime,
    manifest: PointInTimeManifestReference,
    features: tuple[AnalogyFeatureObservation, ...],
    evidence_refs: tuple[str, ...],
) -> str:
    return _hash(
        "r7-analogy-candidate-raw.v1",
        candidate_id,
        candidate_version,
        _utc_text(window_start, "analogy candidate window_start"),
        _utc_text(window_end, "analogy candidate window_end"),
        _utc_text(decision_cutoff, "analogy candidate decision_cutoff"),
        manifest.reference_hash,
        *([item.content_hash for item in features] + list(evidence_refs)),
    )


@dataclass(frozen=True)
class HistoricalAnalogyRawSource:
    """Complete raw query/candidate graph received from the canonical data owner."""

    query_manifest: PointInTimeManifestReference
    query_features: tuple[AnalogyFeatureObservation, ...]
    candidates: tuple[AnalogyCandidateRawEvidence, ...]
    available_at: datetime
    evidence_refs: tuple[str, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        query_manifest: PointInTimeManifestReference,
        query_features: tuple[AnalogyFeatureObservation, ...],
        candidates: tuple[AnalogyCandidateRawEvidence, ...],
        available_at: datetime,
        evidence_refs: tuple[str, ...],
    ) -> HistoricalAnalogyRawSource:
        manifest = _copy_manifest(query_manifest)
        features = tuple(
            sorted(
                (_exact_analogy_observation(item) for item in query_features),
                key=lambda item: item.feature_key,
            )
        )
        canonical_candidates = tuple(
            sorted(
                (_exact_analogy_candidate(item) for item in candidates),
                key=lambda item: item.candidate_id,
            )
        )
        refs = tuple(sorted(set(evidence_refs)))
        values = (manifest, features, canonical_candidates, available_at, refs)
        return cls(*values, _analogy_raw_source_hash(*values))

    def __post_init__(self) -> None:
        manifest = _copy_manifest(self.query_manifest)
        features = _exact_analogy_features(self.query_features, "analogy query")
        _match_analogy_manifest(manifest, features)
        if type(self.candidates) is not tuple or not self.candidates:
            raise ValueError("analogy raw source requires candidates")
        candidates = tuple(_exact_analogy_candidate(item) for item in self.candidates)
        if candidates != tuple(sorted(candidates, key=lambda item: item.candidate_id)):
            raise ValueError("analogy candidates must be canonical")
        if len({item.candidate_id for item in candidates}) != len(candidates):
            raise ValueError("analogy raw source contains duplicate candidates")
        if any(item.decision_cutoff >= manifest.as_of for item in candidates):
            raise ValueError("analogy candidate must predate query PIT as_of")
        _utc_text(self.available_at, "analogy raw source available_at")
        if self.available_at < manifest.as_of:
            raise ValueError("analogy source cannot be available before query PIT as_of")
        _evidence_refs(self.evidence_refs, "analogy raw source")
        require_sha256(self.content_hash, "analogy raw source content_hash")
        if self.content_hash != _analogy_raw_source_hash(
            manifest, features, candidates, self.available_at, self.evidence_refs
        ):
            raise ValueError("analogy raw source content_hash mismatch")

    def validated_copy(self) -> HistoricalAnalogyRawSource:
        if type(self) is not HistoricalAnalogyRawSource:
            raise TypeError("analogy raw source type differs")
        copied = HistoricalAnalogyRawSource.create(
            query_manifest=self.query_manifest,
            query_features=self.query_features,
            candidates=self.candidates,
            available_at=self.available_at,
            evidence_refs=self.evidence_refs,
        )
        if copied != self:
            raise ValueError("analogy raw source differs after replay")
        return copied


def _exact_analogy_candidate(value: object) -> AnalogyCandidateRawEvidence:
    if type(value) is not AnalogyCandidateRawEvidence:
        raise TypeError("analogy candidate raw type differs")
    return AnalogyCandidateRawEvidence.validated_copy(value)


def _analogy_raw_source_hash(
    manifest: PointInTimeManifestReference,
    features: tuple[AnalogyFeatureObservation, ...],
    candidates: tuple[AnalogyCandidateRawEvidence, ...],
    available_at: datetime,
    evidence_refs: tuple[str, ...],
) -> str:
    return _hash(
        "r7-historical-analogy-raw-source.v1",
        manifest.reference_hash,
        *(
            [item.content_hash for item in features]
            + [item.content_hash for item in candidates]
            + [_utc_text(available_at, "analogy raw source available_at"), *evidence_refs]
        ),
    )


@dataclass(frozen=True)
class HistoricalAnalogyReceipt:
    """Append-only owner receipt that derives similarity from sealed raw features."""

    receipt_id: str
    receipt_version: str
    definition: HistoricalAnalogyDefinition
    source: HistoricalAnalogyRawSource
    recorded_at: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        receipt_id: str,
        receipt_version: str,
        definition: HistoricalAnalogyDefinition,
        source: HistoricalAnalogyRawSource,
        recorded_at: datetime,
    ) -> HistoricalAnalogyReceipt:
        canonical_definition = definition.validated_copy()
        canonical_source = source.validated_copy()
        values = (receipt_id, receipt_version, canonical_definition, canonical_source, recorded_at)
        return cls(*values, _analogy_receipt_hash(*values))

    def __post_init__(self) -> None:
        require_token(self.receipt_id, "analogy receipt_id")
        require_token(self.receipt_version, "analogy receipt_version")
        if self.receipt_version != "r7-analogy-receipt.v1":
            raise ValueError("analogy receipt version is unsupported")
        definition = _exact_analogy_definition(self.definition)
        source = _exact_analogy_source(self.source)
        _utc_text(self.recorded_at, "analogy receipt recorded_at")
        if not definition.activated_at <= self.recorded_at < definition.valid_until:
            raise ValueError("analogy definition is not active at receipt time")
        if source.available_at > self.recorded_at:
            raise ValueError("analogy raw source is future-dated")
        _validate_analogy_graph(definition, source)
        require_sha256(self.content_hash, "analogy receipt content_hash")
        if self.content_hash != _analogy_receipt_hash(
            self.receipt_id, self.receipt_version, definition, source, self.recorded_at
        ):
            raise ValueError("analogy receipt content_hash mismatch")

    def validated_copy(self) -> HistoricalAnalogyReceipt:
        if type(self) is not HistoricalAnalogyReceipt:
            raise TypeError("analogy receipt type differs")
        copied = HistoricalAnalogyReceipt.create(
            receipt_id=self.receipt_id,
            receipt_version=self.receipt_version,
            definition=self.definition,
            source=self.source,
            recorded_at=self.recorded_at,
        )
        if copied != self:
            raise ValueError("analogy receipt differs after replay")
        return copied

    def to_study_evidence(self) -> HistoricalAnalogyStudyEvidence:
        """Derive the downstream R7 evidence without accepting a caller score."""

        receipt = self.validated_copy()
        rules = {item.feature_key: item for item in receipt.definition.feature_rules}
        query = {item.feature_key: item for item in receipt.source.query_features}
        candidates: list[HistoricalAnalogyCandidateEvidence] = []
        for raw_candidate in receipt.source.candidates:
            raw = {item.feature_key: item for item in raw_candidate.features}
            distance = sum(
                (rule.weight * abs(query[key].value - raw[key].value) / rule.scale)
                for key, rule in rules.items()
            )
            similarity = max(Decimal(0), Decimal(1) - distance)
            candidates.append(
                HistoricalAnalogyCandidateEvidence.create(
                    candidate_id=raw_candidate.candidate_id,
                    candidate_version=raw_candidate.candidate_version,
                    window_start=raw_candidate.window_start,
                    window_end=raw_candidate.window_end,
                    decision_cutoff=raw_candidate.decision_cutoff,
                    allowed_release_lag=receipt.definition.allowed_release_lag,
                    pit_manifest=raw_candidate.pit_manifest,
                    feature_definition_version=receipt.definition.feature_definition_version,
                    features=tuple(
                        PointInTimeFeatureValue(
                            feature_key=item.feature_key,
                            value=item.value,
                            unit=item.unit,
                            source_version=item.source_version,
                            available_at=item.available_at,
                            vintage_at=item.vintage_at,
                        )
                        for item in raw_candidate.features
                    ),
                    similarity_score=similarity,
                    evidence_refs=raw_candidate.evidence_refs,
                )
            )
        return HistoricalAnalogyStudyEvidence.create(
            study_version=receipt.definition.study_version,
            scope=receipt.definition.scope,
            query_manifest=receipt.source.query_manifest,
            feature_definition_version=receipt.definition.feature_definition_version,
            candidates=tuple(candidates),
            generated_at=receipt.recorded_at,
            valid_until=receipt.definition.valid_until,
            evidence_refs=tuple(
                sorted(set(receipt.definition.evidence_refs + receipt.source.evidence_refs))
            ),
        )


def _exact_analogy_definition(value: object) -> HistoricalAnalogyDefinition:
    if type(value) is not HistoricalAnalogyDefinition:
        raise TypeError("analogy definition type differs")
    return HistoricalAnalogyDefinition.validated_copy(value)


def _exact_analogy_source(value: object) -> HistoricalAnalogyRawSource:
    if type(value) is not HistoricalAnalogyRawSource:
        raise TypeError("analogy raw source type differs")
    return HistoricalAnalogyRawSource.validated_copy(value)


def _validate_analogy_graph(
    definition: HistoricalAnalogyDefinition, source: HistoricalAnalogyRawSource
) -> None:
    rules = {item.feature_key: item for item in definition.feature_rules}
    if set(rules) != {item.feature_key for item in source.query_features}:
        raise ValueError("analogy definition does not exactly cover query features")
    for observation in source.query_features:
        if rules[observation.feature_key].unit != observation.unit:
            raise ValueError("analogy query feature unit differs from definition")
    for candidate in source.candidates:
        if set(rules) != {item.feature_key for item in candidate.features}:
            raise ValueError("analogy definition does not exactly cover candidate features")
        if candidate.decision_cutoff - candidate.window_end > definition.allowed_release_lag:
            raise ValueError("analogy candidate exceeds allowed release lag")
        for observation in candidate.features:
            if rules[observation.feature_key].unit != observation.unit:
                raise ValueError("analogy candidate feature unit differs from definition")


def _analogy_receipt_hash(
    receipt_id: str,
    receipt_version: str,
    definition: HistoricalAnalogyDefinition,
    source: HistoricalAnalogyRawSource,
    recorded_at: datetime,
) -> str:
    return _hash(
        "r7-historical-analogy-receipt.v1",
        receipt_id,
        receipt_version,
        definition.content_hash,
        source.content_hash,
        _utc_text(recorded_at, "analogy receipt recorded_at"),
    )


__all__ = [
    "AnalogyCandidateRawEvidence",
    "AnalogyFeatureObservation",
    "AnalogyFeatureRule",
    "HistoricalAnalogyDefinition",
    "HistoricalAnalogyRawSource",
    "HistoricalAnalogyReceipt",
    "PathExpectedSampleMember",
    "PathObservedSampleMember",
    "PathSampleResolution",
    "PathShockObservation",
    "PathShockRule",
    "ScenarioPathDefinition",
    "ScenarioPathRawSource",
    "ScenarioPathReceipt",
]
