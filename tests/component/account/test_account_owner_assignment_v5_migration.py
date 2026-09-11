"""PostgreSQL migration roundtrip for durable ownership Receipt and Subject V5."""

from importlib import import_module

from django.apps import apps
from django.db import connections
from django.db.migrations.state import ProjectState

from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)

pytest_plugins = [
    "tests.component.account.test_current_account_ownership_postgres",
    "tests.component.account.creation_chain_postgres_fixture",
]


def test_migration_0061_roundtrip_constraints_and_exact_parent_cardinality(
    creation_chain_alias: str,
) -> None:
    """Apply, reverse, and reapply both V5 ledgers over their real parents."""

    reobservation_module = import_module(
        "apps.account.migrations.0060_canonical_account_ownership_reobservation_v1"
    )
    v5_module = import_module("apps.account.migrations.0061_account_owner_assignment_v5")
    reobservation_migration = reobservation_module.Migration(
        "0060_canonical_account_ownership_reobservation_v1", "account"
    )
    v5_migration = v5_module.Migration("0061_account_owner_assignment_v5", "account")
    connection = connections[creation_chain_alias]
    state_0059 = ProjectState.from_apps(apps)
    state_0059.remove_model("account", "accountownerassignmentprovenancereceiptv5model")
    state_0059.remove_model("account", "accountownerassignmentsubjectv5model")
    state_0059.remove_model("account", "canonicalaccountownershipreobservationv1model")
    state_0060 = ProjectState.from_apps(apps)
    state_0060.remove_model("account", "accountownerassignmentprovenancereceiptv5model")
    state_0060.remove_model("account", "accountownerassignmentsubjectv5model")
    original_tables = set(connection.introspection.table_names())

    with connection.schema_editor() as editor:
        editor.create_model(SingleOwnerAuthorityPolicyV1Model)
    try:
        for _ in range(2):
            with connection.schema_editor() as editor:
                reobservation_migration.apply(state_0059.clone(), editor)
                v5_migration.apply(state_0060.clone(), editor)
            try:
                with connection.cursor() as cursor:
                    receipt_constraints = connection.introspection.get_constraints(
                        cursor,
                        AccountOwnerAssignmentProvenanceReceiptV5Model._meta.db_table,
                    )
                    subject_constraints = connection.introspection.get_constraints(
                        cursor,
                        AccountOwnerAssignmentSubjectV5Model._meta.db_table,
                    )
                assert {
                    constraint.name
                    for constraint in AccountOwnerAssignmentProvenanceReceiptV5Model._meta.constraints
                } <= set(receipt_constraints)
                assert {
                    constraint.name
                    for constraint in AccountOwnerAssignmentSubjectV5Model._meta.constraints
                } <= set(subject_constraints)
                assert (
                    sum(bool(value["foreign_key"]) for value in receipt_constraints.values()) == 4
                )
                assert (
                    sum(bool(value["foreign_key"]) for value in subject_constraints.values()) == 3
                )
                binding = AccountOwnerAssignmentProvenanceReceiptV5Model._meta.get_field("binding")
                reobservation = AccountOwnerAssignmentProvenanceReceiptV5Model._meta.get_field(
                    "reobservation"
                )
                receipt = AccountOwnerAssignmentSubjectV5Model._meta.get_field("receipt")
                assert binding.many_to_one is True and binding.one_to_one is False
                assert reobservation.many_to_one is True and reobservation.one_to_one is False
                assert receipt.one_to_one is True
            finally:
                with connection.schema_editor() as editor:
                    v5_migration.unapply(state_0060.clone(), editor)
                    reobservation_migration.unapply(state_0059.clone(), editor)
            assert set(connection.introspection.table_names()) == original_tables | {
                SingleOwnerAuthorityPolicyV1Model._meta.db_table
            }
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(SingleOwnerAuthorityPolicyV1Model)
    assert set(connection.introspection.table_names()) == original_tables
