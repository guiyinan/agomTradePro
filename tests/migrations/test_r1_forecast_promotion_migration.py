"""Migration evidence for the schema-only Research R1 promotion ledgers."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor


def _rows(model: Any, order_by: str) -> list[dict[str, object]]:
    return list(model.objects.order_by(order_by).values())


@pytest.mark.django_db(transaction=True)
def test_0003_preserves_all_0001_and_0002_rows_and_seeds_nothing() -> None:
    """The five R1 tables add no data and preserve every prior Research byte."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    before = [("research", "0002_scenario_review_reminder_ledger")]
    after = [("research", "0003_r1_forecast_promotion_ledgers")]
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        Experiment = old_apps.get_model("research", "ResearchExperiment")
        Family = old_apps.get_model("research", "MultipleTestFamily")
        Trial = old_apps.get_model("research", "ExperimentTrial")
        Split = old_apps.get_model("research", "DatasetSplitSpec")
        Metric = old_apps.get_model("research", "MetricObservation")
        Decision = old_apps.get_model("research", "PromotionDecision")
        Reminder = old_apps.get_model("research", "ScenarioReviewReminderModel")
        ReminderEvent = old_apps.get_model(
            "research",
            "ScenarioReviewReminderEventModel",
        )

        experiment = Experiment.objects.create(
            experiment_id="migration-r1-experiment",
            question="Does R1 preserve every historical row?",
            hypothesis="The R1 migration is schema-only.",
            owner_id=None,
            status="completed",
        )
        family = Family.objects.create(
            family_id="migration-r1-family",
            experiment=experiment,
            planned_trial_count=1,
            fdr_threshold=0.05,
        )
        trial = Trial.objects.create(
            trial_id="migration-r1-trial",
            experiment=experiment,
            family=family,
            status="completed",
            pit_manifest_id="pit-migration-r1",
            backtest_id=81,
            backtest_trust_status="pit_verified",
            code_commit="a" * 40,
            dependency_lock_hash="b" * 64,
            engine_version="engine-r1",
            parameters={"alpha": "1.00", "nested": [1, 2]},
            parameter_hash="c" * 64,
            random_seed=81,
            benchmark_spec={"code": "000300.SH"},
            cost_spec={"bps": "5.0"},
            slippage_spec={"bps": "2.0"},
            universe_spec={"name": "migration-r1"},
        )
        Split.objects.create(
            trial=trial,
            training_window={"start": "2020-01-01", "end": "2020-12-31"},
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
            metadata={"source": "migration-r1", "raw": ["a", "b"]},
        )
        Decision.objects.create(
            decision_id="migration-r1-decision",
            trial=trial,
            decision="rejected",
            evidence={"reason": "byte-preservation", "codes": ["r1"]},
        )

        created_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
        reminder = Reminder.objects.create(
            reminder_id="migration-r1-reminder",
            reminder_version="reminder.v1",
            intent_id="migration-r1-intent",
            intent_version="intent.v1",
            intent_content_hash="1" * 64,
            forecast_entry_id="migration-r1-forecast",
            forecast_group_id="migration-r1-group",
            forecast_observation_hash="2" * 64,
            probability_policy_version="probability.v1",
            probability_policy_hash="3" * 64,
            scenario_revision_id=UUID("11111111-1111-1111-1111-111111111111"),
            scenario_set_revision_id=UUID("22222222-2222-2222-2222-222222222222"),
            invalidation_evidence_hash="4" * 64,
            intent_reason_code="scheduled_review",
            schedule_version="schedule.v1",
            schedule_policy_hash="5" * 64,
            expiry_delay=timedelta(days=3),
            escalation_delay=timedelta(days=1),
            maximum_escalation_level=3,
            path_horizon_periods=4,
            owner_evidence_hash="6" * 64,
            escalation_policy_version="escalation.v1",
            escalation_policy_hash="7" * 64,
            path_evidence_hash="8" * 64,
            period_bindings=[{"period": "2026Q3", "hash": "9" * 64}],
            created_at=created_at,
            due_at=created_at + timedelta(days=1),
            expires_at=created_at + timedelta(days=4),
            delivery_scope="internal_review",
            must_not_execute=True,
            external_dispatch_requested=False,
            auto_approval_requested=False,
            research_only=True,
            must_not_use_for_decision=True,
            content_hash="a" * 64,
        )
        ReminderEvent.objects.create(
            event_id="migration-r1-reminder-event",
            event_version="event.v1",
            reminder=reminder,
            event_type="scheduled",
            sequence=1,
            escalation_level=0,
            occurred_at=created_at,
            recorded_at=created_at + timedelta(minutes=1),
            actor_evidence_hash="b" * 64,
            reason_code="scheduled_review",
            idempotency_key="migration-r1-reminder:scheduled",
            previous_event_hash=None,
            delivery_scope="internal_review",
            must_not_execute=True,
            external_dispatch_requested=False,
            auto_approval_requested=False,
            research_only=True,
            must_not_use_for_decision=True,
            content_hash="c" * 64,
            record_hash="d" * 64,
        )
        snapshots = {
            "ResearchExperiment": ("experiment_id", _rows(Experiment, "experiment_id")),
            "MultipleTestFamily": ("family_id", _rows(Family, "family_id")),
            "ExperimentTrial": ("trial_id", _rows(Trial, "trial_id")),
            "DatasetSplitSpec": ("trial_id", _rows(Split, "trial_id")),
            "MetricObservation": ("id", _rows(Metric, "id")),
            "PromotionDecision": ("decision_id", _rows(Decision, "decision_id")),
            "ScenarioReviewReminderModel": (
                "reminder_id",
                _rows(Reminder, "reminder_id"),
            ),
            "ScenarioReviewReminderEventModel": (
                "event_id",
                _rows(ReminderEvent, "event_id"),
            ),
        }

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        new_apps = executor.loader.project_state(after).apps
        for model_name, (order_by, expected) in snapshots.items():
            model = new_apps.get_model("research", model_name)
            assert _rows(model, order_by) == expected
        for model_name in (
            "R1ForecastPromotionPolicyModel",
            "R1PromotionDecisionReceiptModel",
            "R1ForecastPromotionDecisionBundleModel",
            "R1PromotionLifecycleReceiptModel",
            "R1PromotionLifecycleEventBundleModel",
        ):
            assert new_apps.get_model("research", model_name).objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


