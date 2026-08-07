"""Migration evidence for one-time Qlib runtime profile materialization."""

from __future__ import annotations

import importlib
import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

QLIB_KEYS = {
    "alpha.qlib.enabled",
    "alpha.qlib.provider_uri",
    "alpha.qlib.region",
    "alpha.qlib.model_path",
    "alpha.qlib.default_universe",
    "alpha.qlib.default_feature_set_id",
    "alpha.qlib.default_label_id",
    "alpha.qlib.train_queue_name",
    "alpha.qlib.infer_queue_name",
    "alpha.qlib.allow_auto_activate",
}


@pytest.mark.django_db(transaction=True)
def test_qlib_runtime_migration_materializes_once_and_missing_legacy_fails_closed() -> None:
    """Existing canonical values win; fresh databases receive no invented defaults."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("config_center", "0013_materialize_decision_runtime_state")])
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(
            [("config_center", "0013_materialize_decision_runtime_state")]
        ).apps
        Legacy = old_apps.get_model("config_center", "SystemSettingsModel")
        Profile = old_apps.get_model("config_center", "RuntimeConfigProfileModel")
        Value = old_apps.get_model("config_center", "RuntimeConfigValueModel")
        Profile.objects.all().delete()
        Value.objects.all().delete()
        Legacy.objects.all().delete()
        legacy = Legacy.objects.create(
            id=1,
            qlib_enabled=False,
            qlib_provider_uri="/legacy/qlib/cn_data",
            qlib_region="CN",
            qlib_model_path="/legacy/qlib/models",
            qlib_default_universe="csi500",
            qlib_default_feature_set_id="legacy-features",
            qlib_default_label_id="return_10d",
            qlib_train_queue_name="legacy_train",
            qlib_infer_queue_name="legacy_infer",
            qlib_allow_auto_activate=True,
        )
        old_profile_id = uuid.uuid4()
        Profile.objects.create(
            profile_id=old_profile_id,
            profile_key="development",
            environment="development",
            version=1,
            status="active",
            content_hash="old-hash",
            created_by="migration-test",
        )
        Value.objects.create(
            profile_id=old_profile_id,
            definition_key="alpha.qlib.enabled",
            value_json=True,
            source="admin",
        )
        Value.objects.create(
            profile_id=old_profile_id,
            definition_key="alpha.runtime.pool_mode",
            value_json="strict_valuation",
            source="admin",
        )

        executor.migrate([("config_center", "0014_materialize_qlib_runtime_profile")])
        executor = MigrationExecutor(connection)
        new_apps = executor.loader.project_state(
            [("config_center", "0014_materialize_qlib_runtime_profile")]
        ).apps
        Profile = new_apps.get_model("config_center", "RuntimeConfigProfileModel")
        Value = new_apps.get_model("config_center", "RuntimeConfigValueModel")
        Snapshot = new_apps.get_model("config_center", "RuntimeConfigSnapshotModel")
        active = Profile.objects.get(environment="development", status="active")
        values = {
            row.definition_key: row for row in Value.objects.filter(profile_id=active.profile_id)
        }
        assert active.version == 2
        assert active.based_on_profile == str(old_profile_id)
        assert Profile.objects.get(profile_id=old_profile_id).status == "superseded"
        assert QLIB_KEYS.issubset(values)
        assert values["alpha.qlib.enabled"].value_json is True
        assert values["alpha.qlib.enabled"].source == "admin"
        assert values["alpha.qlib.provider_uri"].value_json == legacy.qlib_provider_uri
        assert values["alpha.qlib.provider_uri"].source == "legacy_materialization_0014"
        assert values["alpha.runtime.pool_mode"].value_json == "strict_valuation"
        snapshot = Snapshot.objects.get(profile_id=active.profile_id)
        assert snapshot.profile_version == active.version
        assert QLIB_KEYS.issubset(snapshot.resolved_values)
        assert snapshot.resolved_values["alpha.qlib.enabled"] is True

        migration = importlib.import_module(
            "apps.config_center.migrations.0014_materialize_qlib_runtime_profile"
        )
        before_counts = (Profile.objects.count(), Value.objects.count(), Snapshot.objects.count())
        migration.materialize_qlib_runtime_profile(new_apps, None)
        assert (Profile.objects.count(), Value.objects.count(), Snapshot.objects.count()) == (
            before_counts
        )

        executor.migrate([("config_center", "0013_materialize_decision_runtime_state")])
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(
            [("config_center", "0013_materialize_decision_runtime_state")]
        ).apps
        old_apps.get_model("config_center", "RuntimeConfigSnapshotModel").objects.all().delete()
        old_apps.get_model("config_center", "RuntimeConfigRevisionModel").objects.all().delete()
        old_apps.get_model("config_center", "RuntimeConfigValueModel").objects.all().delete()
        old_apps.get_model("config_center", "RuntimeConfigProfileModel").objects.all().delete()
        old_apps.get_model("config_center", "SystemSettingsModel").objects.all().delete()

        executor.migrate([("config_center", "0014_materialize_qlib_runtime_profile")])
        executor = MigrationExecutor(connection)
        fresh_apps = executor.loader.project_state(
            [("config_center", "0014_materialize_qlib_runtime_profile")]
        ).apps
        assert (
            not fresh_apps.get_model("config_center", "RuntimeConfigProfileModel")
            .objects.filter(environment="development", status="active")
            .exists()
        )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
