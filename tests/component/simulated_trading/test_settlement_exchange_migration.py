"""Native migration checks for the V2 source-exchange binding column."""

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

_PARTIAL_APP_NAMES = (
    "apps.simulated_trading",
    "django.contrib.auth",
    "django.contrib.contenttypes",
)
_BEFORE = ("simulated_trading", "0026_simulated_trade_settlement_plan_binding")
_AFTER = ("simulated_trading", "0027_separate_settlement_exchange_identity")
_SYNTHETIC_PAYLOAD: dict[str, object] = {
    "schema": "test-only-settlement-exchange-binding",
    "purpose": "reverse guard behavior; not a valid execution receipt",
}

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=_PARTIAL_APP_NAMES,
)


@pytest.fixture(autouse=True)
def _full_app_registry_for_migration_loader(transactional_db: None) -> Iterator[None]:
    """Balance pytest app scopes while MigrationExecutor loads dependencies."""

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


def _create_legacy_rows(apps: Any) -> tuple[int, int, tuple[object, ...]]:
    """Create one unbound historical trade and retain its pre-migration facts."""

    account_model = apps.get_model("simulated_trading", "SimulatedAccountModel")
    trade_model = apps.get_model("simulated_trading", "SimulatedTradeModel")
    account = account_model._default_manager.create(
        user=None,
        account_name="exchange-migration-fixture",
        account_type="simulated",
        initial_capital=Decimal("1000.00"),
        current_cash=Decimal("1000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("1000.00"),
    )
    trade = trade_model._default_manager.create(
        account_id=account.pk,
        asset_code="TEST.EXCH.MIG",
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
    original_facts: tuple[object, ...] = (
        trade.account_id,
        trade.asset_code,
        trade.quantity,
        trade.price,
        trade.total_cost,
        trade.execution_date,
        trade.status,
    )
    return int(account.pk), int(trade.pk), original_facts


def _synthetic_v2_fields(*, idempotency_key: str) -> dict[str, object]:
    """Return DB-complete synthetic V2 markers for migration guard tests only."""

    return {
        "idempotency_key": idempotency_key,
        "request_payload_hash": "b" * 64,
        "fee_config_id": 1,
        "fee_schedule_hash": "c" * 64,
        "fee_schedule_snapshot": {"schema": "synthetic-test-fixture"},
        "fee_precision_basis": "database_binary64",
        "fee_calculation_purpose": "normal_sim_estimated",
        "fee_rounding_policy": "component_half_even_cents_v1",
        "settlement_status": "pending",
        "settlement_security_id": "TEST.EXCHANGE.MIGRATION.SECURITY",
        "settlement_market": "SH",
        "settlement_exchange": "SSE",
        "settlement_board": "MAIN",
        "settlement_market_session": date(2026, 10, 16),
        "settlement_lag_sessions": 1,
        "settlement_plan_binding_version": 2,
        "settlement_plan_binding_payload": dict(_SYNTHETIC_PAYLOAD),
        "settlement_plan_binding_hash": "a" * 64,
        "settlement_bundle_id": "synthetic-bundle",
        "settlement_bundle_version": "1",
        "settlement_bundle_hash": "d" * 64,
        "settlement_policy_id": "synthetic-policy",
        "settlement_policy_version": "1",
        "settlement_policy_hash": "e" * 64,
        "execution_rule_v2_hash": "f" * 64,
        "settlement_release_date": date(2026, 10, 19),
        "settlement_calendar_snapshot_id": str(uuid4()),
        "settlement_calendar_content_hash": "sha256:" + "1" * 64,
        "settlement_calendar_record_digest": "sha256:" + "2" * 64,
        "settlement_calendar_publication_id": "synthetic-publication",
        "settlement_calendar_publication_hash": "3" * 64,
        "settlement_calendar_policy_hash": "4" * 64,
        "settlement_calendar_evidence_hash": "5" * 64,
        "settlement_calendar_timezone": "Asia/Shanghai",
    }


def _database_error_sqlstate(error: DatabaseError) -> str | None:
    """Return the database SQLSTATE when the active Django driver exposes it."""

    current: BaseException | None = error
    while current is not None:
        for attribute in ("sqlstate", "pgcode"):
            code = getattr(current, attribute, None)
            if isinstance(code, str):
                return code
        current = current.__cause__
    return None


def _write_v2_binding(
    *,
    alias: str,
    trade_model: Any,
    trade_id: int,
    idempotency_key: str,
) -> tuple[str, int | None, str | None]:
    """Try a valid versioned write on an independent connection."""

    connections.close_all()
    try:
        with transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '500ms'")
            changed = (
                trade_model._base_manager.using(alias)
                .filter(pk=trade_id)
                .update(**_synthetic_v2_fields(idempotency_key=idempotency_key))
            )
        return "updated", changed, None
    except DatabaseError as error:
        return "database_error", None, _database_error_sqlstate(error)
    finally:
        connections.close_all()


def test_0027_upgrade_reverse_reforward_preserves_legacy_and_v2_evidence() -> None:
    """A legacy-only schema can roundtrip; V2 exchange evidence cannot be dropped."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    account_id: int | None = None
    trade_id: int | None = None
    try:
        executor.migrate([_BEFORE])
        before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
        account_id, trade_id, original_facts = _create_legacy_rows(before_apps)

        MigrationExecutor(connection).migrate([_AFTER])
        after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        trade_model = after_apps.get_model("simulated_trading", "SimulatedTradeModel")
        trade = trade_model._default_manager.get(pk=trade_id)
        assert (
            trade.account_id,
            trade.asset_code,
            trade.quantity,
            trade.price,
            trade.total_cost,
            trade.execution_date,
            trade.status,
        ) == original_facts
        assert trade.settlement_plan_binding_version == 0
        assert trade.settlement_plan_binding_payload is None
        assert trade.settlement_plan_binding_hash is None
        assert trade.settlement_exchange is None

        MigrationExecutor(connection).migrate([_BEFORE])
        reversed_model = (
            MigrationExecutor(connection)
            .loader.project_state([_BEFORE])
            .apps.get_model("simulated_trading", "SimulatedTradeModel")
        )
        reversed_trade = reversed_model._default_manager.get(pk=trade_id)
        assert (
            reversed_trade.account_id,
            reversed_trade.asset_code,
            reversed_trade.quantity,
            reversed_trade.price,
            reversed_trade.total_cost,
            reversed_trade.execution_date,
            reversed_trade.status,
        ) == original_facts

        MigrationExecutor(connection).migrate([_AFTER])
        after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        trade_model = after_apps.get_model("simulated_trading", "SimulatedTradeModel")
        trade = trade_model._default_manager.get(pk=trade_id)
        assert trade.settlement_plan_binding_version == 0
        assert trade.settlement_plan_binding_payload is None
        assert trade.settlement_plan_binding_hash is None
        assert trade.settlement_exchange is None

        changed = (
            trade_model._base_manager.using(connection.alias)
            .filter(pk=trade_id)
            .update(**_synthetic_v2_fields(idempotency_key="migration-v2-reverse-guard"))
        )
        assert changed == 1
        with pytest.raises(IrreversibleError, match="retain them"):
            MigrationExecutor(connection).migrate([_BEFORE])

        preserved = trade_model._default_manager.get(pk=trade_id)
        assert preserved.settlement_plan_binding_version == 2
        assert preserved.settlement_exchange == "SSE"
        assert preserved.settlement_plan_binding_payload == _SYNTHETIC_PAYLOAD
        assert preserved.settlement_plan_binding_hash == "a" * 64
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
    finally:
        try:
            applied = MigrationRecorder(connection).applied_migrations()
            current_target = _AFTER if _AFTER in applied else _BEFORE
            if account_id is not None and trade_id is not None:
                current_apps = (
                    MigrationExecutor(connection).loader.project_state([current_target]).apps
                )
                trade_model = current_apps.get_model("simulated_trading", "SimulatedTradeModel")
                account_model = current_apps.get_model("simulated_trading", "SimulatedAccountModel")
                trade_model._base_manager.using(connection.alias).filter(pk=trade_id).delete()
                account_model._base_manager.using(connection.alias).filter(pk=account_id).delete()
        finally:
            MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Reverse migration guard lock behavior is verified on PostgreSQL.",
)
def test_0027_reverse_guard_blocks_v2_writer_until_outer_transaction_finishes() -> None:
    """The guard's ACCESS EXCLUSIVE lock prevents a writer racing the evidence check."""

    alias = connection.alias
    migration_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    account_id, trade_id, _ = _create_legacy_rows(migration_apps)
    trade_model = migration_apps.get_model("simulated_trading", "SimulatedTradeModel")
    migration = import_module(
        "apps.simulated_trading.migrations.0027_separate_settlement_exchange_identity"
    )
    try:
        with transaction.atomic(using=alias):
            with connections[alias].schema_editor(atomic=False) as schema_editor:
                migration.prevent_dropping_source_exchange_bindings(
                    migration_apps,
                    schema_editor,
                )
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(
                    _write_v2_binding,
                    alias=alias,
                    trade_model=trade_model,
                    trade_id=trade_id,
                    idempotency_key=f"migration-v2-lock-{uuid4()}",
                ).result(timeout=5)
            assert result == ("database_error", None, "55P03"), (
                "the reverse guard must hold ACCESS EXCLUSIVE through its outer transaction; "
                f"got {result!r}"
            )

        legacy_trade = trade_model._base_manager.using(alias).get(pk=trade_id)
        assert legacy_trade.settlement_plan_binding_version == 0
        assert legacy_trade.settlement_exchange is None
    finally:
        trade_model._base_manager.using(alias).filter(pk=trade_id).delete()
        migration_apps.get_model("simulated_trading", "SimulatedAccountModel")._base_manager.using(
            alias
        ).filter(pk=account_id).delete()


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Reverse migration transaction guard is PostgreSQL-specific.",
)
def test_0027_reverse_guard_rejects_non_atomic_schema_editor_without_mutation() -> None:
    """The guard rejects a PostgreSQL check that cannot hold its lock through DDL."""

    alias = connection.alias
    assert connection.in_atomic_block is False
    migration_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
    trade_model = migration_apps.get_model("simulated_trading", "SimulatedTradeModel")
    migration = import_module(
        "apps.simulated_trading.migrations.0027_separate_settlement_exchange_identity"
    )
    table_name = trade_model._meta.db_table
    rows_before = tuple(
        trade_model._base_manager.using(alias)
        .order_by("pk")
        .values_list("pk", "settlement_plan_binding_version", "settlement_exchange")
    )
    with connection.cursor() as cursor:
        columns_before = tuple(
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        )
    applied_before = _AFTER in MigrationRecorder(connection).applied_migrations()

    with connection.schema_editor(atomic=False) as schema_editor:
        assert connection.in_atomic_block is False
        with pytest.raises(IrreversibleError, match="outside a PostgreSQL transaction"):
            migration.prevent_dropping_source_exchange_bindings(migration_apps, schema_editor)

    rows_after = tuple(
        trade_model._base_manager.using(alias)
        .order_by("pk")
        .values_list("pk", "settlement_plan_binding_version", "settlement_exchange")
    )
    with connection.cursor() as cursor:
        columns_after = tuple(
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        )
    applied_after = _AFTER in MigrationRecorder(connection).applied_migrations()
    assert rows_after == rows_before
    assert columns_after == columns_before
    assert applied_after == applied_before
