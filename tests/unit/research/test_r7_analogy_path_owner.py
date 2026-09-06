"""Pure owner contracts for R7 historical analogy and scenario paths."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from apps.research.application.r7_analogy_path_owner import (
    RegisterHistoricalAnalogyDefinitionCommand,
    RegisterHistoricalAnalogyReceiptCommand,
    RegisterScenarioPathDefinitionCommand,
    RegisterScenarioPathReceiptCommand,
)
from apps.research.domain import r7_analogy_path_owner as analogy_contracts
from apps.research.domain import r7_path_owner as path_contracts
from apps.research.domain.r7_analogy_path_owner import (
    AnalogyCandidateRawEvidence,
    AnalogyFeatureObservation,
    AnalogyFeatureRule,
    HistoricalAnalogyDefinition,
    HistoricalAnalogyRawSource,
    HistoricalAnalogyReceipt,
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
    PointInTimeManifestFeature,
    PointInTimeManifestReference,
)
from apps.research.infrastructure.r7_analogy_path_owner_codec import (
    R7AnalogyPathOwnerCodecError,
    decode_historical_analogy_definition,
    decode_historical_analogy_receipt,
    decode_scenario_path_definition,
    decode_scenario_path_receipt,
    encode_historical_analogy_definition,
    encode_historical_analogy_receipt,
    encode_scenario_path_definition,
    encode_scenario_path_receipt,
)

NOW = datetime(2026, 8, 12, 4, tzinfo=UTC)
REVISION_A = UUID("00000000-0000-0000-0000-000000000001")
REVISION_B = UUID("00000000-0000-0000-0000-000000000002")
SET_REVISION = UUID("00000000-0000-0000-0000-000000000100")


def _scope() -> ScenarioResearchScope:
    return ScenarioResearchScope.create(
        scope_version="scenario-scope.v1",
        scenario_set_revision_id=SET_REVISION,
        scenario_revision_ids=(REVISION_A, REVISION_B),
        forecast_horizon=timedelta(days=1),
        censoring_rule_version="scenario-censoring.v1",
        path_horizon_periods=2,
        path_initial_state_revision_ids=(REVISION_A, REVISION_B),
    )


def _manifest(
    name: str,
    at: datetime,
    feature_digests: tuple[tuple[str, str], ...],
) -> PointInTimeManifestReference:
    features = tuple(
        PointInTimeManifestFeature(
            feature_key=key,
            source_version="macro-vintage.v1",
            available_at=at - timedelta(days=2),
            vintage_at=at - timedelta(days=1),
            content_hash=digit * 64,
        )
        for key, digit in feature_digests
    )
    return PointInTimeManifestReference.create(
        manifest_id=name,
        manifest_version="pit-manifest.v1",
        as_of=at,
        manifest_hash=(feature_digests[0][1] if feature_digests else "9") * 64,
        features=features,
    )


def _feature(
    key: str,
    value: str,
    at: datetime,
    digit: str,
) -> AnalogyFeatureObservation:
    return AnalogyFeatureObservation.create(
        feature_key=key,
        value=Decimal(value),
        unit="zscore",
        source_version="macro-vintage.v1",
        available_at=at - timedelta(days=2),
        vintage_at=at - timedelta(days=1),
        source_hash=digit * 64,
        evidence_ref=f"data-center:{key}:{digit}",
    )


def _analogy_definition() -> HistoricalAnalogyDefinition:
    return HistoricalAnalogyDefinition.create(
        definition_id="r7-analogy:macro-regime",
        definition_version="r7-analogy-definition.v1",
        study_version="historical-analogy-study.v1",
        scope=_scope(),
        feature_definition_version="analogy-features.v1",
        similarity_method_version="weighted-normalized-l1.v1",
        feature_rules=(
            AnalogyFeatureRule.create(
                feature_key="growth", unit="zscore", weight=Decimal("0.25"), scale=Decimal("1")
            ),
            AnalogyFeatureRule.create(
                feature_key="inflation",
                unit="zscore",
                weight=Decimal("0.75"),
                scale=Decimal("2"),
            ),
        ),
        allowed_release_lag=timedelta(days=2),
        activated_at=NOW - timedelta(days=3),
        valid_until=NOW + timedelta(days=30),
        evidence_refs=("research:analogy-method:v1",),
    )


def _analogy_receipt() -> HistoricalAnalogyReceipt:
    query_at = NOW - timedelta(hours=2)
    candidate_at = NOW - timedelta(days=100)
    source = HistoricalAnalogyRawSource.create(
        query_manifest=_manifest("pit-query", query_at, (("growth", "a"), ("inflation", "b"))),
        query_features=(
            _feature("growth", "0", query_at, "a"),
            _feature("inflation", "0", query_at, "b"),
        ),
        candidates=(
            AnalogyCandidateRawEvidence.create(
                candidate_id="candidate-1",
                candidate_version="analogy-candidate.v1",
                window_start=candidate_at - timedelta(days=30),
                window_end=candidate_at - timedelta(days=1),
                decision_cutoff=candidate_at,
                pit_manifest=_manifest(
                    "pit-candidate-1",
                    candidate_at,
                    (("growth", "c"), ("inflation", "d")),
                ),
                features=(
                    _feature("growth", "1", candidate_at, "c"),
                    _feature("inflation", "1", candidate_at, "d"),
                ),
                evidence_refs=("data-center:candidate-1",),
            ),
        ),
        available_at=NOW - timedelta(hours=1),
        evidence_refs=("data-center:analogy-run:1",),
    )
    return HistoricalAnalogyReceipt.create(
        receipt_id="r7-analogy-receipt:1",
        receipt_version="r7-analogy-receipt.v1",
        definition=_analogy_definition(),
        source=source,
        recorded_at=NOW,
    )


def _expected_members() -> tuple[PathExpectedSampleMember, ...]:
    members: list[PathExpectedSampleMember] = []
    for period_index in (1, 2):
        for origin in (REVISION_A, REVISION_B):
            for ordinal in (1, 2):
                members.append(
                    PathExpectedSampleMember.create(
                        member_id=f"p{period_index}-{origin.hex[-1]}-{ordinal}",
                        member_version="path-member.v1",
                        period_index=period_index,
                        from_scenario_revision_id=origin,
                        condition_key=f"origin-{origin.hex[-1]}",
                        selector_hash=str(period_index + ordinal) * 64,
                    )
                )
    return tuple(members)


def _path_definition() -> ScenarioPathDefinition:
    return ScenarioPathDefinition.create(
        definition_id="r7-path:macro-regime",
        definition_version="r7-path-definition.v1",
        study_version="scenario-path-study.v1",
        scope=_scope(),
        source_version="data-center-path-facts.v1",
        sample_definition_version="path-sample.v1",
        expected_members=_expected_members(),
        shock_rules=(
            PathShockRule.create(
                period_index=1,
                scenario_revision_id=REVISION_A,
                period_start=NOW - timedelta(days=4),
                period_end=NOW - timedelta(days=3),
                shock_key="growth",
                unit="zscore",
            ),
            PathShockRule.create(
                period_index=2,
                scenario_revision_id=REVISION_A,
                period_start=NOW - timedelta(days=3),
                period_end=NOW - timedelta(days=2),
                shock_key="growth",
                unit="zscore",
            ),
        ),
        probability_sum_tolerance=Decimal("0.000001"),
        activated_at=NOW - timedelta(days=3),
        valid_until=NOW + timedelta(days=30),
        evidence_refs=("research:path-method:v1",),
    )


def _path_receipt(*, unresolved: bool = False) -> ScenarioPathReceipt:
    definition = _path_definition()
    samples: list[PathObservedSampleMember] = []
    for index, expected in enumerate(definition.expected_members):
        state = (
            PathSampleResolution.UNRESOLVED
            if unresolved and expected.from_scenario_revision_id == REVISION_A
            else PathSampleResolution.RESOLVED
        )
        samples.append(
            PathObservedSampleMember.create(
                expected=expected,
                resolution=state,
                to_scenario_revision_id=(
                    (REVISION_A if index % 2 == 0 else REVISION_B)
                    if state is PathSampleResolution.RESOLVED
                    else None
                ),
                observed_at=(
                    NOW - timedelta(days=1) if state is PathSampleResolution.RESOLVED else None
                ),
                available_at=NOW - timedelta(hours=3),
                source_version="data-center-path-facts.v1",
                source_hash=("e" if index % 2 == 0 else "f") * 64,
                evidence_ref=f"data-center:path-member:{index}",
            )
        )
    raw = ScenarioPathRawSource.create(
        pit_manifest=_manifest("pit-path", NOW - timedelta(hours=1), ()),
        sample_members=tuple(samples),
        shocks=tuple(
            PathShockObservation.create(
                rule=rule,
                magnitude=Decimal("-0.5") if rule.period_index == 1 else Decimal("0.25"),
                source_version="data-center-path-facts.v1",
                available_at=NOW - timedelta(hours=3),
                source_hash=("7" if rule.period_index == 1 else "8") * 64,
                evidence_ref=f"data-center:path-shock:{rule.period_index}",
            )
            for rule in definition.shock_rules
        ),
        available_at=NOW - timedelta(minutes=30),
        evidence_refs=("data-center:path-run:1",),
    )
    return ScenarioPathReceipt.create(
        receipt_id="r7-path-receipt:1",
        receipt_version="r7-path-receipt.v1",
        definition=definition,
        source=raw,
        recorded_at=NOW,
    )


def test_registration_commands_are_identity_and_as_of_only() -> None:
    assert tuple(item.name for item in fields(RegisterHistoricalAnalogyDefinitionCommand)) == (
        "definition_id",
        "definition_version",
        "as_of",
    )
    assert tuple(item.name for item in fields(RegisterHistoricalAnalogyReceiptCommand)) == (
        "definition_id",
        "definition_version",
        "receipt_id",
        "receipt_version",
        "as_of",
    )
    assert tuple(item.name for item in fields(RegisterScenarioPathDefinitionCommand)) == (
        "definition_id",
        "definition_version",
        "as_of",
    )
    assert tuple(item.name for item in fields(RegisterScenarioPathReceiptCommand)) == (
        "definition_id",
        "definition_version",
        "receipt_id",
        "receipt_version",
        "as_of",
    )


def test_analogy_similarity_is_derived_only_from_raw_pit_features() -> None:
    receipt = _analogy_receipt()
    candidate = receipt.to_study_evidence().candidates[0]

    assert candidate.similarity_score == Decimal("0.375")
    assert "similarity_score" not in {item.name for item in fields(AnalogyCandidateRawEvidence)}
    assert "similarity_score" not in {item.name for item in fields(AnalogyFeatureObservation)}


def test_path_probabilities_are_derived_from_resolved_raw_members() -> None:
    receipt = _path_receipt()
    study = receipt.to_study_evidence()

    assert {item.probability for item in study.conditional_probabilities} == {Decimal("0.5")}
    assert {item.observation_count for item in study.conditional_probabilities} == {2}
    assert {item.probability for item in study.transition_probabilities} == {Decimal("0.5")}
    assert {item.observation_count for item in study.transition_probabilities} == {2}
    forbidden = {"probability", "numerator", "denominator", "observation_count"}
    assert forbidden.isdisjoint({item.name for item in fields(PathObservedSampleMember)})


def test_path_preserves_unresolved_and_fails_closed_without_a_denominator() -> None:
    receipt = _path_receipt(unresolved=True)

    assert any(
        member.resolution is PathSampleResolution.UNRESOLVED
        for member in receipt.source.sample_members
    )
    with pytest.raises(ValueError, match="resolved denominator"):
        receipt.to_study_evidence()


def test_receipt_rejects_incomplete_expected_membership() -> None:
    receipt = _path_receipt()
    with pytest.raises(ValueError, match="expected membership"):
        ScenarioPathRawSource.create(
            pit_manifest=receipt.source.pit_manifest,
            sample_members=receipt.source.sample_members[:-1],
            shocks=receipt.source.shocks,
            available_at=receipt.source.available_at,
            evidence_refs=receipt.source.evidence_refs,
            expected_definition=receipt.definition,
        )


def test_owner_codecs_are_strict_and_seal_preserving() -> None:
    analogy_definition = _analogy_definition()
    analogy_receipt = _analogy_receipt()
    path_definition = _path_definition()
    path_receipt = _path_receipt()

    assert (
        decode_historical_analogy_definition(
            encode_historical_analogy_definition(analogy_definition)
        )
        == analogy_definition
    )
    assert (
        decode_historical_analogy_receipt(encode_historical_analogy_receipt(analogy_receipt))
        == analogy_receipt
    )
    assert (
        decode_scenario_path_definition(encode_scenario_path_definition(path_definition))
        == path_definition
    )
    assert decode_scenario_path_receipt(encode_scenario_path_receipt(path_receipt)) == path_receipt

    payload = encode_historical_analogy_receipt(analogy_receipt)
    payload["caller_similarity"] = "1"
    with pytest.raises(R7AnalogyPathOwnerCodecError):
        decode_historical_analogy_receipt(payload)

    payload = encode_scenario_path_receipt(path_receipt)
    payload["content_hash"] = "0" * 64
    with pytest.raises(R7AnalogyPathOwnerCodecError):
        decode_scenario_path_receipt(payload)


def _strict_subclass(value: object) -> object:
    subclass = type(f"Data12{type(value).__name__}Subclass", (type(value),), {})
    return subclass(**{item.name: getattr(value, item.name) for item in fields(value) if item.init})


def _assert_replay_difference(value: object) -> None:
    altered = replace(value)  # type: ignore[arg-type]
    object.__setattr__(altered, "content_hash", "0" * 64)
    with pytest.raises(ValueError, match="differs after replay"):
        altered.validated_copy()  # type: ignore[attr-defined]


def test_data12_analogy_owner_rejects_unsealed_definition_and_raw_graph() -> None:
    """Cover retained R7 analogy lines with explicit invalid owner variants."""

    definition = _analogy_definition()
    receipt = _analogy_receipt()
    source = receipt.source
    rule = definition.feature_rules[0]
    feature = source.query_features[0]
    candidate = source.candidates[0]
    second_candidate = AnalogyCandidateRawEvidence.create(
        candidate_id="candidate-2",
        candidate_version=candidate.candidate_version,
        window_start=candidate.window_start - timedelta(days=1),
        window_end=candidate.window_end,
        decision_cutoff=candidate.decision_cutoff,
        pit_manifest=candidate.pit_manifest,
        features=candidate.features,
        evidence_refs=candidate.evidence_refs,
    )
    bad_weight = AnalogyFeatureRule.create(
        feature_key=rule.feature_key,
        unit=rule.unit,
        weight=Decimal("0.20"),
        scale=rule.scale,
    )
    mismatched_feature = _feature(
        feature.feature_key,
        "1",
        source.query_manifest.as_of,
        "f",
    )

    invalid_constructions = (
        lambda: analogy_contracts._utc_text(datetime(2026, 1, 1), "clock"),
        lambda: analogy_contracts._duration_text("one day", "duration"),
        lambda: analogy_contracts._decimal(1, "number"),
        lambda: analogy_contracts._decimal(Decimal("0"), "number", positive=True),
        lambda: analogy_contracts._positive_int(0, "count"),
        lambda: analogy_contracts._evidence_refs((), "evidence"),
        lambda: analogy_contracts._evidence_refs(("b", "a"), "evidence"),
        lambda: analogy_contracts._copy_scope(object()),
        lambda: analogy_contracts._copy_manifest(object()),
        lambda: replace(rule, content_hash="0" * 64),
        lambda: replace(feature, content_hash="0" * 64),
        lambda: replace(definition, similarity_method_version="cosine.v1"),
        lambda: replace(definition, feature_rules=()),
        lambda: replace(definition, feature_rules=tuple(reversed(definition.feature_rules))),
        lambda: replace(definition, feature_rules=(rule, rule)),
        lambda: replace(
            definition,
            feature_rules=(bad_weight, definition.feature_rules[1]),
        ),
        lambda: replace(definition, allowed_release_lag=-timedelta(seconds=1)),
        lambda: replace(definition, valid_until=definition.activated_at),
        lambda: replace(definition, content_hash="0" * 64),
        lambda: analogy_contracts._exact_analogy_rule(object()),
        lambda: replace(candidate, window_end=candidate.window_start),
        lambda: replace(
            candidate,
            decision_cutoff=candidate.decision_cutoff + timedelta(seconds=1),
        ),
        lambda: replace(candidate, content_hash="0" * 64),
        lambda: analogy_contracts._exact_analogy_observation(object()),
        lambda: analogy_contracts._exact_analogy_features((), "features"),
        lambda: analogy_contracts._exact_analogy_features(
            tuple(reversed(source.query_features)),
            "features",
        ),
        lambda: analogy_contracts._exact_analogy_features((feature, feature), "features"),
        lambda: analogy_contracts._match_analogy_manifest(
            source.query_manifest,
            source.query_features[:1],
        ),
        lambda: analogy_contracts._match_analogy_manifest(
            source.query_manifest,
            (mismatched_feature, source.query_features[1]),
        ),
        lambda: replace(source, candidates=()),
        lambda: replace(source, candidates=(second_candidate, candidate)),
        lambda: replace(source, candidates=(candidate, candidate)),
        lambda: replace(source, available_at=source.query_manifest.as_of - timedelta(seconds=1)),
        lambda: replace(source, content_hash="0" * 64),
        lambda: analogy_contracts._exact_analogy_candidate(object()),
        lambda: replace(receipt, receipt_version="unsupported"),
        lambda: replace(receipt, recorded_at=definition.activated_at - timedelta(seconds=1)),
        lambda: replace(receipt, recorded_at=source.available_at - timedelta(seconds=1)),
        lambda: replace(receipt, content_hash="0" * 64),
        lambda: analogy_contracts._exact_analogy_definition(object()),
        lambda: analogy_contracts._exact_analogy_source(object()),
    )
    for construct in invalid_constructions:
        with pytest.raises((TypeError, ValueError)):
            construct()

    for value, match in (
        (rule, "feature rule type differs"),
        (feature, "feature observation type differs"),
        (definition, "definition type differs"),
        (candidate, "candidate raw type differs"),
        (source, "raw source type differs"),
        (receipt, "receipt type differs"),
    ):
        with pytest.raises(TypeError, match=match):
            _strict_subclass(value).validated_copy()  # type: ignore[attr-defined]
        _assert_replay_difference(value)


def test_data12_path_owner_rejects_unsealed_members_sources_and_receipts() -> None:
    """Cover retained R7 path lines without synthesizing resolved denominators."""

    definition = _path_definition()
    receipt = _path_receipt()
    source = receipt.source
    expected = definition.expected_members[0]
    rule = definition.shock_rules[0]
    observed = source.sample_members[0]
    shock = source.shocks[0]
    late_observed = PathObservedSampleMember.create(
        expected=observed.expected,
        resolution=observed.resolution,
        to_scenario_revision_id=observed.to_scenario_revision_id,
        observed_at=observed.observed_at,
        available_at=source.available_at + timedelta(seconds=1),
        source_version=observed.source_version,
        source_hash=observed.source_hash,
        evidence_ref=observed.evidence_ref,
    )
    foreign_observed = PathObservedSampleMember.create(
        expected=observed.expected,
        resolution=observed.resolution,
        to_scenario_revision_id=UUID("00000000-0000-0000-0000-000000000999"),
        observed_at=observed.observed_at,
        available_at=observed.available_at,
        source_version=observed.source_version,
        source_hash=observed.source_hash,
        evidence_ref=observed.evidence_ref,
    )
    wrong_version_observed = PathObservedSampleMember.create(
        expected=observed.expected,
        resolution=observed.resolution,
        to_scenario_revision_id=observed.to_scenario_revision_id,
        observed_at=observed.observed_at,
        available_at=observed.available_at,
        source_version="different-source.v1",
        source_hash=observed.source_hash,
        evidence_ref=observed.evidence_ref,
    )

    invalid_constructions = (
        lambda: path_contracts._utc_text(datetime(2026, 1, 1), "clock"),
        lambda: path_contracts._duration_text("one day", "duration"),
        lambda: path_contracts._decimal(1, "number"),
        lambda: path_contracts._decimal(Decimal("0"), "number", positive=True),
        lambda: path_contracts._positive_int(0, "count"),
        lambda: path_contracts._evidence_refs((), "evidence"),
        lambda: path_contracts._evidence_refs(("b", "a"), "evidence"),
        lambda: path_contracts._copy_scope(object()),
        lambda: path_contracts._copy_manifest(object()),
        lambda: replace(expected, from_scenario_revision_id="revision"),
        lambda: replace(expected, content_hash="0" * 64),
        lambda: replace(rule, scenario_revision_id="revision"),
        lambda: replace(rule, period_end=rule.period_start),
        lambda: replace(rule, content_hash="0" * 64),
        lambda: replace(definition, probability_sum_tolerance=Decimal("1")),
        lambda: replace(definition, valid_until=definition.activated_at),
        lambda: replace(definition, content_hash="0" * 64),
        lambda: path_contracts._exact_path_expected(object()),
        lambda: path_contracts._exact_path_members(()),
        lambda: path_contracts._exact_path_members(tuple(reversed(definition.expected_members))),
        lambda: path_contracts._exact_path_members((expected, expected)),
        lambda: path_contracts._exact_path_shock_rule(object()),
        lambda: path_contracts._exact_path_shock_rules(()),
        lambda: path_contracts._exact_path_shock_rules(tuple(reversed(definition.shock_rules))),
        lambda: path_contracts._exact_path_shock_rules((rule, rule)),
        lambda: replace(observed, resolution="resolved"),
        lambda: replace(
            observed,
            resolution=PathSampleResolution.UNRESOLVED,
        ),
        lambda: replace(observed, to_scenario_revision_id="revision"),
        lambda: replace(
            observed,
            available_at=observed.observed_at - timedelta(seconds=1),
        ),
        lambda: replace(observed, content_hash="0" * 64),
        lambda: replace(shock, available_at=rule.period_end - timedelta(seconds=1)),
        lambda: replace(shock, content_hash="0" * 64),
        lambda: replace(source, available_at=source.pit_manifest.as_of - timedelta(seconds=1)),
        lambda: replace(
            source,
            sample_members=(late_observed, *source.sample_members[1:]),
        ),
        lambda: replace(source, content_hash="0" * 64),
        lambda: path_contracts._exact_path_observed(object()),
        lambda: path_contracts._exact_path_observed_members(()),
        lambda: path_contracts._exact_path_observed_members(tuple(reversed(source.sample_members))),
        lambda: path_contracts._exact_path_observed_members((observed, observed)),
        lambda: path_contracts._exact_path_shock_observation(object()),
        lambda: path_contracts._exact_path_shock_observations(()),
        lambda: path_contracts._exact_path_shock_observations(tuple(reversed(source.shocks))),
        lambda: path_contracts._exact_path_shock_observations((shock, shock)),
        lambda: replace(receipt, receipt_version="unsupported"),
        lambda: replace(receipt, recorded_at=definition.activated_at - timedelta(seconds=1)),
        lambda: replace(receipt, recorded_at=source.available_at - timedelta(seconds=1)),
        lambda: path_contracts._exact_path_definition(object()),
        lambda: path_contracts._exact_path_source(object()),
    )
    for construct in invalid_constructions:
        with pytest.raises((TypeError, ValueError)):
            construct()

    for value, match in (
        (expected, "expected member type differs"),
        (rule, "shock rule type differs"),
        (definition, "definition type differs"),
        (observed, "observed member type differs"),
        (shock, "shock observation type differs"),
        (source, "raw source type differs"),
        (receipt, "receipt type differs"),
    ):
        with pytest.raises(TypeError, match=match):
            _strict_subclass(value).validated_copy()  # type: ignore[attr-defined]
        _assert_replay_difference(value)

    late_source = ScenarioPathRawSource.create(
        pit_manifest=source.pit_manifest,
        sample_members=(foreign_observed, *source.sample_members[1:]),
        shocks=source.shocks,
        available_at=source.available_at,
        evidence_refs=source.evidence_refs,
    )
    with pytest.raises(ValueError, match="outside scenario scope"):
        path_contracts._match_path_source(definition, late_source)
    wrong_version_source = ScenarioPathRawSource.create(
        pit_manifest=source.pit_manifest,
        sample_members=(wrong_version_observed, *source.sample_members[1:]),
        shocks=source.shocks,
        available_at=source.available_at,
        evidence_refs=source.evidence_refs,
    )
    with pytest.raises(ValueError, match="source version differs"):
        path_contracts._match_path_source(definition, wrong_version_source)


def test_data12_owner_graph_cross_member_consistency_is_fail_closed() -> None:
    """Exercise remaining reachable analogy/path graph consistency branches."""

    assert analogy_contracts._positive_int(1, "count") == 1
    assert path_contracts._duration_text(timedelta(days=1), "duration") == "86400.0"

    analogy_definition = _analogy_definition()
    analogy_source = _analogy_receipt().source
    query_subset = deepcopy(analogy_source)
    object.__setattr__(query_subset, "query_features", query_subset.query_features[:1])
    bad_query_unit = deepcopy(analogy_source)
    query_feature = deepcopy(bad_query_unit.query_features[0])
    object.__setattr__(query_feature, "unit", "percent")
    object.__setattr__(
        bad_query_unit,
        "query_features",
        (query_feature, *bad_query_unit.query_features[1:]),
    )
    candidate_subset = deepcopy(analogy_source)
    candidate = deepcopy(candidate_subset.candidates[0])
    object.__setattr__(candidate, "features", candidate.features[:1])
    object.__setattr__(candidate_subset, "candidates", (candidate,))
    excessive_lag = deepcopy(analogy_source)
    candidate = deepcopy(excessive_lag.candidates[0])
    object.__setattr__(
        candidate,
        "window_end",
        candidate.decision_cutoff - analogy_definition.allowed_release_lag - timedelta(seconds=1),
    )
    object.__setattr__(excessive_lag, "candidates", (candidate,))
    bad_candidate_unit = deepcopy(analogy_source)
    candidate = deepcopy(bad_candidate_unit.candidates[0])
    feature = deepcopy(candidate.features[0])
    object.__setattr__(feature, "unit", "percent")
    object.__setattr__(candidate, "features", (feature, *candidate.features[1:]))
    object.__setattr__(bad_candidate_unit, "candidates", (candidate,))

    for source, match in (
        (query_subset, "query features"),
        (bad_query_unit, "query feature unit"),
        (candidate_subset, "candidate features"),
        (excessive_lag, "release lag"),
        (bad_candidate_unit, "candidate feature unit"),
    ):
        with pytest.raises(ValueError, match=match):
            analogy_contracts._validate_analogy_graph(analogy_definition, source)

    equal_cutoff_candidate = AnalogyCandidateRawEvidence.create(
        candidate_id="candidate-at-query-cutoff",
        candidate_version="analogy-candidate.v1",
        window_start=analogy_source.query_manifest.as_of - timedelta(days=3),
        window_end=analogy_source.query_manifest.as_of - timedelta(days=1),
        decision_cutoff=analogy_source.query_manifest.as_of,
        pit_manifest=analogy_source.query_manifest,
        features=analogy_source.query_features,
        evidence_refs=("data-center:candidate-at-query-cutoff",),
    )
    with pytest.raises(ValueError, match="must predate"):
        replace(analogy_source, candidates=(equal_cutoff_candidate,))

    path_definition = _path_definition()
    members = path_definition.expected_members
    rules = path_definition.shock_rules
    unbalanced_members = members[:-1]
    foreign_rule = deepcopy(rules[0])
    object.__setattr__(
        foreign_rule,
        "scenario_revision_id",
        UUID("00000000-0000-0000-0000-000000000999"),
    )
    split_boundary_rule = deepcopy(rules[0])
    object.__setattr__(split_boundary_rule, "scenario_revision_id", REVISION_B)
    object.__setattr__(
        split_boundary_rule,
        "period_start",
        rules[0].period_start + timedelta(hours=1),
    )
    overlap_rule = deepcopy(rules[1])
    object.__setattr__(
        overlap_rule,
        "period_start",
        rules[0].period_end - timedelta(hours=1),
    )
    graph_cases = (
        (members[:1], rules, "cover every period"),
        (unbalanced_members, rules, "balanced group"),
        (members, rules[:1], "exact path horizon"),
        (members, (foreign_rule, rules[1]), "outside scope"),
        (members, (rules[0], split_boundary_rule, rules[1]), "different boundaries"),
        (members, (rules[0], overlap_rule), "overlap"),
    )
    for actual_members, actual_rules, match in graph_cases:
        with pytest.raises(ValueError, match=match):
            path_contracts._validate_path_definition_graph(
                path_definition.scope,
                actual_members,
                actual_rules,
            )

    path_source = _path_receipt().source
    incomplete_shocks = ScenarioPathRawSource.create(
        pit_manifest=path_source.pit_manifest,
        sample_members=path_source.sample_members,
        shocks=path_source.shocks[:1],
        available_at=path_source.available_at,
        evidence_refs=path_source.evidence_refs,
    )
    with pytest.raises(ValueError, match="expected shock rules"):
        path_contracts._match_path_source(path_definition, incomplete_shocks)
    wrong_shock = PathShockObservation.create(
        rule=path_source.shocks[0].rule,
        magnitude=path_source.shocks[0].magnitude,
        source_version="different-source.v1",
        available_at=path_source.shocks[0].available_at,
        source_hash=path_source.shocks[0].source_hash,
        evidence_ref=path_source.shocks[0].evidence_ref,
    )
    wrong_shock_source = ScenarioPathRawSource.create(
        pit_manifest=path_source.pit_manifest,
        sample_members=path_source.sample_members,
        shocks=(wrong_shock, *path_source.shocks[1:]),
        available_at=path_source.available_at,
        evidence_refs=path_source.evidence_refs,
    )
    with pytest.raises(ValueError, match="shock source version differs"):
        path_contracts._match_path_source(path_definition, wrong_shock_source)
