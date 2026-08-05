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
    EmpiricalPercentileMethod,
    ImmutableMarketStructureEvidence,
    InvestorActorDefinition,
    MarketStructureAggregationPolicy,
    MarketStructureMeasureConcept,
    MarketStructureObservation,
    MarketStructureResearchRequest,
    MarketStructureResearchStatus,
    MarketStructureSeriesDefinition,
    MarketStructureSeriesRef,
    PITMembershipSnapshot,
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


def _request() -> MarketStructureResearchRequest:
    return MarketStructureResearchRequest(
        evidence_key="TEST_EVIDENCE",
        evidence_version=1,
        as_of_time=AS_OF,
        knowledge_scope=KnowledgeScope.PUBLIC,
        group_code="TEST_GROUP",
        group_revision=1,
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


def test_complete_aggregation_reports_all_descriptive_metrics_and_proxy_label() -> None:
    first = _series("A")
    second = _series("B", is_proxy=True)

    snapshot = aggregate_market_structure(
        request=_request(),
        definitions=(first, second),
        observations=_complete_observations(first, second),
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

    snapshot = aggregate_market_structure(
        request=_request(),
        definitions=(first, second),
        observations=(_observation(first, period_index=0, value="10", version_id=1),),
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
        definitions=(first, second),
        observations=(),
    )

    assert snapshot.status is MarketStructureResearchStatus.BLOCKED
    assert "measure_concept_not_comparable" in snapshot.blocked_reasons


def test_evidence_hash_seals_inputs_outputs_and_version() -> None:
    first = _series("A")
    second = _series("B")
    observations = _complete_observations(first, second)
    snapshot = aggregate_market_structure(
        request=_request(),
        definitions=(first, second),
        observations=observations,
    )

    evidence = build_market_structure_evidence(
        request=_request(),
        snapshot=snapshot,
        actor_definitions=(_actor("A"), _actor("B")),
        series_definitions=(first, second),
        source_evidence=tuple(item.evidence for item in observations),
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
    ) -> None:
        self._definitions = {(item.series_code, item.series_version): item for item in definitions}
        self._observations = observations
        self._membership_assets = membership_assets
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


def test_application_resolves_membership_at_each_historical_observation_clock() -> None:
    first = _series("A")
    second = _series("B")
    observations = _complete_observations(first, second)
    gateway = _Gateway((first, second), observations)

    evidence = RunMarketStructureResearch(gateway).execute(_request())

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

    evidence = RunMarketStructureResearch(gateway).execute(_request())

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


def test_application_rejects_definition_not_publicly_available_at_request_time() -> None:
    first = replace(_series("A"), available_at=datetime(2025, 5, 1, tzinfo=UTC))
    second = _series("B")
    gateway = _Gateway((first, second), _complete_observations(first, second))

    evidence = RunMarketStructureResearch(gateway).execute(_request())

    assert evidence.status is MarketStructureResearchStatus.BLOCKED
    assert (
        "series_definition_unavailable:SERIES_A"
        in json.loads(evidence.payload_json)["output"]["blocked_reasons"]
    )
