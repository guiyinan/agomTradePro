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
