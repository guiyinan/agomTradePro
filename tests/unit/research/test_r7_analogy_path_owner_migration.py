"""Static schema contract for Research migration 0025."""

from importlib import import_module

from django.db import migrations


def test_0025_is_six_table_schema_only_and_depends_exactly_on_0024() -> None:
    module = import_module("apps.research.migrations.0025_r7_analogy_path_owner")
    migration = module.Migration

    assert migration.dependencies == [("research", "0024_r6_scope_qualification_registry")]
    assert len(migration.operations) == 6
    assert all(type(operation) is migrations.CreateModel for operation in migration.operations)
    assert {operation.name for operation in migration.operations} == {
        "R7HistoricalAnalogyCandidateModel",
        "R7HistoricalAnalogyDefinitionModel",
        "R7HistoricalAnalogyReceiptModel",
        "R7ScenarioPathDefinitionModel",
        "R7ScenarioPathMemberModel",
        "R7ScenarioPathReceiptModel",
    }
    assert not any(
        isinstance(operation, (migrations.RunPython, migrations.RunSQL))
        for operation in migration.operations
    )
