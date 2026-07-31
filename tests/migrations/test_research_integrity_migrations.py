"""Cross-database migration coverage for research-integrity ownership closure."""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

TARGET_MIGRATIONS = {
    ("data_center", "0039_pit_fact_versions_and_manifests"),
    ("decision_rhythm", "0015_transfer_transition_plan_owner"),
    ("decision_rhythm", "0016_decision_input_snapshot"),
    ("signal", "0009_forecast_ledger"),
    ("prompt", "0002_prompt_evaluation_gate"),
    ("events", "0005_stored_event_aggregate_evidence"),
    ("portfolio", "0001_transfer_transition_plan_state"),
    ("portfolio", "0002_transition_plan_evidence"),
    ("portfolio", "0003_transfer_order_intent_state"),
    ("portfolio", "0004_portfolio_planning_policy"),
    ("research", "0001_initial"),
}

EXPECTED_TABLES = {
    "data_center_pit_dataset_manifest",
    "data_center_pit_fact_version",
    "decision_input_snapshot",
    "signal_forecast_ledger_entry",
    "signal_forecast_evaluation",
    "signal_forecast_outcome",
    "prompt_eval_dataset",
    "prompt_version",
    "portfolio_planning_policy",
    "research_experiment",
    "research_experiment_trial",
    "research_metric_observation",
}


def _constraint_names(table: str) -> set[str]:
    with connection.cursor() as cursor:
        return set(connection.introspection.get_constraints(cursor, table))


def _has_foreign_key(table: str, expected_target: str) -> bool:
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)
    return any(
        details.get("foreign_key") and details["foreign_key"][0] == expected_target
        for details in constraints.values()
    )


@pytest.mark.django_db
def test_research_integrity_migrations_are_applied_on_empty_database_path() -> None:
    """The test database must include every migration in the release-blocking set."""

    applied = set(MigrationRecorder(connection).applied_migrations())
    assert TARGET_MIGRATIONS <= applied
    assert EXPECTED_TABLES <= set(connection.introspection.table_names())


@pytest.mark.django_db
def test_research_integrity_unique_constraints_and_indexes_exist() -> None:
    """Idempotency identities and critical query indexes must exist physically."""

    expected_constraints: dict[str, Iterable[str]] = {
        "data_center_pit_fact_version": {
            "dc_pit_fact_version_identity_uniq",
            "data_center_dataset_2d0100_idx",
            "data_center_dataset_5bf9ab_idx",
            "data_center_dataset_10cc27_idx",
        },
        "decision_input_snapshot": {"decision_in_as_of_t_0f30f6_idx"},
        "prompt_eval_dataset": {"prompt_eval_dataset_version_uniq"},
        "prompt_version": {"prompt_template_version_uniq"},
        "portfolio_planning_policy": {
            "portfolio_one_active_planning_policy",
            "portfolio_policy_positive_lot",
        },
        "research_metric_observation": {"research_trial_metric_uniq"},
    }
    for table, expected in expected_constraints.items():
        assert set(expected) <= _constraint_names(table)

    assert _has_foreign_key("research_experiment_trial", "research_multiple_test_family")
    assert _has_foreign_key("signal_forecast_evaluation", "signal_forecast_ledger_entry")


@pytest.mark.django_db(transaction=True)
def test_transition_plan_owner_transfer_preserves_existing_rows() -> None:
    """State-only owner transfer keeps historical transition-plan rows intact."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    before_targets = [
        ("decision_rhythm", "0014_execution_link_transaction_source"),
        ("portfolio", None),
    ]
    after_targets = [
        ("portfolio", "0002_transition_plan_evidence"),
        ("decision_rhythm", "0015_transfer_transition_plan_owner"),
    ]
    try:
        executor.migrate(before_targets)
        old_apps = executor.loader.project_state(
            [("decision_rhythm", "0014_execution_link_transaction_source")]
        ).apps
        OldPlan = old_apps.get_model("decision_rhythm", "PortfolioTransitionPlanModel")
        OldPlan.objects.create(
            plan_id="migration-owner-transfer-1",
            account_id="account-1",
            source_recommendation_ids=["recommendation-1"],
            current_positions_snapshot=[],
            target_positions_snapshot=[],
            orders=[],
            risk_contract={},
            summary={},
            as_of=timezone.now(),
        )

        # MigrationExecutor does not run the post-migrate content-type cleanup
        # when moving this model between apps. Remove stale rows before the
        # state-only owner transfer creates the destination model.
        ContentType.objects.filter(
            app_label__in={"decision_rhythm", "portfolio"},
            model="portfoliotransitionplanmodel",
        ).delete()
        executor = MigrationExecutor(connection)
        executor.migrate(after_targets)
        new_apps = executor.loader.project_state(after_targets).apps
        NewPlan = new_apps.get_model("portfolio", "PortfolioTransitionPlanModel")
        migrated = NewPlan.objects.get(plan_id="migration-owner-transfer-1")

        assert migrated.account_id == "account-1"
        assert migrated.plan_version == 1
        assert migrated.decision_snapshot_id == ""
        assert migrated.portfolio_snapshot_id == ""
        assert migrated.target_portfolio_id == ""
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
