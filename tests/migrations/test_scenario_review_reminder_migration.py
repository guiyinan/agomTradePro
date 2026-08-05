"""Migration evidence for the schema-only R7 reminder ledger."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def _rows(model: Any, order_by: str) -> list[dict[str, object]]:
    return list(model.objects.order_by(order_by).values())


@pytest.mark.django_db(transaction=True)
def test_0002_is_schema_only_and_preserves_every_0001_evidence_row() -> None:
    """Adding reminders creates no seed and leaves all 0001 bytes untouched."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    before = [("research", "0001_initial")]
    after = [("research", "0002_scenario_review_reminder_ledger")]
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        Experiment = old_apps.get_model("research", "ResearchExperiment")
        Family = old_apps.get_model("research", "MultipleTestFamily")
        Trial = old_apps.get_model("research", "ExperimentTrial")
        Split = old_apps.get_model("research", "DatasetSplitSpec")
        Metric = old_apps.get_model("research", "MetricObservation")
        Decision = old_apps.get_model("research", "PromotionDecision")

        experiment = Experiment.objects.create(
            experiment_id="migration-r7-experiment",
            question="Does the original row survive?",
            hypothesis="Schema-only migration preserves it.",
            owner_id=None,
            status="completed",
        )
        family = Family.objects.create(
            family_id="migration-r7-family",
            experiment=experiment,
            planned_trial_count=1,
            fdr_threshold=0.05,
        )
        trial = Trial.objects.create(
            trial_id="migration-r7-trial",
            experiment=experiment,
            family=family,
            status="completed",
            pit_manifest_id="pit-migration-r7",
            backtest_id=7,
            backtest_trust_status="pit_verified",
            code_commit="a" * 40,
            dependency_lock_hash="b" * 64,
            engine_version="engine-v1",
            parameters={"alpha": "1"},
            parameter_hash="c" * 64,
            random_seed=17,
            benchmark_spec={"code": "000300.SH"},
            cost_spec={"bps": "5"},
            slippage_spec={"bps": "2"},
            universe_spec={"name": "migration"},
        )
        Split.objects.create(
            trial=trial,
            training_window={"start": "2020-01-01"},
            validation_window={"start": "2021-01-01"},
            out_of_sample_window={"start": "2022-01-01"},
            walk_forward_windows=[{"start": "2022-01-01"}],
            embargo_days=5,
        )
        Metric.objects.create(
            trial=trial,
            metric_name="sharpe_ratio",
            value=1.25,
            sample_count=100,
            confidence_interval_low=1.0,
            confidence_interval_high=1.5,
            p_value=0.01,
            q_value=0.02,
            metadata={"source": "migration"},
        )
        Decision.objects.create(
            decision_id="migration-r7-decision",
            trial=trial,
            decision="rejected",
            evidence={"reason": "fixture_only"},
        )
        snapshots = {
            "ResearchExperiment": _rows(Experiment, "experiment_id"),
            "MultipleTestFamily": _rows(Family, "family_id"),
            "ExperimentTrial": _rows(Trial, "trial_id"),
            "DatasetSplitSpec": _rows(Split, "trial_id"),
            "MetricObservation": _rows(Metric, "id"),
            "PromotionDecision": _rows(Decision, "decision_id"),
        }

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        for model_name, expected in snapshots.items():
            model = new_apps.get_model("research", model_name)
            order_by = next(iter(expected[0]))
            assert _rows(model, order_by) == expected
        Reminder = new_apps.get_model("research", "ScenarioReviewReminderModel")
        Event = new_apps.get_model("research", "ScenarioReviewReminderEventModel")
        assert Reminder.objects.count() == 0
        assert Event.objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.django_db
def test_0002_tables_and_idempotency_constraints_exist() -> None:
    """Physical schema exposes the append-only identity constraints."""

    tables = set(connection.introspection.table_names())
    assert "research_scenario_review_reminder" in tables
    assert "research_scenario_review_reminder_event" in tables
    with connection.cursor() as cursor:
        header = connection.introspection.get_constraints(
            cursor,
            "research_scenario_review_reminder",
        )
        events = connection.introspection.get_constraints(
            cursor,
            "research_scenario_review_reminder_event",
        )
    assert {
        "research_srr_internal_only_ck",
        "research_srr_path_horizon_positive_ck",
        "research_srr_expiry_delay_positive_ck",
        "research_srr_escalation_delay_positive_ck",
    } <= set(header)
    assert {
        "research_srr_event_sequence_uniq",
        "research_srr_event_idempotency_uniq",
        "research_srr_event_root_chain_ck",
        "research_srr_event_internal_only_ck",
        "research_srr_event_recorded_after_ck",
    } <= set(events)
