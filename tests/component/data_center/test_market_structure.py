"""Django repository coverage for the complete R2 market-structure slice."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import QuerySet

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
    MarketStructurePeriodCalendar,
    MarketStructurePeriodCalendarRef,
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
    MarketStructurePeriodCalendarModel,
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
        available_at=GROUP_EFFECTIVE,
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
        available_at=GROUP_EFFECTIVE,
        proxy_target_actor_code="TARGET_ACTOR" if is_proxy else "",
        proxy_methodology_ref="governance://proxy/v1" if is_proxy else "",
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


def _force_first_calendar_lookup_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expose the insert-time unique race after a winner already committed."""

    manager = MarketStructurePeriodCalendarModel._default_manager
    original_select_for_update = manager.select_for_update
    first_call = True

    def select_for_update(
        *args: object,
        **kwargs: object,
    ) -> QuerySet[MarketStructurePeriodCalendarModel]:
        nonlocal first_call
        queryset = original_select_for_update(*args, **kwargs)
        if first_call:
            first_call = False
            return queryset.none()
        return queryset

    def skip_full_clean(
        _model: MarketStructurePeriodCalendarModel,
        *args: object,
        **kwargs: object,
    ) -> None:
        del args, kwargs

    monkeypatch.setattr(manager, "select_for_update", select_for_update)
    monkeypatch.setattr(MarketStructurePeriodCalendarModel, "full_clean", skip_full_clean)


