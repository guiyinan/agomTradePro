"""Native checks for the current-reference binding version migration."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.db.migrations.state import StateApps

_PARTIAL_APP_NAMES = (
    "apps.simulated_trading",
    "django.contrib.auth",
    "django.contrib.contenttypes",
)
_BEFORE = ("simulated_trading", "0028_preserve_trade_execution_time")
_AFTER = ("simulated_trading", "0029_current_reference_plan_binding")
_V3_MARKER: dict[str, object] = {
    "schema": "test-only-v3-reverse-guard",
    "purpose": "migration guard marker; not a valid production receipt",
}

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=_PARTIAL_APP_NAMES,
)


@pytest.fixture(autouse=True)
def _full_app_registry_for_migration_loader(transactional_db: None) -> Iterator[None]:
    """Balance pytest app scopes while exposing migration dependencies."""

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


def _create_legacy_trade(apps: StateApps) -> tuple[int, int, tuple[object, ...]]:
    """Create one unbound historical trade and retain facts across 0029."""

    account_model = apps.get_model("simulated_trading", "SimulatedAccountModel")
    trade_model = apps.get_model("simulated_trading", "SimulatedTradeModel")
    account = account_model._default_manager.create(
        user=None,
        account_name="current-reference-migration-fixture",
        account_type="simulated",
        initial_capital=Decimal("1000.00"),
        current_cash=Decimal("1000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("1000.00"),
    )
    trade = trade_model._default_manager.create(
        account_id=account.pk,
        asset_code="TEST.CUR.OLD",
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
        execution_time=datetime(2026, 10, 16, 2, 0, tzinfo=UTC),
        status="executed",
    )
    facts: tuple[object, ...] = (
        trade.account_id,
        trade.asset_code,
        trade.quantity,
        trade.price,
        trade.total_cost,
        trade.execution_date,
        trade.execution_time,
        trade.created_at,
        trade.status,
        trade.settlement_plan_binding_version,
        trade.settlement_plan_binding_payload,
        trade.settlement_plan_binding_hash,
    )
    return int(account.pk), int(trade.pk), facts


def _v3_storage_marker() -> dict[str, object]:
    """Return DB-complete synthetic markers solely for the migration reverse guard."""

    digest = "a" * 64
    prefixed_digest = f"sha256:{digest}"
    return {
        "idempotency_key": "current-reference-migration-v3-guard",
        "request_payload_hash": digest,
        "fee_config_id": 1,
        "fee_schedule_hash": "b" * 64,
        "fee_schedule_snapshot": {"schema": "test-only"},
        "fee_precision_basis": "database_binary64",
        "fee_calculation_purpose": "normal_sim_estimated",
        "fee_rounding_policy": "component_half_even_cents_v1",
        "settlement_status": "pending",
        "settlement_release_date": date(2026, 10, 17),
        "settlement_security_id": "test-security",
        "settlement_market": "SH",
        "settlement_exchange": "SSE",
        "settlement_board": "MAIN",
        "settlement_market_session": date(2026, 10, 16),
        "settlement_lag_sessions": 1,
        "settlement_plan_binding_version": 3,
        "settlement_plan_binding_payload": dict(_V3_MARKER),
        "settlement_plan_binding_hash": "c" * 64,
        "settlement_bundle_id": "test-bundle",
        "settlement_bundle_version": "1",
        "settlement_bundle_hash": "d" * 64,
        "settlement_policy_id": "test-policy",
        "settlement_policy_version": "1",
        "settlement_policy_hash": "e" * 64,
        "execution_rule_v2_hash": "f" * 64,
        "settlement_calendar_snapshot_id": "00000000-0000-4000-8000-000000000001",
        "settlement_calendar_content_hash": prefixed_digest,
        "settlement_calendar_record_digest": f"sha256:{'1' * 64}",
        "settlement_calendar_publication_id": "test-publication",
        "settlement_calendar_publication_hash": "2" * 64,
        "settlement_calendar_policy_hash": "3" * 64,
        "settlement_calendar_evidence_hash": "4" * 64,
        "settlement_calendar_timezone": "Etc/UTC",
    }


def test_0029_preserves_legacy_facts_and_refuses_reverse_with_v3_row() -> None:
    """Keep old rows unchanged and prevent restoring the V0-V2-only check."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    alias = connection.alias
    account_id: int | None = None
    trade_id: int | None = None
    try:
        executor.migrate([_BEFORE])
        before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
        account_id, trade_id, original_facts = _create_legacy_trade(before_apps)

        MigrationExecutor(connection).migrate([_AFTER])
        after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        trade_model = after_apps.get_model("simulated_trading", "SimulatedTradeModel")
        migrated = trade_model._default_manager.using(alias).get(pk=trade_id)
        assert (
            migrated.account_id,
            migrated.asset_code,
            migrated.quantity,
            migrated.price,
            migrated.total_cost,
            migrated.execution_date,
            migrated.execution_time,
            migrated.created_at,
            migrated.status,
            migrated.settlement_plan_binding_version,
            migrated.settlement_plan_binding_payload,
            migrated.settlement_plan_binding_hash,
        ) == original_facts

        MigrationExecutor(connection).migrate([_BEFORE])
        reversed_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
        reversed_trade = (
            reversed_apps.get_model("simulated_trading", "SimulatedTradeModel")
            ._default_manager.using(alias)
            .get(pk=trade_id)
        )
        assert (
            reversed_trade.execution_time,
            reversed_trade.created_at,
            reversed_trade.settlement_plan_binding_version,
        ) == (original_facts[6], original_facts[7], 0)

        MigrationExecutor(connection).migrate([_AFTER])
        current_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        trade_model = current_apps.get_model("simulated_trading", "SimulatedTradeModel")
        reforwarded = trade_model._default_manager.using(alias).get(pk=trade_id)
        assert (
            reforwarded.account_id,
            reforwarded.asset_code,
            reforwarded.quantity,
            reforwarded.price,
            reforwarded.total_cost,
            reforwarded.execution_date,
            reforwarded.execution_time,
            reforwarded.created_at,
            reforwarded.status,
            reforwarded.settlement_plan_binding_version,
            reforwarded.settlement_plan_binding_payload,
            reforwarded.settlement_plan_binding_hash,
        ) == original_facts
        changed = (
            trade_model._base_manager.using(alias)
            .filter(pk=trade_id)
            .update(**_v3_storage_marker())
        )
        assert changed == 1
        with pytest.raises(IrreversibleError, match="retain it"):
            MigrationExecutor(connection).migrate([_BEFORE])

        preserved = trade_model._default_manager.using(alias).get(pk=trade_id)
        assert preserved.settlement_plan_binding_version == 3
        assert preserved.settlement_plan_binding_payload == _V3_MARKER
        assert preserved.settlement_plan_binding_hash == "c" * 64
        assert preserved.settlement_exchange == "SSE"
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
    finally:
        try:
            applied = MigrationRecorder(connection).applied_migrations()
            current_target = _AFTER if _AFTER in applied else _BEFORE
            if account_id is not None and trade_id is not None:
                current_apps = (
                    MigrationExecutor(connection).loader.project_state([current_target]).apps
                )
                current_trade_model = current_apps.get_model(
                    "simulated_trading", "SimulatedTradeModel"
                )
                current_account_model = current_apps.get_model(
                    "simulated_trading", "SimulatedAccountModel"
                )
                current_trade_model._base_manager.using(alias).filter(pk=trade_id).delete()
                current_account_model._base_manager.using(alias).filter(pk=account_id).delete()
        finally:
            MigrationExecutor(connection).migrate(leaf_nodes)
