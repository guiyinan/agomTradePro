from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.data_center.application.research_data_foundation import (
    ResearchDataFoundationFacade,
)
from apps.data_center.domain.pit import KnowledgeScope, PITFactVersion
from apps.data_center.domain.research_data_foundation import (
    ASSET_GROUP_MEMBERSHIP_DATASET,
    OPERATING_OBSERVATION_DATASET,
    AssetGroupRevision,
    InvestorFlowDefinition,
    InvestorFlowMeasureKind,
    InvestorFlowObservation,
    ObservationValueKind,
    OperatingMetricDefinition,
    OperatingObservation,
    PITAssetGroupMembership,
    validate_asset_group_membership,
    validate_investor_flow_observation,
    validate_operating_observation,
)

EFFECTIVE_AT = datetime(2025, 1, 1, tzinfo=UTC)
AVAILABLE_AT = datetime(2025, 1, 10, tzinfo=UTC)


def _metric_definition() -> OperatingMetricDefinition:
    return OperatingMetricDefinition(
        metric_code="PILOT_METRIC",
        definition_version=1,
        name="Pilot metric",
        canonical_unit="unit",
        frequency="quarterly",
        source="governed_source",
        effective_at=EFFECTIVE_AT,
    )


def _operating_observation(
    value_kind: ObservationValueKind = ObservationValueKind.OBSERVED_FACT,
) -> OperatingObservation:
    lineage = {
        ObservationValueKind.OBSERVED_FACT: {"source_record_id": "source-row-1"},
        ObservationValueKind.HUMAN_ASSUMPTION: {"assumption_set_id": "assumption-v1"},
        ObservationValueKind.MODEL_INFERENCE: {"model_version": "model-v1"},
    }[value_kind]
    return OperatingObservation(
        metric_code="PILOT_METRIC",
        definition_version=1,
        subject_type="asset",
        subject_code="TEST.ASSET",
        effective_at=EFFECTIVE_AT,
        effective_to=None,
        available_at=AVAILABLE_AT,
        revision_number=0,
        value=Decimal("12.5"),
        unit="unit",
        frequency="quarterly",
        source="governed_source",
        value_kind=value_kind,
        **lineage,
    )


def _flow_definition(*, is_proxy: bool = True) -> InvestorFlowDefinition:
    return InvestorFlowDefinition(
        flow_code="PILOT_FLOW",
        definition_version=1,
        actor_code="GOVERNED_ACTOR",
        actor_name="Governed actor",
        measure_kind=InvestorFlowMeasureKind.HOLDING_CHANGE,
        canonical_unit="shares",
        frequency="daily",
        source="governed_source",
        effective_at=EFFECTIVE_AT,
        is_proxy=is_proxy,
        proxy_target_actor_code="TARGET_ACTOR" if is_proxy else "",
        proxy_methodology_ref="governance://flow-method/v1" if is_proxy else "",
    )


def _flow_observation(*, is_proxy: bool = True) -> InvestorFlowObservation:
    return InvestorFlowObservation(
        flow_code="PILOT_FLOW",
        definition_version=1,
        scope_type="market",
        scope_code="TEST.MARKET",
        effective_at=EFFECTIVE_AT,
        effective_to=None,
        available_at=AVAILABLE_AT,
        revision_number=0,
        value=Decimal("100"),
        measure_kind=InvestorFlowMeasureKind.HOLDING_CHANGE,
        unit="shares",
        frequency="daily",
        source="governed_source",
        source_record_id="flow-row-1",
        is_proxy=is_proxy,
        proxy_target_actor_code="TARGET_ACTOR" if is_proxy else "",
        proxy_methodology_ref="governance://flow-method/v1" if is_proxy else "",
    )


@pytest.mark.parametrize("value_kind", list(ObservationValueKind))
def test_operating_observation_requires_exactly_one_matching_lineage(
    value_kind: ObservationValueKind,
) -> None:
    observation = _operating_observation(value_kind)

    assert observation.value_kind is value_kind
    assert observation.lineage_ref


def test_operating_observation_rejects_mixed_fact_and_assumption_lineage() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        replace(_operating_observation(), assumption_set_id="assumption-v1")


def test_observed_fact_cannot_be_timestamped_before_it_exists() -> None:
    with pytest.raises(ValueError, match="available before"):
        replace(
            _operating_observation(),
            available_at=EFFECTIVE_AT - timedelta(seconds=1),
        )


@pytest.mark.parametrize("field", ["unit", "frequency", "source"])
def test_operating_definition_rejects_semantic_drift(field: str) -> None:
    observation = replace(_operating_observation(), **{field: "different"})

    with pytest.raises(ValueError, match="conflicts"):
        validate_operating_observation(_metric_definition(), observation)


def test_operating_definition_rejects_naive_governance_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_metric_definition(), effective_at=datetime(2025, 1, 1))


def test_investor_flow_measure_kinds_keep_balance_holdings_and_trades_distinct() -> None:
    assert {item.value for item in InvestorFlowMeasureKind} == {
        "capital_balance",
        "holding_change",
        "transaction_net_flow",
    }


