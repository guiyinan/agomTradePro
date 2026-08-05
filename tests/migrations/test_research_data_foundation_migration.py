"""Migration evidence for the unseeded R1/R2 governance-definition catalog."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_research_data_foundation_migration_creates_unseeded_governance_tables() -> None:
    """The migration creates versioned definitions without business defaults."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("data_center", "0057_publicationrollbackmodel")])
        executor = MigrationExecutor(connection)
        executor.migrate(
            [
                (
                    "data_center",
                    "0058_assetgrouprevisionmodel_investorflowdefinitionmodel_and_more",
                )
            ]
        )
        apps = executor.loader.project_state(
            [
                (
                    "data_center",
                    "0058_assetgrouprevisionmodel_investorflowdefinitionmodel_and_more",
                )
            ]
        ).apps
        Metric = apps.get_model("data_center", "OperatingMetricDefinitionModel")
        Flow = apps.get_model("data_center", "InvestorFlowDefinitionModel")
        Group = apps.get_model("data_center", "AssetGroupRevisionModel")

        assert Metric.objects.count() == 0
        assert Flow.objects.count() == 0
        assert Group.objects.count() == 0

        effective_at = datetime(2025, 1, 1, tzinfo=UTC)
        Metric.objects.create(
            metric_code="CALLER_SUPPLIED_METRIC",
            definition_version=1,
            name="Caller supplied metric",
            canonical_unit="unit",
            frequency="quarterly",
            source="caller_governed_source",
            effective_at=effective_at,
        )
        Flow.objects.create(
            flow_code="CALLER_SUPPLIED_FLOW",
            definition_version=1,
            actor_code="CALLER_SUPPLIED_ACTOR",
            actor_name="Caller supplied actor",
            measure_kind="transaction_net_flow",
            canonical_unit="CNY",
            frequency="daily",
            source="caller_governed_source",
            effective_at=effective_at,
            is_proxy=True,
            proxy_target_actor_code="TARGET_ACTOR",
            proxy_methodology_ref="governance://caller-flow/v1",
        )
        Group.objects.create(
            group_code="CALLER_SUPPLIED_GROUP",
            revision=1,
            name="Caller supplied group",
            source="caller_governed_source",
            effective_at=effective_at,
        )

        assert Metric.objects.values_list("metric_code", flat=True).get() == (
            "CALLER_SUPPLIED_METRIC"
        )
        assert Flow.objects.values_list("actor_code", flat=True).get() == ("CALLER_SUPPLIED_ACTOR")
        assert Group.objects.values_list("group_code", flat=True).get() == ("CALLER_SUPPLIED_GROUP")

        with pytest.raises(IntegrityError), transaction.atomic():
            Flow.objects.create(
                flow_code="UNLABELLED_PROXY",
                definition_version=1,
                actor_code="CALLER_SUPPLIED_ACTOR",
                actor_name="Caller supplied actor",
                measure_kind="holding_change",
                canonical_unit="shares",
                frequency="daily",
                source="caller_governed_source",
                effective_at=effective_at,
                is_proxy=True,
            )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