def _request(*, evidence_key: str = "TEST_MARKET_STRUCTURE") -> MarketStructureResearchRequest:
    return MarketStructureResearchRequest(
        evidence_key=evidence_key,
        evidence_version=1,
        as_of_time=AS_OF,
        knowledge_scope=KnowledgeScope.PUBLIC,
        group_code="TEST_GROUP",
        group_revision=1,
        period_calendar=MarketStructurePeriodCalendarRef(
            calendar_code="TEST_MONTHLY_CALENDAR",
            calendar_version=1,
        ),
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
            minimum_membership_coverage_ratio=Decimal("1"),
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
    governance.register_period_calendar(_calendar())
    for actor_code, is_proxy in (("A", False), ("B", True)):
        governance.register_actor(_actor(actor_code))
        foundation.register_investor_flow(_flow_definition(actor_code, is_proxy=is_proxy))
        governance.register_series(_series(actor_code, is_proxy=is_proxy))


def _record_observations(
    foundation: ResearchDataFoundationFacade,
    *,
    excluded_period: datetime | None = None,
) -> None:
    values = {
        "A": ("10", "15", "25"),
        "B": ("20", "18", "19"),
    }
    for actor_code, is_proxy in (("A", False), ("B", True)):
        for period_index, effective_at in enumerate(PERIODS):
            if effective_at == excluded_period:
                continue
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

    assert governance.register_period_calendar(_calendar()) == _calendar()
    with pytest.raises(ValueError, match="conflicting immutable content"):
        governance.register_period_calendar(replace(_calendar(), source="other_governance"))

    evidence = RunMarketStructureResearch(market_repository).execute(_request())

    assert evidence.status is MarketStructureResearchStatus.AVAILABLE
    assert evidence.research_only is True
    assert evidence.must_not_use_for_decision is True
    assert evidence.must_not_execute is True
    assert InvestorActorDefinitionModel._default_manager.count() == 2
    assert MarketStructurePeriodCalendarModel._default_manager.count() == 1
    assert MarketStructureSeriesDefinitionModel._default_manager.count() == 2
    assert MarketStructureResearchEvidenceModel._default_manager.count() == 1
    payload = cast(dict[str, object], json.loads(evidence.payload_json))
    output = cast(dict[str, object], payload["output"])
    metrics = cast(list[dict[str, object]], output["actor_metrics"])
    assert [item["total"] for item in metrics] == ["25", "19"]
    assert output["contains_proxy"] is True
    assert output["deterministic_conclusion"] is None
    coverage = cast(list[dict[str, object]], output["coverage"])
    assert len(coverage) == 6
    assert all(item["expected_count"] == item["observed_count"] == 1 for item in coverage)
    input_payload = cast(dict[str, object], payload["input"])
    assert cast(dict[str, object], input_payload["period_calendar"])["calendar_hash"] == (
        _calendar().calendar_hash
    )

    assert (
        market_repository.get_period_calendar(
            _request().period_calendar,
            as_of_time=datetime(2025, 3, 31, tzinfo=UTC),
        )
        is None
    )
    assert (
        market_repository.get_actor_definition(
            taxonomy_code="TEST_TAXONOMY",
            taxonomy_version=1,
            actor_code="A",
            as_of_time=datetime(2024, 12, 31, tzinfo=UTC),
        )
        is None
    )

    model = MarketStructureResearchEvidenceModel._default_manager.get()
    model.status = MarketStructureResearchStatus.BLOCKED.value
    with pytest.raises(ValidationError, match="immutable"):
        model.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        model.delete()
    with pytest.raises(ValidationError, match="cannot be updated"):
        MarketStructureResearchEvidenceModel.objects.filter(pk=model.pk).update(
            status=MarketStructureResearchStatus.BLOCKED.value
        )
    with pytest.raises(ValidationError, match="bulk updated"):
        MarketStructureResearchEvidenceModel.objects.filter(pk=model.pk).bulk_update(
            [model], ["status"]
        )
    with pytest.raises(ValidationError, match="cannot be deleted"):
        MarketStructureResearchEvidenceModel.objects.filter(pk=model.pk).delete()

    calendar_model = MarketStructurePeriodCalendarModel._default_manager.get()
    with pytest.raises(ValidationError, match="cannot be updated"):
        MarketStructurePeriodCalendarModel._base_manager.filter(pk=calendar_model.pk).update(
            frequency="weekly"
        )
    calendar_model.frequency = "weekly"
    with pytest.raises(ValidationError, match="immutable"):
        calendar_model.save()
    with pytest.raises(ValidationError, match="bulk updated"):
        MarketStructurePeriodCalendarModel._base_manager.bulk_update(
            [calendar_model], ["frequency"]
        )
    with pytest.raises(ValidationError, match="cannot be deleted"):
        MarketStructurePeriodCalendarModel._base_manager.filter(pk=calendar_model.pk).delete()
    with pytest.raises(ValidationError, match="cannot be updated"):
        MarketStructurePeriodCalendarModel.objects.filter(pk=calendar_model.pk).update(
            frequency="weekly"
        )


@pytest.mark.django_db
def test_calendar_concurrent_same_content_unique_winner_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MarketStructureResearchRepository()
    calendar = _calendar()
    assert repository.save_period_calendar(calendar) == calendar
    _force_first_calendar_lookup_miss(monkeypatch)

    assert repository.save_period_calendar(calendar) == calendar
    assert MarketStructurePeriodCalendarModel._default_manager.count() == 1


@pytest.mark.django_db
def test_calendar_concurrent_different_content_unique_winner_is_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MarketStructureResearchRepository()
    assert repository.save_period_calendar(_calendar()) == _calendar()
    _force_first_calendar_lookup_miss(monkeypatch)

    with pytest.raises(ValueError, match="conflicting immutable content"):
        repository.save_period_calendar(replace(_calendar(), source="other_governance"))
    assert MarketStructurePeriodCalendarModel._default_manager.count() == 1


@pytest.mark.django_db
def test_calendar_raw_hash_tamper_is_detected_on_read() -> None:
    repository = MarketStructureResearchRepository()
    repository.save_period_calendar(_calendar())
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE data_center_market_structure_period_calendar "
            "SET calendar_hash = %s WHERE calendar_code = %s",
            ["0" * 64, _calendar().calendar_code],
        )

    with pytest.raises(ValidationError, match="calendar hash mismatch"):
        repository.get_period_calendar(
            _request().period_calendar,
            as_of_time=AS_OF,
        )


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
    assert all(f"period_all_series_missing:{period.isoformat()}" in blockers for period in PERIODS)
    coverage = cast(list[dict[str, object]], output["coverage"])
    assert len(coverage) == len(_request().series) * len(PERIODS)
    assert all(item["expected_count"] == 1 for item in coverage)
    assert all(item["observed_count"] == 0 for item in coverage)
    assert output["actor_metrics"] == []
    assert output["deterministic_conclusion"] is None
    assert MarketStructureResearchEvidenceModel._default_manager.filter(
        evidence_key="TEST_NO_DATA"
    ).exists()


@pytest.mark.django_db
def test_repository_calendar_makes_whole_period_all_missing_visible() -> None:
    foundation = ResearchDataFoundationFacade(
        ResearchDataFoundationRepository(clock=lambda: INGESTED_AT)
    )
    market_repository = MarketStructureResearchRepository()
    governance = MarketStructureGovernanceFacade(market_repository)
    _prepare_governance_and_membership(foundation, governance)
    _record_observations(foundation, excluded_period=PERIODS[1])

    evidence = RunMarketStructureResearch(market_repository).execute(
        _request(evidence_key="TEST_WHOLE_PERIOD_MISSING")
    )

    assert evidence.status is MarketStructureResearchStatus.BLOCKED
    output = cast(dict[str, object], json.loads(evidence.payload_json)["output"])
    blockers = cast(list[str], output["blocked_reasons"])
    assert f"period_all_series_missing:{PERIODS[1].isoformat()}" in blockers
    coverage = cast(list[dict[str, object]], output["coverage"])
    missing_period = [item for item in coverage if item["effective_at"] == PERIODS[1].isoformat()]
    assert len(missing_period) == len(_request().series)
    assert all(item["observed_count"] == 0 for item in missing_period)
