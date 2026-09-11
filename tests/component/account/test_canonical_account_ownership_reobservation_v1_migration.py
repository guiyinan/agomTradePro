"""PostgreSQL migration roundtrip for the durable ownership re-observation ledger."""

from importlib import import_module

from django.apps import apps
from django.db import connections
from django.db.migrations.state import ProjectState

from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_models import (
    CanonicalAccountOwnershipReobservationV1Model,
)

pytest_plugins = [
    "tests.component.account.test_current_account_ownership_postgres",
    "tests.component.account.creation_chain_postgres_fixture",
]


def test_migration_0060_roundtrip_constraints_and_repeatable_binding_fk(
    creation_chain_alias: str,
) -> None:
    """Apply, reverse, and reapply with two protected many-to-one parents."""

    module = import_module(
        "apps.account.migrations.0060_canonical_account_ownership_reobservation_v1"
    )
    migration = module.Migration("0060_canonical_account_ownership_reobservation_v1", "account")
    connection = connections[creation_chain_alias]
    before = ProjectState.from_apps(apps)
    before.remove_model("account", "canonicalaccountownershipreobservationv1model")
    original_tables = set(connection.introspection.table_names())
    for _ in range(2):
        with connection.schema_editor() as editor:
            migration.apply(before.clone(), editor)
        try:
            with connection.cursor() as cursor:
                constraints = connection.introspection.get_constraints(
                    cursor,
                    CanonicalAccountOwnershipReobservationV1Model._meta.db_table,
                )
            assert {
                constraint.name
                for constraint in CanonicalAccountOwnershipReobservationV1Model._meta.constraints
            } <= set(constraints)
            assert sum(bool(value["foreign_key"]) for value in constraints.values()) == 2
            binding_field = CanonicalAccountOwnershipReobservationV1Model._meta.get_field("binding")
            physical_field = CanonicalAccountOwnershipReobservationV1Model._meta.get_field(
                "current_physical"
            )
            assert binding_field.many_to_one is True
            assert binding_field.one_to_one is False
            assert physical_field.many_to_one is True
            assert physical_field.one_to_one is False
            assert binding_field.remote_field.on_delete.__name__ == "PROTECT"
            assert physical_field.remote_field.on_delete.__name__ == "PROTECT"
        finally:
            with connection.schema_editor() as editor:
                migration.unapply(before.clone(), editor)
        assert set(connection.introspection.table_names()) == original_tables
