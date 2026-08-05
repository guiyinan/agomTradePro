from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.data_center.application.research_data_foundation import (
    ResearchDataFoundationFacade,
)
from apps.data_center.domain.pit import KnowledgeScope, PITQuality
from apps.data_center.domain.research_data_foundation import (
    ASSET_GROUP_MEMBERSHIP_DATASET,
    INVESTOR_FLOW_OBSERVATION_DATASET,
    OPERATING_OBSERVATION_DATASET,
    AssetGroupRevision,
    InvestorFlowDefinition,
    InvestorFlowMeasureKind,
    InvestorFlowObservation,
    ObservationValueKind,
    OperatingMetricDefinition,
    OperatingObservation,
    PITAssetGroupMembership,
)
from apps.data_center.infrastructure.models import AssetMasterModel
from apps.data_center.infrastructure.pit_models import PITFactVersionModel
from apps.data_center.infrastructure.research_data_foundation_models import (
    AssetGroupRevisionModel,
    InvestorFlowDefinitionModel,
    OperatingMetricDefinitionModel,
)
from apps.data_center.infrastructure.research_data_foundation_repository import (
    ResearchDataFoundationRepository,
)

EFFECTIVE_AT = datetime(2025, 1, 1, tzinfo=UTC)
FIRST_AVAILABLE_AT = datetime(2025, 1, 10, tzinfo=UTC)
SECOND_AVAILABLE_AT = datetime(2025, 2, 10, tzinfo=UTC)
INGESTED_AT = datetime(2025, 3, 1, tzinfo=UTC)


def _facade() -> ResearchDataFoundationFacade:
    return ResearchDataFoundationFacade(ResearchDataFoundationRepository(clock=lambda: INGESTED_AT))


def _metric_definition() -> OperatingMetricDefinition:
    return OperatingMetricDefinition(
        metric_code="TEST_OPERATING_METRIC",
        definition_version=1,
        name="Test operating metric",
        canonical_unit="units",
        frequency="quarterly",
        source="test_governed_source",
        effective_at=EFFECTIVE_AT,
    )


def _operating_observation(
    value_kind: ObservationValueKind,
) -> OperatingObservation:
    lineage = {
        ObservationValueKind.OBSERVED_FACT: {"source_record_id": "fact-row-1"},
        ObservationValueKind.HUMAN_ASSUMPTION: {"assumption_set_id": "assumption-v1"},
        ObservationValueKind.MODEL_INFERENCE: {"model_version": "model-v1"},
    }[value_kind]
    return OperatingObservation(
        metric_code="TEST_OPERATING_METRIC",
        definition_version=1,
        subject_type="asset",
        subject_code="TEST.ASSET",
        effective_at=EFFECTIVE_AT,
        effective_to=None,
        available_at=FIRST_AVAILABLE_AT,
        revision_number=0,
        value=Decimal("12.50"),
        unit="units",
        frequency="quarterly",
        source="test_governed_source",
        value_kind=value_kind,
        **lineage,
    )


@pytest.mark.django_db
def test_operating_metric_versions_are_governed_and_origins_stay_separate() -> None:
    facade = _facade()
    definition = facade.register_operating_metric(_metric_definition())
    fact = facade.record_operating_observation(
        _operating_observation(ObservationValueKind.OBSERVED_FACT)
    )
    assumption = facade.record_operating_observation(
        _operating_observation(ObservationValueKind.HUMAN_ASSUMPTION)
    )

    assert definition == _metric_definition()
    assert OperatingMetricDefinitionModel._default_manager.count() == 1
    assert fact.dataset == OPERATING_OBSERVATION_DATASET
    assert fact.pit_quality is PITQuality.VERIFIED
    assert assumption.pit_quality is PITQuality.ESTIMATED
    assert fact.business_key != assumption.business_key
    assert assumption.payload["value_kind"] == "human_assumption"
    facts = facade.list_operating_observations(
        metric_code="TEST_OPERATING_METRIC",
        definition_version=1,
        value_kind=ObservationValueKind.OBSERVED_FACT,
        as_of_time=INGESTED_AT,
        knowledge_scope=KnowledgeScope.PUBLIC,
    )
    assert [row.version_id for row in facts] == [fact.version_id]


@pytest.mark.django_db
def test_operating_revision_is_idempotent_but_conflicting_content_fails_closed() -> None:
    facade = _facade()
    facade.register_operating_metric(_metric_definition())
    observation = _operating_observation(ObservationValueKind.OBSERVED_FACT)

    first = facade.record_operating_observation(observation)
    repeated = facade.record_operating_observation(observation)

    assert repeated.version_id == first.version_id
    with pytest.raises(ValueError, match="conflicting content"):
        facade.record_operating_observation(replace(observation, value=Decimal("99")))
    assert (
        PITFactVersionModel._default_manager.filter(dataset=OPERATING_OBSERVATION_DATASET).count()
        == 1
    )


