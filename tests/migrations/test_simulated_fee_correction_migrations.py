"""Real single-migration round-trip coverage for simulated fee corrections."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from django.apps.registry import Apps
from django.conf import settings
from django.db import connection
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.loader import MigrationLoader
from django.db.models import Model
from django.test import override_settings

APP_LABEL = "simulated_trading"
PARENT = "0039_simulated_order_fill_release_proof"
TARGET = "0040_simulated_fee_correction"


def _legacy_values(instance: Model) -> dict[str, object]:
    """Return persisted fields from one pre-migration row."""

    return {
        field.attname: getattr(instance, field.attname) for field in instance._meta.concrete_fields
    }


def _assert_parent_rows(
    rows: tuple[tuple[type[Model], int], ...],
    expected: dict[str, dict[str, object]],
    database: BaseDatabaseWrapper,
) -> None:
    """Assert parent-state rows retain every field across a reverse operation."""

    for model, primary_key in rows:
        instance = model._base_manager.using(database.alias).get(pk=primary_key)
        assert _legacy_values(instance) == expected[model._meta.model_name]


def _assert_migrated_rows(
    models: tuple[type[Model], ...],
    instances: tuple[Model, ...],
    expected: dict[str, dict[str, object]],
) -> None:
    """Assert forward migration retained the complete parent-state field values."""

    for model, instance in zip(models, instances, strict=True):
        old_values = expected[model._meta.model_name]
        assert {key: getattr(instance, key) for key in old_values} == old_values


def _rows(model: type[Model], database: BaseDatabaseWrapper) -> tuple[tuple[object, ...], ...]:
    """Snapshot every persisted field in a table in primary-key order."""

    fields = tuple(field.attname for field in model._meta.concrete_fields)
    values = model._base_manager.using(database.alias).order_by("pk").values_list(*fields)
    return tuple(tuple(row) for row in values)


def _database_shape(
    database: BaseDatabaseWrapper,
    models: tuple[type[Model], ...],
) -> tuple[
    tuple[str, ...],
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
]:
    """Capture table names, columns, and constraint/index names for comparison."""

    table_names = tuple(sorted(database.introspection.table_names()))
    columns: dict[str, tuple[str, ...]] = {}
    constraints: dict[str, tuple[str, ...]] = {}
    with database.cursor() as cursor:
        for model in models:
            table = model._meta.db_table
            columns[table] = tuple(
                column.name
                for column in database.introspection.get_table_description(cursor, table)
            )
            constraints[table] = tuple(
                sorted(database.introspection.get_constraints(cursor, table))
            )
    return table_names, columns, constraints


def _assert_snapshot_unchanged(
    before_shape: tuple[
        tuple[str, ...],
        dict[str, tuple[str, ...]],
        dict[str, tuple[str, ...]],
    ],
    before_rows: dict[str, tuple[tuple[object, ...], ...]],
    database: BaseDatabaseWrapper,
    models: tuple[type[Model], ...],
) -> None:
    """Assert a rejected reverse left the target schema and all target rows intact."""

    assert _database_shape(database, models) == before_shape
    assert {model._meta.db_table: _rows(model, database) for model in models} == before_rows


def _create_legacy_rows(
    apps: Apps,
    database: BaseDatabaseWrapper,
) -> tuple[Model, Model, Model]:
    """Create representative legacy account, trade, and daily rows at 0039."""

    user_label, user_name = settings.AUTH_USER_MODEL.split(".")
    user_model = apps.get_model(user_label, user_name)
    owner = user_model._default_manager.using(database.alias).create(
        username=f"fee-migration-{uuid4()}",
        password="!",
        is_staff=False,
        is_active=True,
        is_superuser=False,
    )
    account_model = apps.get_model(APP_LABEL, "SimulatedAccountModel")
    account = account_model._default_manager.using(database.alias).create(
        user=owner,
        account_name=f"fee-migration-{uuid4()}",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("97500.00"),
        current_market_value=Decimal("2500.00"),
        total_value=Decimal("100000.00"),
        cash_known=True,
        cash_reconciliation_status="simulated_ledger",
    )
    trade_model = apps.get_model(APP_LABEL, "SimulatedTradeModel")
    trade = trade_model._default_manager.using(database.alias).create(
        account=account,
        asset_code="600000.SH",
        asset_name="Migration sample",
        asset_type="equity",
        action="buy",
        quantity=Decimal("100"),
        price=Decimal("25.00"),
        amount=Decimal("2500.00"),
        commission=Decimal("0.00"),
        slippage=Decimal("0.00"),
        total_cost=Decimal("2500.00"),
        order_date=date(2025, 1, 2),
        execution_date=date(2025, 1, 2),
        status="executed",
    )
    daily_model = apps.get_model(APP_LABEL, "DailyNetValueModel")
    daily = daily_model._default_manager.using(database.alias).create(
        account=account,
        record_date=date(2025, 1, 2),
        net_value=Decimal("100000.0000"),
        cash=Decimal("97500.00"),
        market_value=Decimal("2500.00"),
    )
    return account, trade, daily


def _create_fee_evidence(
    apps: Apps,
    database: BaseDatabaseWrapper,
    account: Model,
    trade: Model,
) -> tuple[type[Model], ...]:
    """Create a valid nonempty artifact, policy, binding, and event chain."""

    user_label, user_name = settings.AUTH_USER_MODEL.split(".")
    user_model = apps.get_model(user_label, user_name)
    owner = user_model._default_manager.using(database.alias).get(pk=account.user_id)
    artifact_model = apps.get_model(APP_LABEL, "FeeCorrectionEvidenceArtifactModel")
    binding_model = apps.get_model(APP_LABEL, "FeeCorrectionEvidenceBindingModel")
    policy_model = apps.get_model(APP_LABEL, "FeeCorrectionEvidencePolicyModel")
    event_model = apps.get_model(APP_LABEL, "SimulatedFeeCorrectionEventModel")
    artifact = artifact_model._default_manager.using(database.alias).create(
        account=account,
        uploaded_by=owner,
        original_filename="operator-attested-fees.csv",
        assurance_class="operator_attested_upload",
        schema_version="operator-fee-evidence.v2",
        raw_bytes=b"captured fixture bytes",
        content_sha256="a" * 64,
        payload_sha256="b" * 64,
        raw_row_json={"row": 1},
        parsed_metadata_json={"source": "migration-test"},
        uploaded_at=datetime(2026, 10, 24, 8, 0, tzinfo=UTC),
    )
    policy = policy_model._default_manager.using(database.alias).create(
        account=account,
        enabled=False,
        allow_operator_attested_upload=False,
        ledger_currency="",
        version=1,
        valid_from=None,
        valid_until=None,
        updated_by=None,
    )
    created_at = datetime(2026, 10, 24, 8, 1, tzinfo=UTC)
    binding_model._default_manager.using(database.alias).create(
        account=account,
        artifact=artifact,
        policy=policy,
        trade=trade,
        attested_by=owner,
        idempotency_key="migration-binding-key",
        attestation_version="operator-fee-attestation.v1",
        attestation_acknowledged=True,
        assurance_class="operator_attested_upload",
        expected_revision=0,
        expected_predecessor_id=None,
        content_sha256="a" * 64,
        payload_sha256="b" * 64,
        trade_snapshot_sha256="c" * 64,
        policy_version=1,
        policy_sha256="d" * 64,
        policy_snapshot_json={"version": 1},
        created_at=created_at,
    )
    observed_at = datetime(2026, 10, 24, 8, 2, tzinfo=UTC)
    verified_at = datetime(2026, 10, 24, 8, 3, tzinfo=UTC)
    posted_at = datetime(2026, 10, 24, 8, 4, tzinfo=UTC)
    event_model._default_manager.using(database.alias).create(
        account=account,
        trade=trade,
        actor_user=owner,
        previous_event=None,
        revision=1,
        account_revision=1,
        account_predecessor_hash="0" * 64,
        account_prefix_hash="1" * 64,
        idempotency_key="migration-event-key",
        request_payload_hash="2" * 64,
        trade_snapshot_hash="3" * 64,
        receipt_snapshot_hash=None,
        source_namespace="migration-test-source",
        source_record_id="migration-test-record",
        verifier_identity="migration-test-verifier",
        source_evidence_hash="4" * 64,
        source_payload_hash="5" * 64,
        source_observed_at=observed_at,
        evidence_verified_at=verified_at,
        authority_identity="operator-attestation",
        authority_record_id="migration-test-authority",
        authority_hash="6" * 64,
        authority_snapshot_json=None,
        authority_snapshot_sha256=None,
        previous_commission=Decimal("0.00"),
        previous_transfer_fee=Decimal("0.00"),
        previous_stamp_duty=Decimal("0.00"),
        revised_commission=Decimal("0.00"),
        revised_transfer_fee=Decimal("0.00"),
        revised_stamp_duty=Decimal("0.00"),
        original_slippage=Decimal("0.00"),
        commission_delta=Decimal("0.00"),
        transfer_fee_delta=Decimal("0.00"),
        stamp_duty_delta=Decimal("0.00"),
        total_fee_delta=Decimal("0.00"),
        cash_delta=Decimal("0.00"),
        posted_at=posted_at,
        posting_date=posted_at.date(),
    )
    return (
        artifact_model,
        binding_model,
        policy_model,
        event_model,
    )


@pytest.mark.django_db(transaction=True)
def test_0040_roundtrip_preserves_legacy_rows_and_reverse_refuses_evidence() -> None:
    """Apply only 0040 around retained legacy rows and prove protected reversal fails closed."""

    applied = True
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(connection)
        migration = loader.get_migration(APP_LABEL, TARGET)
        parent_state = loader.project_state([(APP_LABEL, PARENT)])
        migrated_state = loader.project_state([(APP_LABEL, TARGET)])
        assert (APP_LABEL, PARENT) in migration.dependencies
        current_models = tuple(
            migrated_state.apps.get_model(APP_LABEL, name)
            for name in (
                "SimulatedAccountModel",
                "SimulatedTradeModel",
                "DailyNetValueModel",
                "FeeCorrectionEvidenceArtifactModel",
                "FeeCorrectionEvidenceBindingModel",
                "FeeCorrectionEvidencePolicyModel",
                "SimulatedFeeCorrectionEventModel",
            )
        )
        expected_tables = {model._meta.db_table for model in current_models}
        assert expected_tables <= set(connection.introspection.table_names())
        daily_table = current_models[2]._meta.db_table
        with connection.cursor() as cursor:
            current_columns = {
                column.name
                for column in connection.introspection.get_table_description(cursor, daily_table)
            }
        assert {
            "correction_event_watermark",
            "correction_event_watermark_sha256",
        } <= current_columns

        try:
            migrated_apps = migrated_state.apps
            old_apps = parent_state.apps
            account, trade, daily = _create_legacy_rows(migrated_apps, connection)
            legacy_rows = (
                (old_apps.get_model(APP_LABEL, "SimulatedAccountModel"), account.pk),
                (old_apps.get_model(APP_LABEL, "SimulatedTradeModel"), trade.pk),
                (old_apps.get_model(APP_LABEL, "DailyNetValueModel"), daily.pk),
            )
            legacy_snapshots = {
                model._meta.model_name: _legacy_values(
                    model._base_manager.using(connection.alias).get(pk=pk)
                )
                for model, pk in legacy_rows
            }
            initial_daily = migrated_apps.get_model(
                APP_LABEL, "DailyNetValueModel"
            )._base_manager.get(pk=daily.pk)
            assert initial_daily.correction_event_watermark is None
            assert initial_daily.correction_event_watermark_sha256 is None

            # unapply rebuilds operation states from the migration's parent state.
            with connection.schema_editor(atomic=migration.atomic) as editor:
                migration.unapply(parent_state.clone(), editor)
            applied = False
            _assert_parent_rows(legacy_rows, legacy_snapshots, connection)

            with connection.schema_editor(atomic=migration.atomic) as editor:
                migration.apply(parent_state.clone(), editor)
            applied = True

            migrated_apps = loader.project_state([(APP_LABEL, TARGET)]).apps
            migrated_models = tuple(
                migrated_apps.get_model(APP_LABEL, name)
                for name in (
                    "SimulatedAccountModel",
                    "SimulatedTradeModel",
                    "DailyNetValueModel",
                )
            )
            current_instances = (
                migrated_models[0]._base_manager.get(pk=account.pk),
                migrated_models[1]._base_manager.get(pk=trade.pk),
                migrated_models[2]._base_manager.get(pk=daily.pk),
            )
            _assert_migrated_rows(migrated_models, current_instances, legacy_snapshots)
            assert current_instances[2].correction_event_watermark is None
            assert current_instances[2].correction_event_watermark_sha256 is None

            with connection.schema_editor(atomic=migration.atomic) as editor:
                migration.unapply(parent_state.clone(), editor)
            applied = False
            _assert_parent_rows(legacy_rows, legacy_snapshots, connection)

            with connection.schema_editor(atomic=migration.atomic) as editor:
                migration.apply(parent_state.clone(), editor)
            applied = True
            migrated_apps = loader.project_state([(APP_LABEL, TARGET)]).apps
            migrated_models = tuple(
                migrated_apps.get_model(APP_LABEL, name)
                for name in (
                    "SimulatedAccountModel",
                    "SimulatedTradeModel",
                    "DailyNetValueModel",
                )
            )
            current_instances = (
                migrated_models[0]._base_manager.get(pk=account.pk),
                migrated_models[1]._base_manager.get(pk=trade.pk),
                migrated_models[2]._base_manager.get(pk=daily.pk),
            )
            _assert_migrated_rows(migrated_models, current_instances, legacy_snapshots)
            assert current_instances[2].correction_event_watermark is None
            assert current_instances[2].correction_event_watermark_sha256 is None

            evidence_models = _create_fee_evidence(
                migrated_apps,
                connection,
                current_instances[0],
                current_instances[1],
            )
            daily_model = migrated_models[2]
            account_model, trade_model = migrated_models[:2]
            protected_models = (*migrated_models, *evidence_models)
            assert all(
                model._base_manager.using(connection.alias).exists() for model in protected_models
            )

            before_shape = _database_shape(connection, protected_models)
            before_rows = {
                model._meta.db_table: _rows(model, connection) for model in protected_models
            }
            with pytest.raises(IrreversibleError, match="financial or qualification evidence"):
                with connection.schema_editor(atomic=migration.atomic) as editor:
                    migration.unapply(parent_state.clone(), editor)
            _assert_snapshot_unchanged(before_shape, before_rows, connection, protected_models)

            event_model = migrated_apps.get_model(APP_LABEL, "SimulatedFeeCorrectionEventModel")
            binding_model = migrated_apps.get_model(APP_LABEL, "FeeCorrectionEvidenceBindingModel")
            artifact_model = migrated_apps.get_model(
                APP_LABEL, "FeeCorrectionEvidenceArtifactModel"
            )
            policy_model = migrated_apps.get_model(APP_LABEL, "FeeCorrectionEvidencePolicyModel")
            event_model._base_manager.using(connection.alias).all().delete()
            binding_model._base_manager.using(connection.alias).all().delete()
            artifact_model._base_manager.using(connection.alias).all().delete()
            policy_model._base_manager.using(connection.alias).all().delete()
            daily_model._base_manager.using(connection.alias).filter(pk=daily.pk).update(
                correction_event_watermark=1,
                correction_event_watermark_sha256="9" * 64,
            )
            assert not any(
                model._base_manager.using(connection.alias).exists()
                for model in (event_model, binding_model, artifact_model, policy_model)
            )

            before_shape = _database_shape(connection, protected_models)
            before_rows = {
                model._meta.db_table: _rows(model, connection) for model in protected_models
            }
            with pytest.raises(IrreversibleError, match="captured watermarks"):
                with connection.schema_editor(atomic=migration.atomic) as editor:
                    migration.unapply(parent_state.clone(), editor)
            _assert_snapshot_unchanged(before_shape, before_rows, connection, protected_models)
            assert account_model._base_manager.filter(pk=account.pk).exists()
            assert trade_model._base_manager.filter(pk=trade.pk).exists()
        finally:
            if not applied:
                with connection.schema_editor(atomic=migration.atomic) as editor:
                    migration.apply(parent_state.clone(), editor)
