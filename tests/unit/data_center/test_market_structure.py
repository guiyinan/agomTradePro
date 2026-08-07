"""Domain and Application tests for fail-closed R2 market-structure research."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest

from apps.data_center.application.market_structure import RunMarketStructureResearch
from apps.data_center.domain.market_structure import (
    MARKET_STRUCTURE_CALENDAR_DATASET,
    MARKET_STRUCTURE_TAXONOMY_DATASET,
    EmpiricalPercentileMethod,
    ImmutableMarketStructureEvidence,
    InvestorActorDefinition,
    MarketStructureAggregationPolicy,
    MarketStructureGovernanceArtifactKind,
    MarketStructureMeasureConcept,
    MarketStructureObservation,
    MarketStructurePeriodCalendar,
    MarketStructurePeriodCalendarRef,
    MarketStructurePublicationAttestation,
    MarketStructureResearchRequest,
    MarketStructureResearchStatus,
    MarketStructureSeriesDefinition,
    MarketStructureSeriesRef,
    PITMembershipSnapshot,
    SeriesPeriodCoverage,
    VersionedEvidenceReference,
    aggregate_market_structure,
    build_market_structure_evidence,
)
from apps.data_center.domain.pit import KnowledgeScope
from apps.data_center.domain.research_data_foundation import InvestorFlowMeasureKind

AS_OF = datetime(2025, 4, 1, tzinfo=UTC)
PERIODS = (
    datetime(2025, 1, 1, tzinfo=UTC),
    datetime(2025, 2, 1, tzinfo=UTC),
    datetime(2025, 3, 1, tzinfo=UTC),
)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _actor(actor_code: str) -> InvestorActorDefinition:
    return InvestorActorDefinition(
        taxonomy_code="TEST_TAXONOMY",
        taxonomy_version=1,
        actor_code=actor_code,
        actor_name=f"Actor {actor_code}",
        source="test_governance",
        revision_policy_ref="governance://actor-revision/v1",
        effective_at=PERIODS[0],
        available_at=PERIODS[0],
    )


def _series(
    actor_code: str,
    *,
    concept: MarketStructureMeasureConcept = MarketStructureMeasureConcept.FLOW,
    is_proxy: bool = False,
) -> MarketStructureSeriesDefinition:
    measure_kind = {
        MarketStructureMeasureConcept.FLOW: InvestorFlowMeasureKind.FUND_FLOW,
        MarketStructureMeasureConcept.HOLDING: InvestorFlowMeasureKind.HOLDING_CHANGE,
        MarketStructureMeasureConcept.STOCK: InvestorFlowMeasureKind.CAPITAL_BALANCE,
        MarketStructureMeasureConcept.TRANSACTION: (InvestorFlowMeasureKind.TRANSACTION_NET_FLOW),
    }[concept]
    return MarketStructureSeriesDefinition(
        series_code=f"SERIES_{actor_code}",
        series_version=1,
        flow_code=f"FLOW_{actor_code}",
        flow_definition_version=1,
        taxonomy_code="TEST_TAXONOMY",
        taxonomy_version=1,
        actor_code=actor_code,
        measure_concept=concept,
        measure_kind=measure_kind,
        canonical_unit="CNY",
        frequency="monthly",
        source="test_source",
        revision_policy_ref="governance://flow-revision/v1",
        effective_at=PERIODS[0],
        is_proxy=is_proxy,
        available_at=PERIODS[0],
        proxy_target_actor_code="TARGET_ACTOR" if is_proxy else "",
        proxy_methodology_ref="governance://proxy/v1" if is_proxy else "",
    )


def _policy() -> MarketStructureAggregationPolicy:
    return MarketStructureAggregationPolicy(
        policy_code="TEST_POLICY",
        policy_version=1,
        minimum_history_observations=3,
        minimum_actor_count=2,
        minimum_membership_coverage_ratio=Decimal("1"),
        percentile_method=EmpiricalPercentileMethod.WEAK_EMPIRICAL_CDF,
    )


def _calendar() -> MarketStructurePeriodCalendar:
    return MarketStructurePeriodCalendar(
        calendar_code="TEST_MONTHLY_CALENDAR",
        calendar_version=1,
        frequency="monthly",
        source="test_governance",
        revision_policy_ref="governance://period-calendar/v1",
        available_at=AS_OF,
        periods=PERIODS,
    )


def _publication_attestation(
    *,
    kind: MarketStructureGovernanceArtifactKind,
    natural_key: str,
    artifact_hash: str,
    observed_at: datetime,
    member_id: str,
) -> MarketStructurePublicationAttestation:
    taxonomy = kind is not MarketStructureGovernanceArtifactKind.PERIOD_CALENDAR
    return MarketStructurePublicationAttestation.create(
        artifact_kind=kind,
        dataset_key=(
            MARKET_STRUCTURE_TAXONOMY_DATASET if taxonomy else MARKET_STRUCTURE_CALENDAR_DATASET
        ),
        publication_key=(
            "taxonomy:TEST_TAXONOMY:v1" if taxonomy else "calendar:TEST_MONTHLY_CALENDAR:v1"
        ),
        publication_id=("taxonomy-publication" if taxonomy else "calendar-publication"),
        publication_hash=(HASH_C if taxonomy else HASH_B),
        publication_as_of=observed_at,
        published_at=observed_at,
        member_id=member_id,
        member_natural_key=natural_key,
        fact_table="test_governance",
        fact_pk=member_id,
        artifact_hash=artifact_hash,
        member_observed_at=observed_at,
    )


def test_publication_attestation_rejects_semantically_ignored_fields() -> None:
    attestation = _publication_attestation(
        kind=MarketStructureGovernanceArtifactKind.PERIOD_CALENDAR,
        natural_key="calendar:TEST_MONTHLY_CALENDAR:v1",
        artifact_hash=_calendar().calendar_hash,
        observed_at=AS_OF,
        member_id="calendar-member",
    )
    payload = attestation.to_payload()
    payload["unsupported"] = "would-be-ignored"

    with pytest.raises(ValueError, match="unsupported fields"):
        MarketStructurePublicationAttestation.from_payload(payload)


def _request() -> MarketStructureResearchRequest:
    return MarketStructureResearchRequest(
        evidence_key="TEST_EVIDENCE",
        evidence_version=1,
        as_of_time=AS_OF,
        knowledge_scope=KnowledgeScope.PUBLIC,
        group_code="TEST_GROUP",
        group_revision=1,
        period_calendar=MarketStructurePeriodCalendarRef(
            calendar_code="TEST_MONTHLY_CALENDAR",
            calendar_version=1,
        ),
        method_version="r2-test-v1",
        series=(
            MarketStructureSeriesRef(series_code="SERIES_A", series_version=1),
            MarketStructureSeriesRef(series_code="SERIES_B", series_version=1),
        ),
        policy=_policy(),
    )


def _observation(
    definition: MarketStructureSeriesDefinition,
    *,
    period_index: int,
    value: str,
    version_id: int,
) -> MarketStructureObservation:
    return MarketStructureObservation(
        series_code=definition.series_code,
        series_version=definition.series_version,
        actor_code=definition.actor_code,
        asset_code="TEST.ASSET",
        measure_concept=definition.measure_concept,
        effective_at=PERIODS[period_index],
        available_at=PERIODS[period_index],
        value=Decimal(value),
        unit=definition.canonical_unit,
        frequency=definition.frequency,
        source=definition.source,
        revision_number=0,
        is_proxy=definition.is_proxy,
        proxy_target_actor_code=definition.proxy_target_actor_code,
        proxy_methodology_ref=definition.proxy_methodology_ref,
        evidence=VersionedEvidenceReference(
            dataset="research.investor_flow_observation.v1",
            version_id=version_id,
            content_hash=HASH_A if definition.actor_code == "A" else HASH_B,
        ),
    )


def _complete_observations(
    first: MarketStructureSeriesDefinition,
    second: MarketStructureSeriesDefinition,
) -> tuple[MarketStructureObservation, ...]:
    values = (("10", "15", "25"), ("20", "18", "19"))
    rows: list[MarketStructureObservation] = []
    for series_index, definition in enumerate((first, second)):
        for period_index, value in enumerate(values[series_index]):
            rows.append(
                _observation(
                    definition,
                    period_index=period_index,
                    value=value,
                    version_id=series_index * 10 + period_index + 1,
                )
            )
    return tuple(rows)


def _coverage_for(
    observations: tuple[MarketStructureObservation, ...],
) -> tuple[SeriesPeriodCoverage, ...]:
    coverage: list[SeriesPeriodCoverage] = []
    for reference in _request().series:
        for effective_at in PERIODS:
            observed = tuple(
                sorted(
                    {
                        item.asset_code
                        for item in observations
                        if item.series_code == reference.series_code
                        and item.series_version == reference.series_version
                        and item.effective_at == effective_at
                    }
                )
            )
            coverage.append(
                SeriesPeriodCoverage(
                    series_code=reference.series_code,
                    series_version=reference.series_version,
                    effective_at=effective_at,
                    expected_asset_codes=("TEST.ASSET",),
                    observed_asset_codes=observed,
                    missing_asset_codes=tuple(sorted({"TEST.ASSET"} - set(observed))),
                )
            )
    return tuple(coverage)


def test_measure_concepts_distinguish_flow_holding_stock_and_transaction() -> None:
    assert {item.value for item in MarketStructureMeasureConcept} == {
        "flow",
        "holding",
        "stock",
        "transaction",
    }
    assert InvestorFlowMeasureKind.FUND_FLOW.value == "fund_flow"


def test_actor_definition_requires_versioned_revision_semantics() -> None:
    with pytest.raises(ValueError, match="revision_policy_ref"):
        replace(_actor("A"), revision_policy_ref="")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_actor("A"), effective_at=datetime(2025, 1, 1))
    with pytest.raises(ValueError, match="expires_at"):
        replace(_actor("A"), expires_at=PERIODS[0])


def test_series_rejects_measure_concept_relabelling_and_unlabelled_proxy() -> None:
    with pytest.raises(ValueError, match="not interchangeable"):
        replace(
            _series("A"),
            measure_kind=InvestorFlowMeasureKind.HOLDING_CHANGE,
        )
    with pytest.raises(ValueError, match="proxy_target_actor_code"):
        replace(_series("A", is_proxy=True), proxy_target_actor_code="")


def test_period_calendar_requires_canonical_versioned_aware_periods() -> None:
    calendar = _calendar()

    assert calendar.periods == PERIODS
    assert len(calendar.calendar_hash) == 64
    with pytest.raises(ValueError, match="strictly increasing"):
        replace(calendar, periods=(PERIODS[1], PERIODS[0], PERIODS[2]))
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(calendar, periods=(datetime(2025, 1, 1), *PERIODS[1:]))
    with pytest.raises(ValueError, match="calendar_version"):
        replace(calendar, calendar_version=0)


@pytest.mark.parametrize(
    ("calendar", "expected_blocker"),
    (
        (
            replace(_calendar(), calendar_code="OTHER_CALENDAR"),
            "period_calendar_identity_mismatch",
        ),
        (
            replace(_calendar(), frequency="weekly"),
            "period_calendar_frequency_mismatch",
        ),
        (
            replace(_calendar(), is_active=False),
            "period_calendar_unavailable",
        ),
        (
            replace(_calendar(), available_at=PERIODS[0], expires_at=AS_OF),
            "period_calendar_unavailable",
        ),
    ),
)
def test_period_calendar_mismatch_or_unavailable_fails_closed(
    calendar: MarketStructurePeriodCalendar,
    expected_blocker: str,
) -> None:
    first = _series("A")
    second = _series("B")
    observations = _complete_observations(first, second)

    snapshot = aggregate_market_structure(
        request=_request(),
        period_calendar=calendar,
        definitions=(first, second),
        observations=observations,
        coverage=_coverage_for(observations),
    )

    assert snapshot.status is MarketStructureResearchStatus.BLOCKED
    assert expected_blocker in snapshot.blocked_reasons


@pytest.mark.parametrize(
    ("coverage_transform", "expected_blocker"),
    (
        ("missing", "membership_coverage_incomplete"),
        ("duplicate", "membership_coverage_duplicate"),
    ),
)
def test_period_coverage_missing_or_duplicate_cell_fails_closed(
    coverage_transform: str,
    expected_blocker: str,
) -> None:
    first = _series("A")
    second = _series("B")
    observations = _complete_observations(first, second)
    complete = _coverage_for(observations)
    coverage = complete[:-1] if coverage_transform == "missing" else (*complete, complete[0])

    snapshot = aggregate_market_structure(
        request=_request(),
        period_calendar=_calendar(),
        definitions=(first, second),
        observations=observations,
        coverage=coverage,
    )

    assert snapshot.status is MarketStructureResearchStatus.BLOCKED
    assert expected_blocker in snapshot.blocked_reasons


def test_complete_aggregation_reports_all_descriptive_metrics_and_proxy_label() -> None:
    first = _series("A")
    second = _series("B", is_proxy=True)
    observations = _complete_observations(first, second)

    snapshot = aggregate_market_structure(
        request=_request(),
        period_calendar=_calendar(),
        definitions=(first, second),
        observations=observations,
        coverage=_coverage_for(observations),
    )

    assert snapshot.status is MarketStructureResearchStatus.AVAILABLE
    assert snapshot.research_only is True
    assert snapshot.must_not_use_for_decision is True
    assert snapshot.deterministic_conclusion is None
    assert snapshot.contains_proxy is True
    first_metrics, second_metrics = snapshot.actor_metrics
    assert (first_metrics.total, first_metrics.change, first_metrics.acceleration) == (
        Decimal("25"),
        Decimal("10"),
        Decimal("5"),
    )
    assert first_metrics.historical_percentile == Decimal("1")
    assert second_metrics.historical_percentile == Decimal(2) / Decimal(3)
    assert second_metrics.is_proxy is True
    assert second_metrics.proxy_methodology_ref == "governance://proxy/v1"
    difference = snapshot.cross_actor_differences[0]
    assert difference.total_difference == Decimal("6")
    assert difference.change_difference == Decimal("9")
    assert difference.acceleration_difference == Decimal("2")


def test_missing_history_fails_closed_without_partial_metrics_or_conclusion() -> None:
    first = _series("A")
    second = _series("B")
    observations = (_observation(first, period_index=0, value="10", version_id=1),)

    snapshot = aggregate_market_structure(
        request=_request(),
        period_calendar=_calendar(),
        definitions=(first, second),
        observations=observations,
        coverage=_coverage_for(observations),
    )

    assert snapshot.status is MarketStructureResearchStatus.BLOCKED
    assert snapshot.actor_metrics == ()
    assert snapshot.cross_actor_differences == ()
    assert snapshot.deterministic_conclusion is None
    assert "history_insufficient:A" in snapshot.blocked_reasons
    assert "history_insufficient:B" in snapshot.blocked_reasons


def test_cross_actor_comparison_rejects_mixed_measure_concepts() -> None:
    first = _series("A", concept=MarketStructureMeasureConcept.FLOW)
    second = _series("B", concept=MarketStructureMeasureConcept.STOCK)

    snapshot = aggregate_market_structure(
        request=_request(),
        period_calendar=_calendar(),
        definitions=(first, second),
        observations=(),
        coverage=_coverage_for(()),
    )

    assert snapshot.status is MarketStructureResearchStatus.BLOCKED
    assert "measure_concept_not_comparable" in snapshot.blocked_reasons


def test_evidence_hash_seals_inputs_outputs_and_version() -> None:
    first = _series("A")
    second = _series("B")
    observations = _complete_observations(first, second)
    snapshot = aggregate_market_structure(
        request=_request(),
        period_calendar=_calendar(),
        definitions=(first, second),
        observations=observations,
        coverage=_coverage_for(observations),
    )

    evidence = build_market_structure_evidence(
        request=_request(),
        snapshot=snapshot,
        period_calendar=_calendar(),
        actor_definitions=(_actor("A"), _actor("B")),
        series_definitions=(first, second),
        source_evidence=tuple(item.evidence for item in observations),
        governance_publications=(
            _publication_attestation(
                kind=MarketStructureGovernanceArtifactKind.PERIOD_CALENDAR,
                natural_key="calendar:TEST_MONTHLY_CALENDAR:v1",
                artifact_hash=_calendar().calendar_hash,
                observed_at=AS_OF,
                member_id="calendar-member",
            ),
            *(
                _publication_attestation(
                    kind=MarketStructureGovernanceArtifactKind.ACTOR,
                    natural_key=f"actor:TEST_TAXONOMY:v1:{actor.actor_code}",
                    artifact_hash=actor.definition_hash,
                    observed_at=actor.available_at,
                    member_id=f"actor-{actor.actor_code}",
                )
                for actor in (_actor("A"), _actor("B"))
            ),
            *(
                _publication_attestation(
                    kind=MarketStructureGovernanceArtifactKind.SERIES,
                    natural_key=f"series:{series.series_code}:v1",
                    artifact_hash=series.definition_hash,
                    observed_at=series.available_at,
                    member_id=f"series-{series.actor_code}",
                )
                for series in (first, second)
            ),
        ),
    )

    assert evidence.status is MarketStructureResearchStatus.AVAILABLE
    assert (
        len(evidence.input_hash) == len(evidence.output_hash) == len(evidence.evidence_hash) == 64
    )
    with pytest.raises(ValueError, match="evidence_hash mismatch"):
        replace(evidence, evidence_hash="0" * 64)
    with pytest.raises(ValueError, match="source_evidence conflicts"):
        replace(
            evidence,
            source_evidence=(
                VersionedEvidenceReference(
                    dataset="research.investor_flow_observation.v1",
                    version_id=999,
                    content_hash="d" * 64,
                ),
            ),
        )


class _Gateway:
    def __init__(
        self,
        definitions: tuple[MarketStructureSeriesDefinition, ...],
        observations: tuple[MarketStructureObservation, ...],
        membership_assets: tuple[str, ...] = ("TEST.ASSET",),
        period_calendar: MarketStructurePeriodCalendar | None = None,
        publications_enabled: bool = True,
    ) -> None:
        self._definitions = {(item.series_code, item.series_version): item for item in definitions}
        self._observations = observations
        self._membership_assets = membership_assets
        self._period_calendar = period_calendar or _calendar()
        self._publications_enabled = publications_enabled
        self.membership_calls: list[tuple[datetime, datetime]] = []
        self.saved: ImmutableMarketStructureEvidence | None = None

    def save_actor_definition(
        self,
        definition: InvestorActorDefinition,
    ) -> InvestorActorDefinition:
        return definition

    def get_actor_definition(
        self,
        *,
        taxonomy_code: str,
        taxonomy_version: int,
        actor_code: str,
        as_of_time: datetime,
    ) -> InvestorActorDefinition | None:
        del taxonomy_code, taxonomy_version, as_of_time
        return _actor(actor_code)

    def save_series_definition(
        self,
        definition: MarketStructureSeriesDefinition,
    ) -> MarketStructureSeriesDefinition:
        return definition

    def save_period_calendar(
        self,
        calendar: MarketStructurePeriodCalendar,
    ) -> MarketStructurePeriodCalendar:
        return calendar

    def get_period_calendar(
        self,
        reference: MarketStructurePeriodCalendarRef,
        *,
        as_of_time: datetime,
    ) -> MarketStructurePeriodCalendar | None:
        del as_of_time
        if (
            reference.calendar_code,
            reference.calendar_version,
        ) != (
            self._period_calendar.calendar_code,
            self._period_calendar.calendar_version,
        ):
            return None
        return self._period_calendar

    def get_series_definition(
        self,
        reference: MarketStructureSeriesRef,
        *,
        as_of_time: datetime,
    ) -> MarketStructureSeriesDefinition | None:
        del as_of_time
        return self._definitions.get((reference.series_code, reference.series_version))

    def list_series_observations(
        self,
        definition: MarketStructureSeriesDefinition,
        *,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
    ) -> tuple[MarketStructureObservation, ...]:
        return tuple(
            item for item in self._observations if item.series_code == definition.series_code
        )

    def resolve_asset_group_membership(
        self,
        *,
        group_code: str,
        group_revision: int,
        effective_at: datetime,
        knowledge_at: datetime,
        knowledge_scope: KnowledgeScope,
    ) -> PITMembershipSnapshot:
        self.membership_calls.append((effective_at, knowledge_at))
        return PITMembershipSnapshot(
            group_code=group_code,
            group_revision=group_revision,
            effective_at=effective_at,
            knowledge_at=knowledge_at,
            asset_codes=self._membership_assets,
            evidence=tuple(
                VersionedEvidenceReference(
                    dataset="research.asset_group_membership.v1",
                    version_id=1000 * len(self.membership_calls) + index,
                    content_hash=f"{index:x}" * 64,
                )
                for index, _asset_code in enumerate(self._membership_assets, start=1)
            ),
        )

    def add_evidence(
        self,
        evidence: ImmutableMarketStructureEvidence,
    ) -> ImmutableMarketStructureEvidence:
        self.saved = evidence
        return evidence

    def get_evidence(
        self,
        *,
        evidence_key: str,
        evidence_version: int,
    ) -> ImmutableMarketStructureEvidence | None:
        return self.saved

    def get_evidence_at(
        self,
        *,
        evidence_key: str,
        evidence_version: int,
        as_of_time: datetime,
    ) -> ImmutableMarketStructureEvidence | None:
        del evidence_key, evidence_version, as_of_time
        return self.saved

    def attest_actor(
        self,
        definition: InvestorActorDefinition,
        *,
        as_of_time: datetime,
    ) -> MarketStructurePublicationAttestation | None:
        del as_of_time
        if not self._publications_enabled:
            return None
        return _publication_attestation(
            kind=MarketStructureGovernanceArtifactKind.ACTOR,
            natural_key=(
                f"actor:{definition.taxonomy_code}:v{definition.taxonomy_version}:"
                f"{definition.actor_code}"
            ),
            artifact_hash=definition.definition_hash,
            observed_at=definition.available_at,
            member_id=f"actor-{definition.actor_code}",
        )

    def attest_series(
        self,
        definition: MarketStructureSeriesDefinition,
        *,
        as_of_time: datetime,
    ) -> MarketStructurePublicationAttestation | None:
        del as_of_time
        if not self._publications_enabled:
            return None
        return _publication_attestation(
            kind=MarketStructureGovernanceArtifactKind.SERIES,
            natural_key=f"series:{definition.series_code}:v{definition.series_version}",
            artifact_hash=definition.definition_hash,
            observed_at=definition.available_at,
            member_id=f"series-{definition.actor_code}",
        )

    def attest_period_calendar(
        self,
        calendar: MarketStructurePeriodCalendar,
        *,
        as_of_time: datetime,
    ) -> MarketStructurePublicationAttestation | None:
        del as_of_time
        if not self._publications_enabled:
            return None
        return _publication_attestation(
            kind=MarketStructureGovernanceArtifactKind.PERIOD_CALENDAR,
            natural_key=f"calendar:{calendar.calendar_code}:v{calendar.calendar_version}",
            artifact_hash=calendar.calendar_hash,
            observed_at=calendar.available_at,
            member_id="calendar-member",
        )


def test_application_resolves_membership_at_each_historical_observation_clock() -> None:
    first = _series("A")
    second = _series("B")
    observations = _complete_observations(first, second)
    gateway = _Gateway((first, second), observations)

    evidence = RunMarketStructureResearch(gateway, gateway).execute(_request())

    assert evidence.status is MarketStructureResearchStatus.AVAILABLE
    assert {call[0] for call in gateway.membership_calls} == set(PERIODS)
    assert all(knowledge_at == AS_OF for _, knowledge_at in gateway.membership_calls)
    payload = cast(dict[str, object], json.loads(evidence.payload_json))
    output = cast(dict[str, object], payload["output"])
    assert output["deterministic_conclusion"] is None


def test_application_blocks_and_seals_partial_membership_coverage() -> None:
    first = _series("A")
    second = _series("B")
    gateway = _Gateway(
        (first, second),
        _complete_observations(first, second),
        membership_assets=("EXTRA.ASSET", "TEST.ASSET"),
    )

    evidence = RunMarketStructureResearch(gateway, gateway).execute(_request())

    assert evidence.status is MarketStructureResearchStatus.BLOCKED
    payload = cast(dict[str, object], json.loads(evidence.payload_json))
    output = cast(dict[str, object], payload["output"])
    blockers = cast(list[str], output["blocked_reasons"])
    assert any(reason.startswith("membership_coverage_insufficient:") for reason in blockers)
    coverage = cast(list[dict[str, object]], output["coverage"])
    assert coverage
    assert all(item["expected_count"] == 2 for item in coverage)
    assert all(item["observed_count"] == 1 for item in coverage)
    assert all(item["missing_asset_codes"] == ["EXTRA.ASSET"] for item in coverage)


def test_application_calendar_exposes_and_blocks_whole_period_all_missing() -> None:
    first = _series("A")
    second = _series("B")
    observations = tuple(
        item for item in _complete_observations(first, second) if item.effective_at != PERIODS[1]
    )
    gateway = _Gateway((first, second), observations)

    evidence = RunMarketStructureResearch(gateway, gateway).execute(_request())

    assert evidence.status is MarketStructureResearchStatus.BLOCKED
    payload = cast(dict[str, object], json.loads(evidence.payload_json))
    input_payload = cast(dict[str, object], payload["input"])
    output = cast(dict[str, object], payload["output"])
    assert cast(dict[str, object], input_payload["period_calendar"])["calendar_hash"] == (
        _calendar().calendar_hash
    )
    assert {call[0] for call in gateway.membership_calls} == set(PERIODS)
    coverage = cast(list[dict[str, object]], output["coverage"])
    assert len(coverage) == len(_request().series) * len(PERIODS)
    missing_period = [item for item in coverage if item["effective_at"] == PERIODS[1].isoformat()]
    assert len(missing_period) == len(_request().series)
    assert all(item["expected_count"] == 1 for item in missing_period)
    assert all(item["observed_count"] == 0 for item in missing_period)
    blockers = cast(list[str], output["blocked_reasons"])
    assert f"period_all_series_missing:{PERIODS[1].isoformat()}" in blockers


def test_application_rejects_definition_not_publicly_available_at_request_time() -> None:
    first = replace(_series("A"), available_at=datetime(2025, 5, 1, tzinfo=UTC))
    second = _series("B")
    gateway = _Gateway((first, second), _complete_observations(first, second))

    evidence = RunMarketStructureResearch(gateway, gateway).execute(_request())

    assert evidence.status is MarketStructureResearchStatus.BLOCKED
    assert (
        "series_definition_unavailable:SERIES_A"
        in json.loads(evidence.payload_json)["output"]["blocked_reasons"]
    )


def test_application_rejects_unpublished_taxonomy_and_calendar() -> None:
    first = _series("A")
    second = _series("B")
    gateway = _Gateway(
        (first, second),
        _complete_observations(first, second),
        publications_enabled=False,
    )

    evidence = RunMarketStructureResearch(gateway, gateway).execute(_request())

    assert evidence.status is MarketStructureResearchStatus.BLOCKED
    blockers = json.loads(evidence.payload_json)["output"]["blocked_reasons"]
    assert any(reason.startswith("period_calendar_unpublished:") for reason in blockers)
    assert "series_definition_unpublished:SERIES_A" in blockers
    assert "series_definition_unpublished:SERIES_B" in blockers
    assert evidence.governance_publications == ()
