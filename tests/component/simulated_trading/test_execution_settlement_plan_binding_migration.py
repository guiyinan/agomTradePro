"""Native migration checks for settlement-plan binding compatibility."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from importlib import import_module
from typing import Any
from uuid import uuid4

import pytest
from django.apps import apps as django_apps
from django.db import DatabaseError, connection, connections, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from apps.account.infrastructure.account_authority_generation_models import (
    AccountAuthorityGenerationModel,
)

_PARTIAL_APP_NAMES = (
    "apps.simulated_trading",
    "django.contrib.auth",
    "django.contrib.contenttypes",
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=_PARTIAL_APP_NAMES,
)

_BEFORE = ("simulated_trading", "0025_fee_policy_v2_contract")
_AFTER = ("simulated_trading", "0026_simulated_trade_settlement_plan_binding")
_BINDING_TEST_PAYLOAD: dict[str, object] = {
    "test_only": "synthetic reverse-guard marker; not a valid production binding"
}


@pytest.fixture(autouse=True)
def _full_app_registry_for_migration_loader(transactional_db: None) -> Iterator[None]:
    """Balance nested pytest/Django app scopes while exposing migration dependencies."""

    del transactional_db
    expected_partial_names = tuple(sorted(_PARTIAL_APP_NAMES))
    popped_layers: list[tuple[str, ...]] = []
    try:
        for _ in range(4):
            current_names = tuple(sorted(config.name for config in django_apps.get_app_configs()))
            assert current_names == expected_partial_names
            django_apps.unset_available_apps()
            popped_layers.append(current_names)
            if django_apps.is_installed("apps.strategy"):
                break
        assert django_apps.is_installed("apps.strategy")
        yield
    finally:
        for layer_names in reversed(popped_layers):
            django_apps.set_available_apps(layer_names)


def _legacy_trade_values(row: Any) -> tuple[object, ...]:
    """Return business columns that must survive adding and removing 0026."""

    return (
        row.account_id,
        row.asset_code,
        row.asset_name,
        row.asset_type,
        row.action,
        row.quantity,
        row.price,
        row.amount,
        row.total_cost,
        row.order_date,
        row.execution_date,
        row.execution_time,
        row.status,
        row.idempotency_key,
        row.request_payload_hash,
    )


def _create_legacy_rows(apps: Any) -> tuple[int, int, tuple[object, ...]]:
    """Create one account and an unbound trade using the historical app state."""

    account_model = apps.get_model("simulated_trading", "SimulatedAccountModel")
    trade_model = apps.get_model("simulated_trading", "SimulatedTradeModel")
    account = account_model._default_manager.create(
        user=None,
        account_name="plan-binding-migration-fixture",
        account_type="simulated",
        initial_capital=Decimal("1000.00"),
        current_cash=Decimal("1000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("1000.00"),
    )
    trade = trade_model._default_manager.create(
        account_id=account.pk,
        asset_code="TEST.MIGRATION",
        asset_name="Migration fixture",
        asset_type="equity",
        action="buy",
        quantity=Decimal("1.000000"),
        price=Decimal("10.0000"),
        amount=Decimal("10.00"),
        commission=Decimal("0.00"),
        slippage=Decimal("0.00"),
        total_cost=Decimal("10.00"),
        order_date=date(2026, 10, 16),
        execution_date=date(2026, 10, 16),
        status="executed",
    )
    return account.pk, trade.pk, _legacy_trade_values(trade)


def test_0026_upgrade_reverse_guard_and_reforward_preserve_legacy_rows() -> None:
    """Legacy rows stay unbound, while new binding evidence prevents reversal."""

    alias = connection.alias
    generation_before = (
        AccountAuthorityGenerationModel._base_manager.using(alias).get(singleton=1).generation
    )
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    account_id: int | None = None
    trade_id: int | None = None
    bound_payload = dict(_BINDING_TEST_PAYLOAD)
    binding_hash = "a" * 64
    try:
        executor.migrate([_BEFORE])
        historical_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
        account_id, trade_id, original_values = _create_legacy_rows(historical_apps)

        MigrationExecutor(connection).migrate([_AFTER])
        migrated_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        migrated_trade_model = migrated_apps.get_model("simulated_trading", "SimulatedTradeModel")
        migrated_trade = migrated_trade_model._default_manager.get(pk=trade_id)
        assert _legacy_trade_values(migrated_trade) == original_values
        assert migrated_trade.settlement_plan_binding_version == 0
        assert migrated_trade.settlement_plan_binding_payload is None
        assert migrated_trade.settlement_plan_binding_hash is None

        MigrationExecutor(connection).migrate([_BEFORE])
        reversed_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
        reversed_trade = reversed_apps.get_model(
            "simulated_trading", "SimulatedTradeModel"
        )._default_manager.get(pk=trade_id)
        assert _legacy_trade_values(reversed_trade) == original_values

        MigrationExecutor(connection).migrate([_AFTER])
        migrated_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        migrated_trade_model = migrated_apps.get_model("simulated_trading", "SimulatedTradeModel")
        migrated_trade = migrated_trade_model._default_manager.get(pk=trade_id)
        assert _legacy_trade_values(migrated_trade) == original_values
        assert migrated_trade.settlement_plan_binding_version == 0
        assert migrated_trade.settlement_plan_binding_payload is None
        assert migrated_trade.settlement_plan_binding_hash is None

        assert (
            _make_synthetic_binding_row(
                migrated_trade_model,
                trade_id=trade_id,
                payload=bound_payload,
                binding_hash=binding_hash,
                idempotency_key="migration-binding-test",
                using=alias,
            )
            == 1
        )
        with pytest.raises(IrreversibleError, match="retain them"):
            MigrationExecutor(connection).migrate([_BEFORE])

        table_names = set(connection.introspection.table_names())
        assert migrated_trade_model._meta.db_table in table_names
        with connection.cursor() as cursor:
            current_columns = {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor,
                    migrated_trade_model._meta.db_table,
                )
            }
        assert {
            "settlement_plan_binding_version",
            "settlement_plan_binding_payload",
            "settlement_plan_binding_hash",
        } <= current_columns
        preserved = migrated_trade_model._default_manager.get(pk=trade_id)
        assert preserved.settlement_plan_binding_version == 1
        assert preserved.settlement_plan_binding_payload == bound_payload
        assert preserved.settlement_plan_binding_hash == binding_hash
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
    finally:
        try:
            current_tables = set(connection.introspection.table_names())
            if (
                account_id is not None
                and "simulated_account" in current_tables
                and "simulated_trade" in current_tables
            ):
                applied_migrations = MigrationRecorder(connection).applied_migrations()
                cleanup_target = _AFTER if _AFTER in applied_migrations else _BEFORE
                current_apps = (
                    MigrationExecutor(connection).loader.project_state([cleanup_target]).apps
                )
                current_trade_model = current_apps.get_model(
                    "simulated_trading", "SimulatedTradeModel"
                )
                current_account_model = current_apps.get_model(
                    "simulated_trading", "SimulatedAccountModel"
                )
                if trade_id is not None:
                    current_trade_model._base_manager.filter(pk=trade_id).delete()
                current_account_model._base_manager.filter(pk=account_id).delete()
        finally:
            MigrationExecutor(connection).migrate(leaf_nodes)

    generation_after = (
        AccountAuthorityGenerationModel._base_manager.using(alias).get(singleton=1).generation
    )
    assert generation_after == generation_before


def _make_synthetic_binding_row(
    trade_model: Any,
    *,
    trade_id: int,
    payload: dict[str, object],
    binding_hash: str,
    idempotency_key: str,
    using: str,
) -> int:
    """Mark the fixture row as bound so reverse migration must retain its columns."""

    return (
        trade_model._base_manager.using(using)
        .filter(pk=trade_id)
        .update(
            idempotency_key=idempotency_key,
            request_payload_hash="b" * 64,
            fee_config_id=1,
            fee_schedule_hash="c" * 64,
            fee_schedule_snapshot={"schema": "synthetic-test-fixture"},
            fee_precision_basis="database_binary64",
            fee_calculation_purpose="normal_sim_estimated",
            fee_rounding_policy="component_half_even_cents_v1",
            settlement_status="pending",
            settlement_security_id="TEST.MIGRATION.SECURITY",
            settlement_market="TEST",
            settlement_board="TEST_BOARD",
            settlement_market_session=date(2026, 10, 16),
            settlement_lag_sessions=1,
            settlement_plan_binding_version=1,
            settlement_plan_binding_payload=payload,
            settlement_plan_binding_hash=binding_hash,
            settlement_bundle_id="synthetic-bundle",
            settlement_bundle_version="1",
            settlement_bundle_hash="d" * 64,
            settlement_policy_id="synthetic-policy",
            settlement_policy_version="1",
            settlement_policy_hash="e" * 64,
            execution_rule_v2_hash="f" * 64,
            settlement_release_date=date(2026, 10, 19),
            settlement_calendar_snapshot_id=str(uuid4()),
            settlement_calendar_content_hash="sha256:" + "1" * 64,
            settlement_calendar_record_digest="sha256:" + "2" * 64,
            settlement_calendar_publication_id="synthetic-publication",
            settlement_calendar_publication_hash="3" * 64,
            settlement_calendar_policy_hash="4" * 64,
            settlement_calendar_evidence_hash="5" * 64,
            settlement_calendar_timezone="Asia/Shanghai",
        )
    )


def _database_error_sqlstate(error: DatabaseError) -> str | None:
    """Return the driver SQLSTATE when Django exposes one on the error chain."""

    current: BaseException | None = error
    while current is not None:
        for attribute in ("sqlstate", "pgcode"):
            code = getattr(current, attribute, None)
            if isinstance(code, str):
                return code
        current = current.__cause__
    return None


def _write_synthetic_binding(
    *,
    alias: str,
    trade_model: Any,
    trade_id: int,
) -> tuple[str, int | None, str | None]:
    """Try a valid binding update on a worker-owned connection with a short lock timeout."""

    connections.close_all()
    try:
        with transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '500ms'")
            changed = _make_synthetic_binding_row(
                trade_model,
                trade_id=trade_id,
                payload=dict(_BINDING_TEST_PAYLOAD),
                binding_hash="a" * 64,
                idempotency_key=f"migration-lock-{uuid4()}",
                using=alias,
            )
        return "updated", changed, None
    except DatabaseError as error:
        return "database_error", None, _database_error_sqlstate(error)
    finally:
        connections.close_all()


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Reverse migration guard lock behavior requires PostgreSQL row locks.",
)
def test_reverse_guard_blocks_binding_writer_until_outer_transaction_finishes() -> None:
    """The actual reverse guard protects a legacy row from a concurrent binding update."""

    alias = connection.alias
    generation_before = (
        AccountAuthorityGenerationModel._base_manager.using(alias).get(singleton=1).generation
    )
    migration_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    account_model = migration_apps.get_model("simulated_trading", "SimulatedAccountModel")
    trade_model = migration_apps.get_model("simulated_trading", "SimulatedTradeModel")
    account_id: int | None = None
    trade_id: int | None = None
    try:
        account_id, trade_id, _ = _create_legacy_rows(migration_apps)
        assert trade_model._base_manager.using(alias).count() == 1
        assert (
            trade_model._base_manager.using(alias)
            .filter(
                settlement_plan_binding_version=0,
                settlement_plan_binding_payload__isnull=True,
                settlement_plan_binding_hash__isnull=True,
            )
            .count()
            == 1
        )
        migration = import_module(
            "apps.simulated_trading.migrations.0026_simulated_trade_settlement_plan_binding"
        )
        with transaction.atomic(using=alias):
            with connections[alias].schema_editor(atomic=False) as schema_editor:
                migration.prevent_dropping_settlement_plan_bindings(
                    migration_apps,
                    schema_editor,
                )
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(
                    _write_synthetic_binding,
                    alias=alias,
                    trade_model=trade_model,
                    trade_id=trade_id,
                ).result(timeout=5)
            assert result == ("database_error", None, "55P03"), (
                "reverse guard must block the binding writer with PostgreSQL lock timeout "
                f"SQLSTATE 55P03; got {result!r}"
            )

        legacy_trade = trade_model._base_manager.using(alias).get(pk=trade_id)
        assert legacy_trade.settlement_plan_binding_version == 0
        assert legacy_trade.settlement_plan_binding_payload is None
        assert legacy_trade.settlement_plan_binding_hash is None
    finally:
        if trade_id is not None:
            trade_model._base_manager.using(alias).filter(pk=trade_id).delete()
        if account_id is not None:
            account_model._base_manager.using(alias).filter(pk=account_id).delete()
        generation_after = (
            AccountAuthorityGenerationModel._base_manager.using(alias).get(singleton=1).generation
        )
        assert generation_after == generation_before


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Reverse migration transaction guard is PostgreSQL-specific.",
)
def test_reverse_guard_rejects_non_atomic_schema_editor_without_mutation() -> None:
    """The real reverse guard refuses a PostgreSQL check outside a transaction."""

    assert connection.in_atomic_block is False
    migration_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    trade_model = migration_apps.get_model("simulated_trading", "SimulatedTradeModel")
    migration = import_module(
        "apps.simulated_trading.migrations.0026_simulated_trade_settlement_plan_binding"
    )
    table_name = trade_model._meta.db_table
    rows_before = tuple(
        trade_model._base_manager.using(connection.alias)
        .order_by("pk")
        .values_list(
            "pk",
            "settlement_plan_binding_version",
            "settlement_plan_binding_payload",
            "settlement_plan_binding_hash",
        )
    )
    with connection.cursor() as cursor:
        columns_before = tuple(
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        )
    applied_before = _AFTER in MigrationRecorder(connection).applied_migrations()
    generation_before = (
        AccountAuthorityGenerationModel._base_manager.using(connection.alias)
        .get(singleton=1)
        .generation
    )

    with connection.schema_editor(atomic=False) as schema_editor:
        assert connection.in_atomic_block is False
        with pytest.raises(IrreversibleError, match="outside a PostgreSQL transaction"):
            migration.prevent_dropping_settlement_plan_bindings(
                migration_apps,
                schema_editor,
            )

    assert connection.in_atomic_block is False
    rows_after = tuple(
        trade_model._base_manager.using(connection.alias)
        .order_by("pk")
        .values_list(
            "pk",
            "settlement_plan_binding_version",
            "settlement_plan_binding_payload",
            "settlement_plan_binding_hash",
        )
    )
    with connection.cursor() as cursor:
        columns_after = tuple(
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        )
    applied_after = _AFTER in MigrationRecorder(connection).applied_migrations()
    generation_after = (
        AccountAuthorityGenerationModel._base_manager.using(connection.alias)
        .get(singleton=1)
        .generation
    )
    assert rows_after == rows_before
    assert columns_after == columns_before
    assert applied_after == applied_before
    assert generation_after == generation_before
