"""Pure owner contracts for R7 historical analogy and scenario paths."""

from __future__ import annotations

from dataclasses import fields
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
