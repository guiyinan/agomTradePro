"""PostgreSQL roundtrip coverage for the schema-only Authority V3 migration."""

from importlib import import_module

import pytest
from django.apps import apps
from django.db import connections
from django.db.migrations.state import ProjectState

from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentEvidenceV5Model,
)
from apps.account.infrastructure.owner_tenant_authority_v3_models import (
    OwnerTenantAuthorityV3Model,
    OwnerTenantAuthorityV3RevocationModel,
)

pytest_plugins = [
    "tests.component.account.test_account_owner_assignment_evidence_v5_repository",
]


@pytest.mark.django_db(transaction=True, databases="__all__")
def test_migration_0063_roundtrip_authority_v3_schema(evidence_v5_alias: str) -> None:
    """Apply, reverse, and reapply both immutable Authority V3 ledgers."""

    migration_module = import_module("apps.account.migrations.0063_owner_tenant_authority_v3")
    migration = migration_module.Migration("0063_owner_tenant_authority_v3", "account")
    connection = connections[evidence_v5_alias]
    before = ProjectState.from_apps(apps)
    before.remove_model("account", "ownertenantauthorityv3revocationmodel")
    before.remove_model("account", "ownertenantauthorityv3model")
    models = (
        (OwnerTenantAuthorityV3Model, 4),
        (OwnerTenantAuthorityV3RevocationModel, 2),
    )
    original_tables = set(connection.introspection.table_names())

    for _ in range(2):
        with connection.schema_editor() as editor:
            migration.apply(before.clone(), editor)
        try:
            for model, expected_foreign_keys in models:
                with connection.cursor() as cursor:
                    constraints = connection.introspection.get_constraints(
                        cursor, model._meta.db_table
                    )
                assert {constraint.name for constraint in model._meta.constraints} <= set(
                    constraints
                )
                assert (
                    sum(bool(value["foreign_key"]) for value in constraints.values())
                    == expected_foreign_keys
                )
                for field in model._meta.fields:
                    if field.many_to_one or field.one_to_one:
                        assert field.remote_field.on_delete.__name__ == "PROTECT"
            assignment = OwnerTenantAuthorityV3Model._meta.get_field("assignment")
            assert assignment.many_to_one is True
            assert assignment.one_to_one is False
            assert assignment.remote_field.model is AccountOwnerAssignmentEvidenceV5Model
            predecessor = OwnerTenantAuthorityV3Model._meta.get_field("predecessor")
            assert predecessor.one_to_one is True
            assert predecessor.remote_field.model is OwnerTenantAuthorityV3Model
        finally:
            with connection.schema_editor() as editor:
                migration.unapply(before.clone(), editor)
        assert set(connection.introspection.table_names()) == original_tables
