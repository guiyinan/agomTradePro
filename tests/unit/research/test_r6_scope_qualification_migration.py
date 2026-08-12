"""Static schema contract for Research migration 0024."""

from importlib import import_module

from django.db import migrations


def test_0024_is_schema_only_and_depends_on_the_current_research_leaf() -> None:
    module = import_module("apps.research.migrations.0024_r6_scope_qualification_registry")
    migration = module.Migration
    assert migration.dependencies == [("research", "0023_r8_monitoring_policy_registry")]
    assert len(migration.operations) == 1
    assert type(migration.operations[0]) is migrations.CreateModel
    assert migration.operations[0].name == "R6ScopeQualificationRegistryModel"
    assert not any(
        isinstance(operation, (migrations.RunPython, migrations.RunSQL))
        for operation in migration.operations
    )
