"""Apply the real policy migration to a retained legacy row in an isolated database."""

from django.db import connections
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings


def test_policy_migration_preserves_legacy_content_and_adds_independent_version(
    django_db_blocker,
) -> None:
    settings = dict(connections["default"].settings_dict)
    settings["NAME"] = ":memory:"
    wrapper = connections["default"].__class__(settings, alias="data16_policy_migration")
    connections["data16_policy_migration"] = wrapper
    with django_db_blocker.unblock():
        try:
            with override_settings(MIGRATION_MODULES={}):
                loader = MigrationLoader(wrapper)
            state = loader.project_state([("data_center", "0075_egress_routing")])
            legacy_model = state.apps.get_model("data_center", "DatasetPublicationPolicyModel")
            with wrapper.schema_editor() as editor:
                editor.create_model(legacy_model)
            with wrapper.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO data_center_dataset_publication_policy "
                    "(dataset_key, contract_version, schema_version, minimum_coverage_ratio, "
                    "allow_partial, conflict_action, required_evidence, retention_days, active, "
                    "created_at, updated_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                    [
                        "test.retained.policy",
                        "1.0",
                        "1.0",
                        0.99,
                        True,
                        "quarantine",
                        '["source","payload_hash"]',
                        3650,
                        True,
                    ],
                )
                cursor.execute("SELECT * FROM data_center_dataset_publication_policy")
                before = dict(
                    zip(
                        [column[0] for column in cursor.description], cursor.fetchone(), strict=True
                    )
                )
            assert "policy_version" not in before
            migration = loader.get_migration("data_center", "0076_publication_policy_versions")
            with wrapper.schema_editor() as editor:
                migration.apply(state, editor)
            with wrapper.cursor() as cursor:
                cursor.execute("SELECT * FROM data_center_dataset_publication_policy")
                after = dict(
                    zip(
                        [column[0] for column in cursor.description], cursor.fetchone(), strict=True
                    )
                )
            assert after.pop("policy_version") == "legacy"
            assert after == before
            constraints = wrapper.introspection.get_constraints(
                wrapper.cursor(), "data_center_dataset_publication_policy"
            )
            assert constraints["dc_dataset_policy_version_unique"]["columns"] == [
                "dataset_key",
                "contract_version",
                "schema_version",
                "policy_version",
            ]
            assert constraints["dc_dataset_policy_active_unique"]["unique"]
        finally:
            wrapper.close()
            del connections["data16_policy_migration"]
