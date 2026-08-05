"""Application facade for governed R1/R2 research-data foundations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from apps.data_center.domain.pit import KnowledgeScope, PITFactVersion
from apps.data_center.domain.research_data_foundation import (
    ASSET_GROUP_MEMBERSHIP_DATASET,
    INVESTOR_FLOW_OBSERVATION_DATASET,
    OPERATING_OBSERVATION_DATASET,
    AssetGroupRevision,
    InvestorFlowDefinition,
    InvestorFlowObservation,
    ObservationValueKind,
    OperatingMetricDefinition,
    OperatingObservation,
    PITAssetGroupMembership,
)


class ResearchDataFoundationGateway(Protocol):
    """Persistence boundary consumed by the R1/R2 application facade."""

    def save_operating_metric_definition(
        self,
        definition: OperatingMetricDefinition,
    ) -> OperatingMetricDefinition:
        """Persist an operating metric definition version."""

    def save_investor_flow_definition(
        self,
        definition: InvestorFlowDefinition,
    ) -> InvestorFlowDefinition:
        """Persist an investor-flow definition version."""

    def save_asset_group_revision(
        self,
        definition: AssetGroupRevision,
    ) -> AssetGroupRevision:
        """Persist a custom asset-group revision."""

    def append_operating_observation(
        self,
        observation: OperatingObservation,
    ) -> PITFactVersion:
        """Append one governed operating observation."""

    def append_investor_flow_observation(
        self,
        observation: InvestorFlowObservation,
    ) -> PITFactVersion:
        """Append one governed investor-flow observation."""

    def append_asset_group_membership(
        self,
        membership: PITAssetGroupMembership,
    ) -> PITFactVersion:
        """Append one asset-group membership version."""

    def query_versions(
        self,
        *,
        dataset: str,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
        filters: dict[str, Any],
    ) -> list[PITFactVersion]:
        """Query exact PIT versions under an explicit clock."""

    def get_operating_fact_versions(
        self,
        version_ids: tuple[int, ...],
        *,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
    ) -> list[PITFactVersion]:
        """Return requested operating versions only when latest and knowable."""


class ResearchDataFoundationFacade:
    """Single application entry point for R1/R2 definition and PIT workflows."""

    def __init__(self, gateway: ResearchDataFoundationGateway) -> None:
        self._gateway = gateway

    def register_operating_metric(
        self,
        definition: OperatingMetricDefinition,
    ) -> OperatingMetricDefinition:
        """Register a caller-supplied, versioned operating metric taxonomy row."""

        return self._gateway.save_operating_metric_definition(definition)

    def register_investor_flow(
        self,
        definition: InvestorFlowDefinition,
    ) -> InvestorFlowDefinition:
        """Register a caller-supplied actor/measure/source definition."""

        return self._gateway.save_investor_flow_definition(definition)

    def register_asset_group(
        self,
        definition: AssetGroupRevision,
    ) -> AssetGroupRevision:
        """Register a caller-supplied custom asset-group revision."""

        return self._gateway.save_asset_group_revision(definition)

    def record_operating_observation(
        self,
        observation: OperatingObservation,
    ) -> PITFactVersion:
        """Record a fact, assumption or inference without erasing its origin."""

        return self._gateway.append_operating_observation(observation)

    def record_investor_flow(
        self,
        observation: InvestorFlowObservation,
    ) -> PITFactVersion:
        """Record a flow observation with immutable measure/proxy semantics."""

        return self._gateway.append_investor_flow_observation(observation)

    def record_asset_group_membership(
        self,
        membership: PITAssetGroupMembership,
    ) -> PITFactVersion:
        """Record a point-in-time membership for one governed group revision."""

        return self._gateway.append_asset_group_membership(membership)

    def list_operating_observations(
        self,
        *,
        metric_code: str,
        definition_version: int,
        value_kind: ObservationValueKind,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
        subject_code: str | None = None,
    ) -> list[PITFactVersion]:
        """Query one explicit operating origin so facts and estimates never mix."""

        self._validate_query_time(as_of_time)
        filters: dict[str, Any] = {
            "metric_code": metric_code,
            "definition_version": definition_version,
            "value_kind": value_kind.value,
        }
        if subject_code is not None:
            filters["subject_code"] = subject_code
        return self._gateway.query_versions(
            dataset=OPERATING_OBSERVATION_DATASET,
            as_of_time=as_of_time,
            knowledge_scope=knowledge_scope,
            filters=filters,
        )

    def get_operating_fact_versions(
        self,
        version_ids: tuple[int, ...],
        *,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope = KnowledgeScope.PUBLIC,
    ) -> list[PITFactVersion]:
        """Resolve exact latest operating versions under an explicit PIT clock."""

        self._validate_query_time(as_of_time)
        if not version_ids or len(set(version_ids)) != len(version_ids):
            raise ValueError("version_ids must be non-empty and unique")
        if any(isinstance(version_id, bool) or version_id <= 0 for version_id in version_ids):
            raise ValueError("version_ids must be positive integers")
        return self._gateway.get_operating_fact_versions(
            version_ids,
            as_of_time=as_of_time,
            knowledge_scope=knowledge_scope,
        )

    def list_investor_flow_observations(
        self,
        *,
        flow_code: str,
        definition_version: int,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
        scope_code: str | None = None,
    ) -> list[PITFactVersion]:
        """Query one governed flow series without aggregating measure kinds."""

        self._validate_query_time(as_of_time)
        filters: dict[str, Any] = {
            "flow_code": flow_code,
            "definition_version": definition_version,
        }
        if scope_code is not None:
            filters["scope_code"] = scope_code
        return self._gateway.query_versions(
            dataset=INVESTOR_FLOW_OBSERVATION_DATASET,
            as_of_time=as_of_time,
            knowledge_scope=knowledge_scope,
            filters=filters,
        )

    def list_asset_group_memberships(
        self,
        *,
        group_code: str,
        group_revision: int,
        as_of_time: datetime,
        knowledge_scope: KnowledgeScope,
    ) -> list[PITFactVersion]:
        """Query members as known at an explicit point in time."""

        self._validate_query_time(as_of_time)
        return self._gateway.query_versions(
            dataset=ASSET_GROUP_MEMBERSHIP_DATASET,
            as_of_time=as_of_time,
            knowledge_scope=knowledge_scope,
            filters={
                "group_code": group_code,
                "group_revision": group_revision,
            },
        )

    @staticmethod
    def _validate_query_time(as_of_time: datetime) -> None:
        """Reject a query that would collapse PIT time semantics."""

        if as_of_time.tzinfo is None or as_of_time.utcoffset() is None:
            raise ValueError("as_of_time must be timezone-aware")


_configured_facade: ResearchDataFoundationFacade | None = None


def configure_research_data_foundation_facade(
    facade: ResearchDataFoundationFacade,
) -> None:
    """Register the Data Center-owned runtime facade at composition time."""

    global _configured_facade
    _configured_facade = facade


def get_research_data_foundation_facade() -> ResearchDataFoundationFacade:
    """Return the configured Application facade without exposing Infrastructure."""

    if _configured_facade is None:
        raise RuntimeError("research data foundation facade is not configured")
    return _configured_facade


__all__ = [
    "ResearchDataFoundationFacade",
    "ResearchDataFoundationGateway",
    "configure_research_data_foundation_facade",
    "get_research_data_foundation_facade",
]
