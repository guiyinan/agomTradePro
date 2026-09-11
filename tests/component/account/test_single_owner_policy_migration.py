"""Apply and reverse the policy migration on the isolated PostgreSQL alias."""

from importlib import import_module

from django.db import connections
from django.db.migrations.state import ProjectState

from apps.account.infrastructure.single_owner_authority_policy_v1_models import (
    SingleOwnerAuthorityPolicyV1Model,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    evid06_alias as evid06_alias,
)


def test_policy_migration_applies_reverses_and_reapplies(evid06_alias: str) -> None:
    """Verify real DDL and constraint names without replaying unrelated history."""
    module = import_module("apps.account.migrations.0056_single_owner_authority_policy_v1")
    migration = module.Migration("0056_single_owner_authority_policy_v1", "account")
    assert migration.dependencies == [("account", "0055_owner_tenant_authority_v1")]
    connection = connections[evid06_alias]
    table = SingleOwnerAuthorityPolicyV1Model._meta.db_table
    assert table not in connection.introspection.table_names()
    before = ProjectState()
    for _ in range(2):
        applied = False
        try:
            with connection.schema_editor() as editor:
                after = migration.apply(before.clone(), editor)
            applied = True
            historical = after.apps.get_model("account", "SingleOwnerAuthorityPolicyV1Model")
            with connection.cursor() as cursor:
                columns = connection.introspection.get_table_description(cursor, table)
                constraints = connection.introspection.get_constraints(cursor, table)
            assert (
                {column.name for column in columns}
                == {field.column for field in historical._meta.local_fields}
                == {field.column for field in SingleOwnerAuthorityPolicyV1Model._meta.local_fields}
            )
            expected = {item.name for item in SingleOwnerAuthorityPolicyV1Model._meta.constraints}
            assert expected <= set(constraints)
            assert constraints["acct_sop_v1_policy_root_uq"]["unique"]
            assert constraints["acct_sop_v1_clock_ck"]["check"]
        finally:
            if applied:
                with connection.schema_editor() as editor:
                    migration.unapply(before.clone(), editor)
        assert table not in connection.introspection.table_names()
