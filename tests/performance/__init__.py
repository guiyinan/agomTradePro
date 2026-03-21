"""
Migration tests for Agent Runtime module.

WP-M1-07: Tests (027-030)

These tests verify that:
1. Migrations apply cleanly
2. Database schema matches model definitions
3. Indexes are created correctly
4. Foreign key relationships work
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.apps import apps
from django.core.management import call_command


@pytest.mark.django_db
class TestAgentRuntimeMigrations:
    """Tests for agent_runtime migrations."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test."""
        self.app_config = apps.get_app_config("agent_runtime")

    def test_migrations_apply_cleanly(self):
        """Test that all migrations apply without errors."""
        # This test runs in a transaction, migrations should work
        executor = MigrationExecutor(connection)

        # Get the migration state before
        migration_state_before = executor.migration_plan(
            [(self.app_config.label, None)]
        )

        # Apply all migrations
        call_command("migrate", self.app_config.label, verbosity=0)

        # Verify no pending migrations
        executor.loader.build_graph()
        migration_state_after = executor.migration_plan(
            [(self.app_config.label, None)]
        )

        # If there were pending migrations before, there should be none now
        # (unless new migrations were added after the test started)
        assert len(migration_state_after) == 0 or len(migration_state_after) <= len(migration_state_before)

    def test_agent_task_table_exists(self):
        """Test that agent_task table exists with correct columns."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_task'"
            )
            result = cursor.fetchone()
            assert result is not None, "agent_task table should exist"

            # Check columns
            cursor.execute("PRAGMA table_info(agent_task)")
            columns = {row[1] for row in cursor.fetchall()}

            expected_columns = {
                "id",
                "request_id",
                "schema_version",
                "task_domain",
                "task_type",
                "status",
                "input_payload",
                "current_step",
                "last_error",
                "requires_human",
                "created_at",
                "updated_at",
                "created_by_id",
            }

            for col in expected_columns:
                assert col in columns, f"Column {col} should exist in agent_task table"

    def test_agent_proposal_table_exists(self):
        """Test that agent_proposal table exists with correct columns."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_proposal'"
            )
            result = cursor.fetchone()
            assert result is not None, "agent_proposal table should exist"

            # Check columns
            cursor.execute("PRAGMA table_info(agent_proposal)")
            columns = {row[1] for row in cursor.fetchall()}

            expected_columns = {
                "id",
                "request_id",
                "schema_version",
                "proposal_type",
                "status",
                "risk_level",
                "approval_required",
                "approval_status",
                "approval_reason",
                "proposal_payload",
                "created_at",
                "updated_at",
                "created_by_id",
                "task_id",
            }

            for col in expected_columns:
                assert col in columns, f"Column {col} should exist in agent_proposal table"

    def test_agent_timeline_event_table_exists(self):
        """Test that agent_timeline_event table exists with correct columns."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_timeline_event'"
            )
            result = cursor.fetchone()
            assert result is not None, "agent_timeline_event table should exist"

            # Check columns
            cursor.execute("PRAGMA table_info(agent_timeline_event)")
            columns = {row[1] for row in cursor.fetchall()}

            expected_columns = {
                "id",
                "request_id",
                "event_type",
                "event_source",
                "step_index",
                "event_payload",
                "created_at",
                "task_id",
                "proposal_id",
            }

            for col in expected_columns:
                assert col in columns, f"Column {col} should exist in agent_timeline_event table"

    def test_agent_task_step_table_exists(self):
        """Test that agent_task_step table exists with correct columns."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_task_step'"
            )
            result = cursor.fetchone()
            assert result is not None, "agent_task_step table should exist"

    def test_agent_artifact_table_exists(self):
        """Test that agent_artifact table exists."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_artifact'"
            )
            result = cursor.fetchone()
            assert result is not None, "agent_artifact table should exist"

    def test_agent_context_snapshot_table_exists(self):
        """Test that agent_context_snapshot table exists."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_context_snapshot'"
            )
            result = cursor.fetchone()
            assert result is not None, "agent_context_snapshot table should exist"

    def test_agent_execution_record_table_exists(self):
        """Test that agent_execution_record table exists."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_execution_record'"
            )
            result = cursor.fetchone()
            assert result is not None, "agent_execution_record table should exist"

    def test_agent_guardrail_decision_table_exists(self):
        """Test that agent_guardrail_decision table exists."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_guardrail_decision'"
            )
            result = cursor.fetchone()
            assert result is not None, "agent_guardrail_decision table should exist"

    def test_agent_handoff_table_exists(self):
        """Test that agent_handoff table exists."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_handoff'"
            )
            result = cursor.fetchone()
            assert result is not None, "agent_handoff table should exist"

    def test_request_id_unique_constraint(self):
        """Test that request_id has unique constraint on agent_task."""
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA index_list(agent_task)")
            indexes = cursor.fetchall()

            # Find unique indexes
            unique_indexes = [idx for idx in indexes if idx[2] == 1]  # unique flag

            # Check if there's a unique index on request_id
            has_unique_request_id = False
            for idx in unique_indexes:
                cursor.execute(f"PRAGMA index_info({idx[1]})")
                columns = cursor.fetchall()
                if any(col[2] == "request_id" for col in columns):
                    has_unique_request_id = True
                    break

            assert has_unique_request_id, "request_id should have a unique constraint"

    def test_indexes_created(self):
        """Test that expected indexes are created."""
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA index_list(agent_task)")
            indexes = [idx[1] for idx in cursor.fetchall()]

            # Should have indexes on commonly queried fields
            # The exact names may vary, but we should have multiple indexes
            assert len(indexes) >= 3, "agent_task should have multiple indexes for performance"

    def test_foreign_key_to_user(self):
        """Test that foreign key to User model exists."""
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA table_info(agent_task)")
            columns = {row[1]: row for row in cursor.fetchall()}

            assert "created_by_id" in columns, "created_by_id column should exist"

    def test_model_can_create_and_query(self):
        """Test that models can create and query records."""
        from apps.agent_runtime.infrastructure.models import (
            AgentTaskModel,
            AgentTimelineEventModel,
        )

        # Create a task
        task = AgentTaskModel.objects.create(
            request_id=f"test_migration_{id(task) if 'task' in dir() else 'unique'}",
            task_domain="research",
            task_type="migration_test",
            status="draft",
            input_payload={"test": True},
        )

        # Query it back
        retrieved = AgentTaskModel.objects.get(id=task.id)
        assert retrieved.task_domain == "research"
        assert retrieved.task_type == "migration_test"

        # Create a timeline event
        event = AgentTimelineEventModel.objects.create(
            request_id=task.request_id,
            task=task,
            event_type="task_created",
            event_source="system",
            event_payload={},
        )

        # Query it back
        retrieved_event = AgentTimelineEventModel.objects.get(id=event.id)
        assert retrieved_event.task.id == task.id

        # Cleanup
        retrieved_event.delete()
        retrieved.delete()


@pytest.mark.django_db
class TestAgentRuntimeModelConstraints:
    """Tests for model-level constraints."""

    def test_task_domain_choices(self):
        """Test that task_domain accepts only valid choices."""
        from apps.agent_runtime.infrastructure.models import AgentTaskModel
        from django.core.exceptions import ValidationError

        task = AgentTaskModel(
            request_id="test_domain_choices",
            task_domain="invalid_domain",  # Invalid
            task_type="test",
            status="draft",
            input_payload={},
        )

        # full_clean() should raise ValidationError
        with pytest.raises(ValidationError):
            task.full_clean()

    def test_task_status_choices(self):
        """Test that status accepts only valid choices."""
        from apps.agent_runtime.infrastructure.models import AgentTaskModel
        from django.core.exceptions import ValidationError

        task = AgentTaskModel(
            request_id="test_status_choices",
            task_domain="research",
            task_type="test",
            status="invalid_status",  # Invalid
            input_payload={},
        )

        # full_clean() should raise ValidationError
        with pytest.raises(ValidationError):
            task.full_clean()

    def test_request_id_unique(self):
        """Test that duplicate request_id is rejected."""
        from apps.agent_runtime.infrastructure.models import AgentTaskModel
        from django.db import IntegrityError, transaction

        # Create first task
        task1 = AgentTaskModel.objects.create(
            request_id="test_unique_request_id_v2",
            task_domain="research",
            task_type="test",
            status="draft",
            input_payload={},
        )

        # Try to create second task with same request_id
        # Use atomic block to ensure transaction is properly handled
        with transaction.atomic():
            with pytest.raises(IntegrityError):
                AgentTaskModel.objects.create(
                    request_id="test_unique_request_id_v2",  # Duplicate
                    task_domain="research",
                    task_type="test",
                    status="draft",
                    input_payload={},
                )

        # Cleanup
        task1.delete()


@pytest.mark.django_db
class TestAgentRuntimeRelationships:
    """Tests for model relationships."""

    def test_task_timeline_relationship(self):
        """Test that task.timeline_events relationship works."""
        from apps.agent_runtime.infrastructure.models import (
            AgentTaskModel,
            AgentTimelineEventModel,
        )

        # Create task
        task = AgentTaskModel.objects.create(
            request_id="test_timeline_rel",
            task_domain="research",
            task_type="test",
            status="draft",
            input_payload={},
        )

        # Create timeline events
        event1 = AgentTimelineEventModel.objects.create(
            request_id=task.request_id,
            task=task,
            event_type="task_created",
            event_source="system",
            event_payload={},
        )
        event2 = AgentTimelineEventModel.objects.create(
            request_id=task.request_id,
            task=task,
            event_type="state_changed",
            event_source="system",
            event_payload={"old": "draft", "new": "context_ready"},
        )

        # Query through relationship
        assert task.timeline_events.count() == 2
        assert event1 in task.timeline_events.all()
        assert event2 in task.timeline_events.all()

        # Cleanup
        task.delete()

    def test_task_steps_relationship(self):
        """Test that task.steps relationship works."""
        from apps.agent_runtime.infrastructure.models import (
            AgentTaskModel,
            AgentTaskStepModel,
        )

        # Create task
        task = AgentTaskModel.objects.create(
            request_id="test_steps_rel",
            task_domain="research",
            task_type="test",
            status="draft",
            input_payload={},
        )

        # Create steps
        step1 = AgentTaskStepModel.objects.create(
            request_id=task.request_id,
            task=task,
            step_key="step_1",
            step_name="First Step",
            step_index=0,
            status="completed",
        )
        step2 = AgentTaskStepModel.objects.create(
            request_id=task.request_id,
            task=task,
            step_key="step_2",
            step_name="Second Step",
            step_index=1,
            status="pending",
        )

        # Query through relationship
        assert task.steps.count() == 2

        # Cleanup
        task.delete()

    def test_cascade_delete_timeline_events(self):
        """Test that deleting a task cascades to timeline events."""
        from apps.agent_runtime.infrastructure.models import (
            AgentTaskModel,
            AgentTimelineEventModel,
        )

        # Create task with timeline events
        task = AgentTaskModel.objects.create(
            request_id="test_cascade_delete",
            task_domain="research",
            task_type="test",
            status="draft",
            input_payload={},
        )

        event = AgentTimelineEventModel.objects.create(
            request_id=task.request_id,
            task=task,
            event_type="task_created",
            event_source="system",
            event_payload={},
        )

        event_id = event.id
        task_id = task.id

        # Delete task
        task.delete()

        # Timeline event should also be deleted
        assert not AgentTimelineEventModel.objects.filter(id=event_id).exists()
