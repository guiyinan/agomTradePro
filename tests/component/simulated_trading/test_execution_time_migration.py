"""Native migration regression for source execution timestamps."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from datetime import timezone as datetime_timezone
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

_PARTIAL_APP_NAMES = (
    "apps.simulated_trading",
    "django.contrib.auth",
    "django.contrib.contenttypes",
)
_BEFORE = ("simulated_trading", "0027_separate_settlement_exchange_identity")
_AFTER = ("simulated_trading", "0028_preserve_trade_execution_time")

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


def _create_account(account_model: Any) -> int:
    """Create the minimum account row required by the historical model state."""

    account = account_model._default_manager.create(
        user=None,
        account_name="execution-time-migration-fixture",
        account_type="simulated",
        initial_capital="1000.00",
        current_cash="1000.00",
        current_market_value="0.00",
        total_value="1000.00",
    )
    return int(account.pk)


def _create_trade(
    trade_model: Any,
    *,
    account_id: int,
    asset_code: str,
    execution_time: datetime | None = None,
) -> int:
    """Create a complete historical trade, optionally supplying its source time."""

    values: dict[str, Any] = {
        "account_id": account_id,
        "asset_code": asset_code,
        "asset_name": "Migration timestamp fixture",
        "asset_type": "equity",
        "action": "buy",
        "quantity": "1.000000",
        "price": "10.0000",
        "amount": "10.00",
        "commission": "0.00",
        "slippage": "0.00",
        "total_cost": "10.00",
        "order_date": date(2026, 10, 16),
        "execution_date": date(2026, 10, 16),
        "status": "executed",
    }
    if execution_time is not None:
        values["execution_time"] = execution_time
    trade = trade_model._default_manager.create(**values)
    return int(trade.pk)


def _trade_facts(
    trade_model: Any,
    trade_ids: tuple[int, ...],
) -> tuple[tuple[int, Any, Any], ...]:
    """Return the persisted execution and creation instants for the fixture rows."""

    return tuple(
        trade_model._base_manager.using(connection.alias)
        .filter(pk__in=trade_ids)
        .order_by("pk")
        .values_list("pk", "execution_time", "created_at")
    )


def test_0028_execution_time_roundtrip_preserves_source_and_creation_instants() -> None:
    """The field change preserves old rows and honors supplied/default timestamps."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    account_id: int | None = None
    trade_ids: list[int] = []
    try:
        executor.migrate([_BEFORE])
        before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
        account_model = before_apps.get_model("simulated_trading", "SimulatedAccountModel")
        old_trade_model = before_apps.get_model("simulated_trading", "SimulatedTradeModel")
        old_execution_field = old_trade_model._meta.get_field("execution_time")
        assert old_execution_field.auto_now_add is True
        assert old_execution_field.editable is False
        assert old_execution_field.blank is True
        assert old_trade_model._meta.get_field("created_at").auto_now_add is True

        account_id = _create_account(account_model)
        legacy_id = _create_trade(
            old_trade_model,
            account_id=account_id,
            asset_code="MIGTIMELEG",
        )
        trade_ids.append(legacy_id)
        legacy_execution_time = datetime(
            2026,
            10,
            15,
            9,
            30,
            12,
            345678,
            tzinfo=datetime_timezone(timedelta(hours=8)),
        )
        legacy_created_at = datetime(
            2026,
            10,
            17,
            1,
            2,
            3,
            456789,
            tzinfo=UTC,
        )
        old_trade_model._base_manager.using(connection.alias).filter(pk=legacy_id).update(
            execution_time=legacy_execution_time,
            created_at=legacy_created_at,
        )
        original_legacy_facts = _trade_facts(old_trade_model, (legacy_id,))

        MigrationExecutor(connection).migrate([_AFTER])
        after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        new_trade_model = after_apps.get_model("simulated_trading", "SimulatedTradeModel")
        execution_field = new_trade_model._meta.get_field("execution_time")
        assert execution_field.auto_now_add is False
        assert execution_field.has_default() is True
        assert execution_field.editable is False
        assert execution_field.blank is True
        assert new_trade_model._meta.get_field("created_at").auto_now_add is True
        assert _trade_facts(new_trade_model, (legacy_id,)) == original_legacy_facts

        explicit_execution_time = datetime(
            2024,
            3,
            5,
            9,
            8,
            7,
            654321,
            tzinfo=datetime_timezone(timedelta(hours=8)),
        )
        explicit_created_start = timezone.now()
        explicit_id = _create_trade(
            new_trade_model,
            account_id=account_id,
            asset_code="MIGTIMEEXP",
            execution_time=explicit_execution_time,
        )
        explicit_created_end = timezone.now()
        trade_ids.append(explicit_id)
        explicit_trade = new_trade_model._default_manager.get(pk=explicit_id)
        assert explicit_trade.execution_time == explicit_execution_time
        assert explicit_created_start <= explicit_trade.created_at <= explicit_created_end

        omitted_execution_start = timezone.now()
        omitted_id = _create_trade(
            new_trade_model,
            account_id=account_id,
            asset_code="MIGTIMEOMT",
        )
        omitted_execution_end = timezone.now()
        trade_ids.append(omitted_id)
        omitted_trade = new_trade_model._default_manager.get(pk=omitted_id)
        assert omitted_execution_start <= omitted_trade.execution_time <= omitted_execution_end
        assert omitted_execution_start <= omitted_trade.created_at <= omitted_execution_end

        expected_facts = _trade_facts(new_trade_model, tuple(trade_ids))

        MigrationExecutor(connection).migrate([_BEFORE])
        reversed_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
        reversed_trade_model = reversed_apps.get_model(
            "simulated_trading",
            "SimulatedTradeModel",
        )
        assert _trade_facts(reversed_trade_model, tuple(trade_ids)) == expected_facts

        MigrationExecutor(connection).migrate([_AFTER])
        final_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        final_trade_model = final_apps.get_model("simulated_trading", "SimulatedTradeModel")
        assert _trade_facts(final_trade_model, tuple(trade_ids)) == expected_facts
    finally:
        try:
            applied = MigrationRecorder(connection).applied_migrations()
            current_target = _AFTER if _AFTER in applied else _BEFORE
            if account_id is not None:
                current_apps = (
                    MigrationExecutor(connection).loader.project_state([current_target]).apps
                )
                current_trade_model = current_apps.get_model(
                    "simulated_trading",
                    "SimulatedTradeModel",
                )
                current_account_model = current_apps.get_model(
                    "simulated_trading",
                    "SimulatedAccountModel",
                )
                if trade_ids:
                    current_trade_model._base_manager.using(connection.alias).filter(
                        pk__in=trade_ids
                    ).delete()
                current_account_model._base_manager.using(connection.alias).filter(
                    pk=account_id
                ).delete()
        finally:
            MigrationExecutor(connection).migrate(leaf_nodes)