@pytest.mark.django_db
def test_flow_revisions_preserve_measure_and_proxy_semantics_under_as_of_query() -> None:
    facade = _facade()
    definition = InvestorFlowDefinition(
        flow_code="TEST_GOVERNED_FLOW",
        definition_version=1,
        actor_code="TEST_ACTOR",
        actor_name="Test actor",
        measure_kind=InvestorFlowMeasureKind.HOLDING_CHANGE,
        canonical_unit="shares",
        frequency="daily",
        source="test_governed_source",
        effective_at=EFFECTIVE_AT,
        is_proxy=True,
        proxy_target_actor_code="TARGET_ACTOR",
        proxy_methodology_ref="governance://test-flow/v1",
    )
    facade.register_investor_flow(definition)
    first = InvestorFlowObservation(
        flow_code="TEST_GOVERNED_FLOW",
        definition_version=1,
        scope_type="market",
        scope_code="TEST.MARKET",
        effective_at=EFFECTIVE_AT,
        effective_to=None,
        available_at=FIRST_AVAILABLE_AT,
        revision_number=0,
        value=Decimal("100"),
        measure_kind=InvestorFlowMeasureKind.HOLDING_CHANGE,
        unit="shares",
        frequency="daily",
        source="test_governed_source",
        source_record_id="flow-row-v0",
        is_proxy=True,
        proxy_target_actor_code="TARGET_ACTOR",
        proxy_methodology_ref="governance://test-flow/v1",
    )
    second = replace(
        first,
        available_at=SECOND_AVAILABLE_AT,
        revision_number=1,
        value=Decimal("120"),
        source_record_id="flow-row-v1",
    )
    facade.record_investor_flow(first)
    facade.record_investor_flow(second)

    before_revision = facade.list_investor_flow_observations(
        flow_code="TEST_GOVERNED_FLOW",
        definition_version=1,
        as_of_time=datetime(2025, 1, 31, tzinfo=UTC),
        knowledge_scope=KnowledgeScope.PUBLIC,
    )
    after_revision = facade.list_investor_flow_observations(
        flow_code="TEST_GOVERNED_FLOW",
        definition_version=1,
        as_of_time=datetime(2025, 2, 28, tzinfo=UTC),
        knowledge_scope=KnowledgeScope.PUBLIC,
    )

    assert InvestorFlowDefinitionModel._default_manager.count() == 1
    assert before_revision[0].revision_number == 0
    assert after_revision[0].revision_number == 1
    assert after_revision[0].dataset == INVESTOR_FLOW_OBSERVATION_DATASET
    assert after_revision[0].payload["measure_kind"] == "holding_change"
    assert after_revision[0].payload["is_proxy"] is True
    assert after_revision[0].payload["proxy_methodology_ref"] == "governance://test-flow/v1"


@pytest.mark.django_db
def test_asset_group_membership_reuses_pit_and_requires_canonical_asset() -> None:
    facade = _facade()
    facade.register_asset_group(
        AssetGroupRevision(
            group_code="TEST_CUSTOM_GROUP",
            revision=1,
            name="Test custom group",
            source="test_governed_source",
            effective_at=EFFECTIVE_AT,
        )
    )
    membership = PITAssetGroupMembership(
        group_code="TEST_CUSTOM_GROUP",
        group_revision=1,
        asset_code="TEST.ASSET",
        effective_at=EFFECTIVE_AT,
        effective_to=datetime(2025, 6, 1, tzinfo=UTC),
        available_at=FIRST_AVAILABLE_AT,
        revision_number=0,
        source="test_governed_source",
        source_record_id="membership-row-1",
    )

    with pytest.raises(ValueError, match="asset master"):
        facade.record_asset_group_membership(membership)
    AssetMasterModel._default_manager.create(
        code="TEST.ASSET",
        name="Test asset",
        short_name="Test",
        asset_type="stock",
        exchange="SSE",
    )
    saved = facade.record_asset_group_membership(membership)

    assert AssetGroupRevisionModel._default_manager.count() == 1
    assert saved.dataset == ASSET_GROUP_MEMBERSHIP_DATASET
    before_effective = facade.list_asset_group_memberships(
        group_code="TEST_CUSTOM_GROUP",
        group_revision=1,
        as_of_time=datetime(2024, 12, 31, tzinfo=UTC),
        knowledge_scope=KnowledgeScope.PUBLIC,
    )
    while_effective = facade.list_asset_group_memberships(
        group_code="TEST_CUSTOM_GROUP",
        group_revision=1,
        as_of_time=datetime(2025, 2, 1, tzinfo=UTC),
        knowledge_scope=KnowledgeScope.PUBLIC,
    )
    after_expiry = facade.list_asset_group_memberships(
        group_code="TEST_CUSTOM_GROUP",
        group_revision=1,
        as_of_time=datetime(2025, 7, 1, tzinfo=UTC),
        knowledge_scope=KnowledgeScope.PUBLIC,
    )
    assert before_effective == []
    assert [row.payload["asset_code"] for row in while_effective] == ["TEST.ASSET"]
    assert after_expiry == []