def test_proxy_flow_requires_target_and_methodology_while_direct_flow_forbids_them() -> None:
    with pytest.raises(ValueError, match="proxy_target_actor_code"):
        replace(_flow_definition(), proxy_target_actor_code="")
    with pytest.raises(ValueError, match="direct flow"):
        replace(
            _flow_definition(is_proxy=False),
            proxy_target_actor_code="TARGET_ACTOR",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("measure_kind", InvestorFlowMeasureKind.TRANSACTION_NET_FLOW),
        ("unit", "CNY"),
        ("frequency", "weekly"),
        ("source", "other_source"),
    ],
)
def test_flow_definition_rejects_measure_source_or_proxy_drift(
    field: str,
    value: object,
) -> None:
    observation = replace(_flow_observation(), **{field: value})

    with pytest.raises(ValueError, match="conflicts"):
        validate_investor_flow_observation(_flow_definition(), observation)


def test_flow_definition_rejects_proxy_status_drift() -> None:
    observation = replace(
        _flow_observation(),
        is_proxy=False,
        proxy_target_actor_code="",
        proxy_methodology_ref="",
    )

    with pytest.raises(ValueError, match="conflicts"):
        validate_investor_flow_observation(_flow_definition(), observation)


def test_asset_group_membership_requires_matching_revision_and_source() -> None:
    definition = AssetGroupRevision(
        group_code="CUSTOM_GROUP",
        revision=2,
        name="Custom group",
        source="governed_source",
        effective_at=EFFECTIVE_AT,
    )
    membership = PITAssetGroupMembership(
        group_code="CUSTOM_GROUP",
        group_revision=2,
        asset_code="TEST.ASSET",
        effective_at=EFFECTIVE_AT,
        effective_to=None,
        available_at=AVAILABLE_AT,
        revision_number=0,
        source="governed_source",
        source_record_id="membership-row-1",
    )

    validate_asset_group_membership(definition, membership)
    with pytest.raises(ValueError, match="conflicts"):
        validate_asset_group_membership(definition, replace(membership, group_revision=3))


class _Gateway:
    def __init__(self) -> None:
        self.query: dict[str, Any] = {}

    def save_operating_metric_definition(
        self, definition: OperatingMetricDefinition
    ) -> OperatingMetricDefinition:
        return definition

    def save_investor_flow_definition(
        self, definition: InvestorFlowDefinition
    ) -> InvestorFlowDefinition:
        return definition

    def save_asset_group_revision(self, definition: AssetGroupRevision) -> AssetGroupRevision:
        return definition

    def append_operating_observation(self, observation: OperatingObservation) -> PITFactVersion:
        raise NotImplementedError

    def append_investor_flow_observation(
        self, observation: InvestorFlowObservation
    ) -> PITFactVersion:
        raise NotImplementedError

    def append_asset_group_membership(self, membership: PITAssetGroupMembership) -> PITFactVersion:
        raise NotImplementedError

    def query_versions(
        self,
        *,
        dataset: str,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
        filters: dict[str, Any],
    ) -> list[PITFactVersion]:
        self.query = {
            "dataset": dataset,
            "as_of_time": as_of_time,
            "knowledge_scope": knowledge_scope,
            "filters": filters,
        }
        return []


def test_facade_forces_explicit_operating_value_kind_filter() -> None:
    gateway = _Gateway()
    facade = ResearchDataFoundationFacade(gateway)

    facade.list_operating_observations(
        metric_code="PILOT_METRIC",
        definition_version=1,
        value_kind=ObservationValueKind.OBSERVED_FACT,
        as_of_time=AVAILABLE_AT,
        knowledge_scope=KnowledgeScope.PUBLIC,
    )

    assert gateway.query == {
        "dataset": OPERATING_OBSERVATION_DATASET,
        "as_of_time": AVAILABLE_AT,
        "knowledge_scope": KnowledgeScope.PUBLIC,
        "filters": {
            "metric_code": "PILOT_METRIC",
            "definition_version": 1,
            "value_kind": "observed_fact",
        },
    }


def test_facade_membership_query_preserves_group_revision_and_as_of_clock() -> None:
    gateway = _Gateway()
    facade = ResearchDataFoundationFacade(gateway)

    facade.list_asset_group_memberships(
        group_code="CUSTOM_GROUP",
        group_revision=2,
        as_of_time=AVAILABLE_AT,
        knowledge_scope=KnowledgeScope.SYSTEM,
    )

    assert gateway.query["dataset"] == ASSET_GROUP_MEMBERSHIP_DATASET
    assert gateway.query["filters"] == {
        "group_code": "CUSTOM_GROUP",
        "group_revision": 2,
    }


def test_facade_rejects_naive_as_of_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ResearchDataFoundationFacade(_Gateway()).list_asset_group_memberships(
            group_code="CUSTOM_GROUP",
            group_revision=2,
            as_of_time=datetime(2025, 1, 10),
            knowledge_scope=KnowledgeScope.PUBLIC,
        )