def test_0003_declares_only_schema_creation_and_guards() -> None:
    """The R1 migration contains only its five tables and schema guards."""

    module = importlib.import_module("apps.research.migrations.0003_r1_forecast_promotion_ledgers")
    operations = module.Migration.operations
    allowed_types = (
        migrations.CreateModel,
        migrations.AddConstraint,
        migrations.AddIndex,
    )
    assert len(operations) == 25
    assert all(isinstance(operation, allowed_types) for operation in operations)
    assert sum(isinstance(operation, migrations.CreateModel) for operation in operations) == 5
    assert sum(isinstance(operation, migrations.AddConstraint) for operation in operations) == 19
    assert sum(isinstance(operation, migrations.AddIndex) for operation in operations) == 1
    forbidden_types = (
        migrations.RunPython,
        migrations.RunSQL,
        migrations.AlterField,
        migrations.RemoveField,
        migrations.DeleteModel,
        migrations.RenameField,
        migrations.RenameModel,
    )
    assert not any(isinstance(operation, forbidden_types) for operation in operations)


@pytest.mark.django_db
def test_0003_physical_tables_and_identity_chain_constraints_exist() -> None:
    """The live schema exposes all five tables and critical immutable identities."""

    expected = {
        "research_r1_promotion_policy": {
            "res_r1_pol_identity_uq",
            "res_r1_pol_authority_ck",
            "res_r1_pol_time_ck",
            "res_r1_pol_research_ck",
        },
        "research_r1_promotion_decision_receipt": {
            "res_r1_dr_identity_uq",
            "res_r1_dr_decision_uq",
            "res_r1_dr_authority_ck",
            "res_r1_dr_time_ck",
        },
        "research_r1_promotion_decision_bundle": {
            "res_r1_db_identity_uq",
            "res_r1_db_authority_ck",
            "res_r1_db_time_ck",
            "res_r1_db_research_ck",
        },
        "research_r1_promotion_lifecycle_receipt": {
            "res_r1_lr_auth_identity_uq",
            "res_r1_lr_event_identity_uq",
            "res_r1_lr_authority_ck",
            "res_r1_lr_time_ck",
            "res_r1_lr_target_ck",
        },
        "research_r1_promotion_lifecycle_bundle": {
            "res_r1_lb_identity_uq",
            "res_r1_lb_stream_seq_uq",
            "res_r1_lb_previous_uq",
            "res_r1_lb_time_ck",
            "res_r1_lb_root_chain_ck",
            "res_r1_lb_research_ck",
        },
    }
    tables = set(connection.introspection.table_names())
    assert set(expected) <= tables
    with connection.cursor() as cursor:
        for table, constraint_names in expected.items():
            constraints = connection.introspection.get_constraints(cursor, table)
            assert constraint_names <= set(constraints)
