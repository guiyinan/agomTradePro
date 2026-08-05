"""Django repository coverage for the complete R2 market-structure slice."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest
from django.core.exceptions import ValidationError

from apps.data_center.application.market_structure import (
    MarketStructureGovernanceFacade,
    RunMarketStructureResearch,
)
from apps.data_center.application.research_data_foundation import (
    ResearchDataFoundationFacade,
)
from apps.data_center.domain.market_structure import (
    EmpiricalPercentileMethod,
    InvestorActorDefinition,
    MarketStructureAggregationPolicy,
    MarketStructureMeasureConcept,
    MarketStructureResearchRequest,
    MarketStructureResearchStatus,
    MarketStructureSeriesDefinition,
    MarketStructureSeriesRef,
)
from apps.data_center.domain.pit import KnowledgeScope
from apps.data_center.domain.research_data_foundation import (
    AssetGroupRevision,
    InvestorFlowDefinition,
    InvestorFlowMeasureKind,
    InvestorFlowObservation,
    PITAssetGroupMembership,
)
from apps.data_center.infrastructure.market_structure_models import (
    InvestorActorDefinitionModel,
    MarketStructureResearchEvidenceModel,
    MarketStructureSeriesDefinitionModel,
)
from apps.data_center.infrastructure.market_structure_repository import (
    MarketStructureResearchRepository,
)
from apps.data_center.infrastructure.models import AssetMasterModel
from apps.data_center.infrastructure.research_data_foundation_repository import (
    ResearchDataFoundationRepository,
)

GROUP_EFFECTIVE = datetime(2025, 1, 1, tzinfo=UTC)
GROUP_SWITCH = datetime(2025, 4, 1, tzinfo=UTC)
AS_OF = datetime(2025, 5, 1, tzinfo=UTC)
INGESTED_AT = datetime(2025, 6, 1, tzinfo=UTC)
PERIODS = (
    datetime(2025, 1, 1, tzinfo=UTC),
    datetime(2025, 2, 1, tzinfo=UTC),
    datetime(2025, 3, 1, tzinfo=UTC),
)


def _actor(actor_code: str) -> InvestorActorDefinition:
    return InvestorActorDefinition(
        taxonomy_code="TEST_TAXONOMY",
        taxonomy_version=1,
        actor_code=actor_code,
        actor_name=f"Actor {actor_code}",
        source="test_governance",
        revision_policy_ref="governance://actor-revision/v1",
        effective_at=GROUP_EFFECTIVE,
    )


def _flow_definition(actor_code: str, *, is_proxy: bool) -> InvestorFlowDefinition:
    return InvestorFlowDefinition(
        flow_code=f"TEST_FLOW_{actor_code}",
        definition_version=1,
        actor_code=actor_code,
        actor_name=f"Actor {actor_code}",
        measure_kind=InvestorFlowMeasureKind.FUND_FLOW,
        canonical_unit="CNY",
        frequency="monthly",
        source="test_source",
        effective_at=GROUP_EFFECTIVE,
        is_proxy=is_proxy,
        proxy_target_actor_code="TARGET_ACTOR" if is_proxy else "",
        proxy_methodology_ref="governance://proxy/v1" if is_proxy else "",
    )


def _series(actor_code: str, *, is_proxy: bool) -> MarketStructureSeriesDefinition:
    return MarketStructureSeriesDefinition(
        series_code=f"TEST_SERIES_{actor_code}",
        series_version=1,
        flow_code=f"TEST_FLOW_{actor_code}",
        flow_definition_version=1,
        taxonomy_code="TEST_TAXONOMY",
        taxonomy_version=1,
        actor_code=actor_code,
        measure_concept=MarketStructureMeasureConcept.FLOW,
        measure_kind=InvestorFlowMeasureKind.FUND_FLOW,
        canonical_unit="CNY",
        frequency="monthly",
        source="test_source",
        revision_policy_ref="governance://flow-revision/v1",
        effective_at=GROUP_EFFECTIVE,
        is_proxy=is_proxy,
        proxy_target_actor_code="TARGET_ACTOR" if is_proxy else "",
        proxy_methodology_ref="governance://proxy/v1" if is_proxy else "",
    )


def _request(*, evidence_key: str = "TEST_MARKET_STRUCTURE") -> MarketStructureResearchRequest:
    return MarketStructureResearchRequest(
        evidence_key=evidence_key,
        evidence_version=1,
        as_of_time=AS_OF,
        knowledge_scope=KnowledgeScope.PUBLIC,
        group_code="TEST_GROUP",
        group_revision=1,
        method_version="r2-component-v1",
        series=(
            MarketStructureSeriesRef(series_code="TEST_SERIES_A", series_version=1),
            MarketStructureSeriesRef(series_code="TEST_SERIES_B", series_version=1),
        ),
        policy=MarketStructureAggregationPolicy(
            policy_code="TEST_POLICY",
            policy_version=1,
            minimum_history_observations=3,
            minimum_actor_count=2,
            percentile_method=EmpiricalPercentileMethod.WEAK_EMPIRICAL_CDF,
        ),
    )


def _prepare_governance_and_membership(
    foundation: ResearchDataFoundationFacade,
    governance: MarketStructureGovernanceFacade,
) -> None:
    AssetMasterModel._default_manager.bulk_create(
        [
            AssetMasterModel(
                code="HISTORICAL.ASSET",
                name="Historical asset",
                short_name="Historical",
                asset_type="stock",
                exchange="SSE",
            ),
            AssetMasterModel(
                code="CURRENT.ASSET",
                name="Current asset",
                short_name="Current",
                asset_type="stock",
                exchange="SSE",
            ),
        ]
    )
    foundation.register_asset_group(
        AssetGroupRevision(
            group_code="TEST_GROUP",
            revision=1,
            name="Test group",
            source="test_membership_source",
            effective_at=GROUP_EFFECTIVE,
        )
    )
    foundation.record_asset_group_membership(
        PITAssetGroupMembership(
            group_code="TEST_GROUP",
            group_revision=1,
            asset_code="HISTORICAL.ASSET",
            effective_at=GROUP_EFFECTIVE,
            effective_to=GROUP_SWITCH,
            available_at=GROUP_EFFECTIVE,
            revision_number=0,
            source="test_membership_source",
            source_record_id="historical-membership",
        )
    )
    foundation.record_asset_group_membership(
        PITAssetGroupMembership(
            group_code="TEST_GROUP",
            group_revision=1,
            asset_code="CURRENT.ASSET",
            effective_at=GROUP_SWITCH,
            effective_to=None,
            available_at=GROUP_SWITCH,
            revision_number=0,
            source="test_membership_source",
            source_record_id="current-membership",
        )
    )
    for actor_code, is_proxy in (("A", False), ("B", True)):
        governance.register_actor(_actor(actor_code))
        foundation.register_investor_flow(_flow_definition(actor_code, is_proxy=is_proxy))
        governance.register_series(_series(actor_code, is_proxy=is_proxy))


def _record_observations(foundation: ResearchDataFoundationFacade) -> None:
    values = {
        "A": ("10", "15", "25"),
        "B": ("20", "18", "19"),
    }
    for actor_code, is_proxy in (("A", False), ("B", True)):
        for period_index, effective_at in enumerate(PERIODS):
            for asset_code, multiplier in (
                ("HISTORICAL.ASSET", Decimal("1")),
                ("CURRENT.ASSET", Decimal("100")),
            ):
                foundation.record_investor_flow(
                    InvestorFlowObservation(
                        flow_code=f"TEST_FLOW_{actor_code}",
                        definition_version=1,
                        scope_type="asset",
                        scope_code=asset_code,
                        effective_at=effective_at,
                        effective_to=None,
                        available_at=effective_at,
                        revision_number=0,
                        value=Decimal(values[actor_code][period_index]) * multiplier,
                        measure_kind=InvestorFlowMeasureKind.FUND_FLOW,
                        unit="CNY",
                        frequency="monthly",
                        source="test_source",
                        source_record_id=(f"{actor_code}-{asset_code}-{period_index}"),
                        is_proxy=is_proxy,
                        proxy_target_actor_code="TARGET_ACTOR" if is_proxy else "",
                        proxy_methodology_ref=("governance://proxy/v1" if is_proxy else ""),
                    )
                )


@pytest.mark.django_db
def test_repository_run_uses_historical_membership_and_persists_immutable_evidence() -> None:
    foundation_repository = ResearchDataFoundationRepository(clock=lambda: INGESTED_AT)
    market_repository = MarketStructureResearchRepository()
    foundation = ResearchDataFoundationFacade(foundation_repository)
    governance = MarketStructureGovernanceFacade(market_repository)
    _prepare_governance_and_membership(foundation, governance)
    _record_observations(foundation)

    evidence = RunMarketStructureResearch(market_repository).execute(_request())

    assert evidence.status is MarketStructureResearchStatus.AVAILABLE
    assert evidence.research_only is True
    assert evidence.must_not_use_for_decision is True
    assert evidence.must_not_execute is True
    assert InvestorActorDefinitionModel._default_manager.count() == 2
    assert MarketStructureSeriesDefinitionModel._default_manager.count() == 2
    assert MarketStructureResearchEvidenceModel._default_manager.count() == 1
    payload = cast(dict[str, object], json.loads(evidence.payload_json))
    output = cast(dict[str, object], payload["output"])
    metrics = cast(list[dict[str, object]], output["actor_metrics"])
    assert [item["total"] for item in metrics] == ["25", "19"]
    assert output["contains_proxy"] is True
    assert output["deterministic_conclusion"] is None

    model = MarketStructureResearchEvidenceModel._default_manager.get()
    model.status = MarketStructureResearchStatus.BLOCKED.value
    with pytest.raises(ValidationError, match="immutable"):
        model.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        model.delete()


@pytest.mark.django_db
def test_no_flow_data_persists_blocked_research_only_evidence_without_conclusion() -> None:
    foundation = ResearchDataFoundationFacade(
        ResearchDataFoundationRepository(clock=lambda: INGESTED_AT)
    )
    market_repository = MarketStructureResearchRepository()
    governance = MarketStructureGovernanceFacade(market_repository)
    _prepare_governance_and_membership(foundation, governance)

    evidence = RunMarketStructureResearch(market_repository).execute(
        _request(evidence_key="TEST_NO_DATA")
    )

    assert evidence.status is MarketStructureResearchStatus.BLOCKED
    payload = cast(dict[str, object], json.loads(evidence.payload_json))
    output = cast(dict[str, object], payload["output"])
    blockers = cast(list[str], output["blocked_reasons"])
    assert "history_insufficient:A" in blockers
    assert "history_insufficient:B" in blockers
    assert output["actor_metrics"] == []
    assert output["deterministic_conclusion"] is None
    assert MarketStructureResearchEvidenceModel._default_manager.filter(
        evidence_key="TEST_NO_DATA"
    ).exists()
