"""Actual PostgreSQL apply/reverse/reapply for the independent V2 owner ledgers."""

from importlib import import_module

from django.apps import apps
from django.db import connections
from django.db.migrations.state import ProjectState

from apps.account.infrastructure.owner_tenant_authority_v2_models import (
    OwnerTenantAuthorityV2Model,
    OwnerTenantAuthorityV2RevocationModel,
)

pytest_plugins = [
    "tests.component.account.test_account_owner_assignment_evidence_v4_repository",
]


def test_migration_0059_roundtrip_constraints_and_protected_parent_foreign_keys(assignment_alias):
    module = import_module("apps.account.migrations.0059_owner_tenant_authority_v2")
    migration = module.Migration("0059_owner_tenant_authority_v2", "account")
    connection = connections[assignment_alias]
    before = ProjectState.from_apps(apps)
    before.remove_model("account", "ownertenantauthorityv2revocationmodel")
    before.remove_model("account", "ownertenantauthorityv2model")
    models = ((OwnerTenantAuthorityV2Model, 3), (OwnerTenantAuthorityV2RevocationModel, 2))
    original_tables = set(connection.introspection.table_names())
    for _ in range(2):
        with connection.schema_editor() as editor:
            migration.apply(before.clone(), editor)
        try:
            for model, expected_fks in models:
                with connection.cursor() as cursor:
                    constraints = connection.introspection.get_constraints(
                        cursor, model._meta.db_table
                    )
                assert {constraint.name for constraint in model._meta.constraints} <= set(
                    constraints
                )
                assert (
                    sum(bool(value["foreign_key"]) for value in constraints.values())
                    == expected_fks
                )
                for field in model._meta.fields:
                    if field.many_to_one or field.one_to_one:
                        assert field.remote_field.on_delete.__name__ == "PROTECT"
        finally:
            with connection.schema_editor() as editor:
                migration.unapply(before.clone(), editor)
        assert set(connection.introspection.table_names()) == original_tables
