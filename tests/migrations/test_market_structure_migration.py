"""Migration evidence for the unseeded, research-only R2 persistence slice."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_market_structure_migration_is_unseeded_and_enforces_research_scope() -> None:
    """Create only governance/evidence structure and reject unsafe flags."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(
            [
                (
                    "data_center",
                    "0058_assetgrouprevisionmodel_investorflowdefinitionmodel_and_more",
                )
            ]
        )
        executor = MigrationExecutor(connection)
        executor.migrate([("data_center", "0059_market_structure_research_slice")])
        apps = executor.loader.project_state(
            [("data_center", "0059_market_structure_research_slice")]
        ).apps
        Actor = apps.get_model("data_center", "InvestorActorDefinitionModel")
        Series = apps.get_model("data_center", "MarketStructureSeriesDefinitionModel")
        Evidence = apps.get_model("data_center", "MarketStructureResearchEvidenceModel")
        Flow = apps.get_model("data_center", "InvestorFlowDefinitionModel")

        assert Actor.objects.count() == 0
        assert Series.objects.count() == 0
        assert Evidence.objects.count() == 0
        measure_choices = {value for value, _label in Flow._meta.get_field("measure_kind").choices}
        assert measure_choices == {
            "fund_flow",
            "capital_balance",
            "holding_change",
            "transaction_net_flow",
        }

        effective_at = datetime(2025, 1, 1, tzinfo=UTC)
        Actor.objects.create(
            taxonomy_code="CALLER_TAXONOMY",
            taxonomy_version=1,
            actor_code="CALLER_ACTOR",
            actor_name="Caller actor",
            source="caller_source",
            revision_policy_ref="governance://actor-revision/v1",
            effective_at=effective_at,
            definition_hash="a" * 64,
        )
        Series.objects.create(
            series_code="CALLER_SERIES",
            series_version=1,
            flow_code="CALLER_FLOW",
            flow_definition_version=1,
            taxonomy_code="CALLER_TAXONOMY",
            taxonomy_version=1,
            actor_code="CALLER_ACTOR",
            measure_concept="flow",
            measure_kind="fund_flow",
            canonical_unit="CNY",
            frequency="monthly",
            source="caller_source",
            revision_policy_ref="governance://flow-revision/v1",
            effective_at=effective_at,
            is_proxy=True,
            proxy_target_actor_code="TARGET_ACTOR",
            proxy_methodology_ref="governance://proxy/v1",
            definition_hash="b" * 64,
        )
        Evidence.objects.create(
            evidence_key="CALLER_EVIDENCE",
            evidence_version=1,
            as_of_time=effective_at,
            group_code="CALLER_GROUP",
            group_revision=1,
            method_version="caller-method-v1",
            policy_code="CALLER_POLICY",
            policy_version=1,
            status="blocked",
            input_hash="c" * 64,
            output_hash="d" * 64,
            evidence_hash="e" * 64,
            payload={"input": {}, "output": {}},
            source_evidence=[],
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            Evidence.objects.filter(evidence_key="CALLER_EVIDENCE").update(research_only=False)
        with pytest.raises(IntegrityError), transaction.atomic():
            Series.objects.create(
                series_code="UNLABELLED_PROXY",
                series_version=1,
                flow_code="CALLER_FLOW",
                flow_definition_version=1,
                taxonomy_code="CALLER_TAXONOMY",
                taxonomy_version=1,
                actor_code="CALLER_ACTOR",
                measure_concept="flow",
                measure_kind="fund_flow",
                canonical_unit="CNY",
                frequency="monthly",
                source="caller_source",
                revision_policy_ref="governance://flow-revision/v1",
                effective_at=effective_at,
                is_proxy=True,
                definition_hash="f" * 64,
            )

        executor = MigrationExecutor(connection)
        executor.migrate([("data_center", "0060_market_structure_definition_knowledge_time")])
        temporal_apps = executor.loader.project_state(
            [("data_center", "0060_market_structure_definition_knowledge_time")]
        ).apps
        TemporalActor = temporal_apps.get_model("data_center", "InvestorActorDefinitionModel")
        TemporalSeries = temporal_apps.get_model(
            "data_center", "MarketStructureSeriesDefinitionModel"
        )
        migrated_actor = TemporalActor.objects.get(actor_code="CALLER_ACTOR")
        migrated_series = TemporalSeries.objects.get(series_code="CALLER_SERIES")
        assert migrated_actor.available_at == effective_at
        assert migrated_series.available_at == effective_at
        assert migrated_actor.definition_hash != "a" * 64
        assert migrated_series.definition_hash != "b" * 64
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_period_calendar_migration_is_unseeded_and_preserves_legacy_evidence() -> None:
    """Add only calendar governance and leave prior evidence byte-for-byte intact."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("data_center", "0060_market_structure_definition_knowledge_time")])
        before_apps = executor.loader.project_state(
            [("data_center", "0060_market_structure_definition_knowledge_time")]
        ).apps
        LegacyEvidence = before_apps.get_model(
            "data_center", "MarketStructureResearchEvidenceModel"
        )
        as_of_time = datetime(2025, 4, 1, tzinfo=UTC)
        legacy_payload = {
            "input": {"request": {"method_version": "legacy-v1"}},
            "output": {"status": "blocked"},
        }
        LegacyEvidence.objects.create(
            evidence_key="LEGACY_EVIDENCE",
            evidence_version=1,
            as_of_time=as_of_time,
            group_code="LEGACY_GROUP",
            group_revision=1,
            method_version="legacy-v1",
            policy_code="LEGACY_POLICY",
            policy_version=1,
            status="blocked",
            input_hash="a" * 64,
            output_hash="b" * 64,
            evidence_hash="c" * 64,
            payload=legacy_payload,
            source_evidence=[],
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("data_center", "0061_market_structure_period_calendar")])
        apps = executor.loader.project_state(
            [("data_center", "0061_market_structure_period_calendar")]
        ).apps
        Calendar = apps.get_model("data_center", "MarketStructurePeriodCalendarModel")
        Evidence = apps.get_model("data_center", "MarketStructureResearchEvidenceModel")

        assert Calendar.objects.count() == 0
        assert Calendar._meta.base_manager_name == "objects"
        assert Calendar._meta.default_manager_name == "objects"
        legacy = Evidence.objects.get(evidence_key="LEGACY_EVIDENCE")
        assert legacy.input_hash == "a" * 64
        assert legacy.output_hash == "b" * 64
        assert legacy.evidence_hash == "c" * 64
        assert legacy.payload == legacy_payload

        Calendar.objects.create(
            calendar_code="CALLER_MONTHLY_CALENDAR",
            calendar_version=1,
            frequency="monthly",
            source="caller_governance",
            revision_policy_ref="governance://calendar/v1",
            available_at=as_of_time,
            periods=[
                "2025-01-01T00:00:00+00:00",
                "2025-02-01T00:00:00+00:00",
                "2025-03-01T00:00:00+00:00",
            ],
            calendar_hash="d" * 64,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Calendar.objects.create(
                calendar_code="CALLER_MONTHLY_CALENDAR",
                calendar_version=1,
                frequency="monthly",
                source="caller_governance",
                revision_policy_ref="governance://calendar/v2",
                available_at=as_of_time,
                periods=["2025-03-01T00:00:00+00:00"],
                calendar_hash="e" * 64,
            )
        with pytest.raises(IntegrityError), transaction.atomic():
            Calendar.objects.create(
                calendar_code="INVALID_EXPIRY",
                calendar_version=1,
                frequency="monthly",
                source="caller_governance",
                revision_policy_ref="governance://calendar/v1",
                available_at=as_of_time,
                expires_at=as_of_time,
                periods=["2025-03-01T00:00:00+00:00"],
                calendar_hash="f" * 64,
            )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
