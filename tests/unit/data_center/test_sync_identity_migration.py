"""Migration-state checks for the zero-seed sync identity table."""

from __future__ import annotations

import importlib

from django.db.migrations.operations.models import CreateModel
from django.db.migrations.state import ProjectState


def test_sync_identity_migration_is_one_zero_seed_create_model() -> None:
    migration = importlib.import_module(
        "apps.data_center.migrations.0071_syncexecutionidentitymodel"
    ).Migration

    assert migration.dependencies == [("data_center", "0070_rawaudit_identity_and_content_hash")]
    assert len(migration.operations) == 1
    operation = migration.operations[0]
    assert isinstance(operation, CreateModel)

    before = ProjectState()
    after = before.clone()
    operation.state_forwards("data_center", after)
    model_state = after.models[("data_center", "syncexecutionidentitymodel")]
    field_names = set(model_state.fields)
    assert field_names == {
        "identity_hash",
        "run_id",
        "ingested_run_id",
        "batch_id",
        "dataset_key",
        "provider_name",
    }
    assert not any(
        field.has_default() for field in model_state.fields.values()
    ), "identity schema must not invent UUIDs or clocks"
    assert not any(
        operation.__class__.__name__ in {"RunPython", "RunSQL"}
        for operation in migration.operations
    )
