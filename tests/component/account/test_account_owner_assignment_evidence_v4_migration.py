"""Apply, reverse and reapply migration 0058 against real local PostgreSQL parents."""

from importlib import import_module

from django.apps import apps
from django.db import connections
from django.db.migrations.state import ProjectState

from apps.account.infrastructure.account_owner_assignment_evidence_v4_models import (
    AccountOwnerAssignmentEvidenceV4Model,
    AccountOwnerAssignmentSubjectV4Model,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    creation_alias as creation_alias,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    evid06_alias as evid06_alias,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    receipt_alias as receipt_alias,
)


def test_migration_0058_roundtrip_constraints_and_durable_foreign_keys(receipt_alias):
    migration_module = import_module(
        "apps.account.migrations.0058_account_owner_assignment_evidence_v4"
    )
    migration = migration_module.Migration("0058_account_owner_assignment_evidence_v4", "account")
    connection = connections[receipt_alias]
    before = ProjectState.from_apps(apps)
    before.remove_model("account", "accountownerassignmentevidencev4model")
    before.remove_model("account", "accountownerassignmentsubjectv4model")
    models = ((AccountOwnerAssignmentSubjectV4Model, 1), (AccountOwnerAssignmentEvidenceV4Model, 2))
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
        finally:
            with connection.schema_editor() as editor:
                migration.unapply(before.clone(), editor)
        for model, _ in models:
            assert model._meta.db_table not in connection.introspection.table_names()
