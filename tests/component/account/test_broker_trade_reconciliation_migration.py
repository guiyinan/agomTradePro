"""Native historical-row fidelity and reverse-safety tests for migration 0068."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.db import IntegrityError, connection
from django.db import transaction as db_transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.db.migrations.state import StateApps
from django.utils import timezone

_PARTIAL_APP_NAMES = ("django.contrib.auth", "django.contrib.contenttypes")
_BEFORE = ("account", "0067_transaction_fee_availability_flags")
_AFTER = ("account", "0068_broker_trade_reconciliation")

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=list(_PARTIAL_APP_NAMES),
)


@pytest.fixture(autouse=True)
def _migration_executor_uses_full_app_registry(
    transactional_db: None,
) -> Iterator[None]:
    """Temporarily expand pytest's partial flush registry for migration loading."""
    del transactional_db
    expected_partial_names = tuple(sorted(_PARTIAL_APP_NAMES))
    popped_layers: list[tuple[str, ...]] = []
    try:
        for _ in range(4):
            current_names = tuple(sorted(config.name for config in django_apps.get_app_configs()))
            if django_apps.is_installed("apps.account"):
                break
            assert current_names == expected_partial_names
            django_apps.unset_available_apps()
            popped_layers.append(current_names)
        assert django_apps.is_installed("apps.account")
        yield
    finally:
        for layer_names in reversed(popped_layers):
            django_apps.set_available_apps(layer_names)


def _seed_pre_0068_facts(
    migration_apps: StateApps,
    *,
    suffix: str,
) -> tuple[
    int,
    int,
    int,
    str,
    list[int],
    dict[int, dict[str, object]],
    dict[int, str],
]:
    """Create historical transaction rows covering each legacy broker marker."""
    UserModel: Any = migration_apps.get_model("auth", "User")
    PortfolioModel: Any = migration_apps.get_model("account", "PortfolioModel")
    TransactionModel: Any = migration_apps.get_model("account", "TransactionModel")
    BatchModel: Any = migration_apps.get_model("account", "BrokerTradeImportBatchModel")

    username = f"broker-recon-{suffix}"
    user = UserModel._default_manager.create(
        username=username,
        password="!",
        email="",
        first_name="",
        last_name="",
        is_staff=False,
        is_active=True,
        is_superuser=False,
        date_joined=datetime(2026, 10, 17, 0, 0, tzinfo=UTC),
    )
    portfolio = PortfolioModel._default_manager.create(
        user_id=user.pk,
        name=f"broker-recon-{suffix}",
    )
    batch_hash = f"{uuid4().hex}{uuid4().hex}"
    batch = BatchModel._default_manager.create(
        user_id=user.pk,
        portfolio_id=portfolio.pk,
        broker_name="legacy-broker",
        source_filename="legacy.csv",
        file_hash=batch_hash,
        status="completed",
        total_rows=1,
        imported_rows=1,
    )

    row_specs: tuple[tuple[str, str, str, str | None, int | None, str], ...] = (
        ("ordinary", "", "", None, None, "not_applicable"),
        ("batch-only", "legacy-broker", "", None, int(batch.pk), "legacy_unverified"),
        (
            "key-only",
            "legacy-broker",
            "",
            f"legacy-key-{suffix}",
            None,
            "legacy_unverified",
        ),
        (
            "external-id-only",
            "legacy-broker",
            f"legacy-external-{suffix}",
            None,
            None,
            "legacy_unverified",
        ),
    )
    snapshot_fields = (
        "position_id",
        "action",
        "asset_code",
        "shares",
        "price",
        "notional",
        "commission",
        "slippage",
        "stamp_duty",
        "transfer_fee",
        "commission_known",
        "slippage_known",
        "stamp_duty_known",
        "transfer_fee_known",
        "estimated_cost",
        "estimated_cost_ratio",
        "cost_variance",
        "cost_variance_pct",
        "traded_at",
        "notes",
        "broker_name",
        "external_trade_id",
        "broker_trade_key",
        "raw_payload",
        "import_batch_id",
        "created_at",
    )
    transaction_ids: list[int] = []
    expected_fields: dict[int, dict[str, object]] = {}
    expected_states: dict[int, str] = {}

    for index, (label, broker_name, external_id, trade_key, batch_id, state) in enumerate(
        row_specs
    ):
        shares = float(10 + index)
        price = Decimal("12.3400")
        notional = (price * Decimal(str(shares))).quantize(Decimal("0.01"))
        traded_at = datetime(
            2024 + index,
            3,
            4,
            1,
            2,
            3,
            456789,
            tzinfo=UTC,
        )
        record = TransactionModel._default_manager.create(
            portfolio_id=portfolio.pk,
            action="sell" if index == 3 else "buy",
            asset_code=f"OLD-{suffix[:6]}-{index}",
            shares=shares,
            price=price,
            notional=notional,
            commission=Decimal("1.25"),
            slippage=Decimal("0.50"),
            stamp_duty=Decimal("0.30"),
            transfer_fee=Decimal("0.05"),
            commission_known=True,
            slippage_known=False,
            stamp_duty_known=None,
            transfer_fee_known=True,
            estimated_cost=Decimal("2.10"),
            estimated_cost_ratio=0.017,
            cost_variance=Decimal("0.20"),
            cost_variance_pct=0.009,
            traded_at=traded_at,
            notes=f"historical fact {label}",
            broker_name=broker_name,
            external_trade_id=external_id,
            broker_trade_key=trade_key,
            raw_payload={"source_row": label, "source_amount": "12.3400"},
            import_batch_id=batch_id,
        )
        transaction_id = int(record.pk)
        transaction_ids.append(transaction_id)
        expected_fields[transaction_id] = {
            field_name: getattr(record, field_name) for field_name in snapshot_fields
        }
        expected_states[transaction_id] = state

    return (
        int(user.pk),
        int(portfolio.pk),
        int(batch.pk),
        batch_hash,
        transaction_ids,
        expected_fields,
        expected_states,
    )


def _assert_fact_snapshots(
    migration_apps: StateApps,
    *,
    transaction_ids: list[int],
    expected_fields: dict[int, dict[str, object]],
) -> None:
    """Compare existing economic, fee, clock, and broker metadata fields."""
    TransactionModel: Any = migration_apps.get_model("account", "TransactionModel")
    rows = {
        int(row.pk): row for row in TransactionModel._default_manager.filter(pk__in=transaction_ids)
    }
    assert set(rows) == set(transaction_ids)
    for transaction_id, expected in expected_fields.items():
        row = rows[transaction_id]
        actual = {field_name: getattr(row, field_name) for field_name in expected}
        assert actual == expected
        assert timezone.is_aware(row.traded_at)
        assert timezone.is_aware(row.created_at)


def _assert_migrated_rows(
    migration_apps: StateApps,
    *,
    transaction_ids: list[int],
    expected_fields: dict[int, dict[str, object]],
    expected_states: dict[int, str],
) -> None:
    """Assert migration defaults and legacy classifications without fact rewrites."""
    _assert_fact_snapshots(
        migration_apps,
        transaction_ids=transaction_ids,
        expected_fields=expected_fields,
    )
    TransactionModel: Any = migration_apps.get_model("account", "TransactionModel")
    rows = {
        int(row.pk): row for row in TransactionModel._default_manager.filter(pk__in=transaction_ids)
    }
    for transaction_id, expected_state in expected_states.items():
        row = rows[transaction_id]
        assert row.broker_reconciliation_state == expected_state
        assert row.broker_reconciliation_details == {}


def _transaction_columns() -> set[str]:
    """Return physical column names for the account transaction table."""
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, "transaction")
    return {column.name for column in description}


def _assert_after_schema_and_recorder() -> None:
    """Ensure a refused reverse leaves migration state and both columns intact."""
    assert _AFTER in MigrationRecorder(connection).applied_migrations()
    assert {
        "broker_reconciliation_state",
        "broker_reconciliation_details",
    } <= _transaction_columns()


def _cleanup_and_restore_leaf(
    *,
    leaf_nodes: list[tuple[str, str]],
    seeded: tuple[
        int,
        int,
        int,
        str,
        list[int],
        dict[int, dict[str, object]],
        dict[int, str],
    ],
) -> None:
    """Delete test rows using the active historical state and restore all leaves."""
    user_id, portfolio_id, batch_id, _, transaction_ids, _, _ = seeded
    try:
        applied = MigrationRecorder(connection).applied_migrations()
        target = _AFTER if _AFTER in applied else _BEFORE
        migration_apps = MigrationExecutor(connection).loader.project_state([target]).apps
        TransactionModel: Any = migration_apps.get_model("account", "TransactionModel")
        BatchModel: Any = migration_apps.get_model("account", "BrokerTradeImportBatchModel")
        PortfolioModel: Any = migration_apps.get_model("account", "PortfolioModel")
        UserModel: Any = migration_apps.get_model("auth", "User")
        TransactionModel._default_manager.filter(pk__in=transaction_ids).delete()
        BatchModel._default_manager.filter(pk=batch_id).delete()
        PortfolioModel._default_manager.filter(pk=portfolio_id).delete()
        UserModel._default_manager.filter(pk=user_id).delete()
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


def test_0068_classifies_legacy_rows_and_round_trips_without_rewriting_facts(
    django_db_use_migrations: bool,
) -> None:
    """Preserve legacy economics and clocks while classifying only broker facts."""
    if not django_db_use_migrations:
        pytest.skip("Broker reconciliation migration proof requires migrations-enabled database")
    if connection.vendor != "postgresql":
        pytest.skip("Broker reconciliation migration proof requires native PostgreSQL")
    assert settings.AUTH_USER_MODEL == "auth.User"

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    assert _AFTER in executor.loader.graph.nodes
    seeded = None
    try:
        executor.migrate([_BEFORE])
        before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
        seeded = _seed_pre_0068_facts(before_apps, suffix=uuid4().hex[:12])
        (
            user_id,
            portfolio_id,
            batch_id,
            batch_hash,
            transaction_ids,
            expected_fields,
            expected_states,
        ) = seeded

        executor = MigrationExecutor(connection)
        executor.migrate([_AFTER])
        after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        _assert_migrated_rows(
            after_apps,
            transaction_ids=transaction_ids,
            expected_fields=expected_fields,
            expected_states=expected_states,
        )
        assert _AFTER in MigrationRecorder(connection).applied_migrations()
        BatchModel: Any = after_apps.get_model("account", "BrokerTradeImportBatchModel")
        batch = BatchModel._default_manager.get(pk=batch_id)
        assert (batch.user_id, batch.portfolio_id, batch.file_hash, batch.status) == (
            user_id,
            portfolio_id,
            batch_hash,
            "completed",
        )

        TransactionModel: Any = after_apps.get_model("account", "TransactionModel")
        with pytest.raises(IntegrityError):
            with db_transaction.atomic():
                TransactionModel._default_manager.filter(pk=transaction_ids[0]).update(
                    broker_reconciliation_state="unknown",
                )
        assert (
            TransactionModel._default_manager.get(pk=transaction_ids[0]).broker_reconciliation_state
            == "not_applicable"
        )

        executor = MigrationExecutor(connection)
        executor.migrate([_BEFORE])
        assert _AFTER not in MigrationRecorder(connection).applied_migrations()
        assert "broker_reconciliation_state" not in _transaction_columns()
        assert "broker_reconciliation_details" not in _transaction_columns()
        before_round_trip_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
        _assert_fact_snapshots(
            before_round_trip_apps,
            transaction_ids=transaction_ids,
            expected_fields=expected_fields,
        )

        executor = MigrationExecutor(connection)
        executor.migrate([_AFTER])
        round_trip_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        _assert_migrated_rows(
            round_trip_apps,
            transaction_ids=transaction_ids,
            expected_fields=expected_fields,
            expected_states=expected_states,
        )
    finally:
        if seeded is None:
            MigrationExecutor(connection).migrate(leaf_nodes)
        else:
            _cleanup_and_restore_leaf(leaf_nodes=leaf_nodes, seeded=seeded)


def test_0068_refuses_reverse_for_business_states_and_nonempty_legacy_details(
    django_db_use_migrations: bool,
) -> None:
    """Keep schema and migration recorder intact for non-reconstructable state."""
    if not django_db_use_migrations:
        pytest.skip("Broker reconciliation migration proof requires migrations-enabled database")
    if connection.vendor != "postgresql":
        pytest.skip("Broker reconciliation reverse guard requires native PostgreSQL")
    assert settings.AUTH_USER_MODEL == "auth.User"

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    assert _AFTER in executor.loader.graph.nodes
    seeded = None
    try:
        executor.migrate([_BEFORE])
        before_apps = MigrationExecutor(connection).loader.project_state([_BEFORE]).apps
        seeded = _seed_pre_0068_facts(before_apps, suffix=uuid4().hex[:12])
        executor = MigrationExecutor(connection)
        executor.migrate([_AFTER])
        after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        TransactionModel: Any = after_apps.get_model("account", "TransactionModel")
        transaction_ids = seeded[4]
        refusal_cases = (
            ("awaiting_baseline", {}),
            ("projection_pending", {}),
            ("projection_blocked", {}),
            ("projected", {}),
            ("already_in_baseline", {}),
            ("legacy_unverified", {"review_note": "must remain inspectable"}),
        )

        for state, details in refusal_cases:
            transaction_id = transaction_ids[1]
            TransactionModel._default_manager.filter(pk=transaction_id).update(
                broker_reconciliation_state=state,
                broker_reconciliation_details=details,
            )
            with pytest.raises(
                IrreversibleError,
                match="Cannot remove broker reconciliation fields",
            ):
                MigrationExecutor(connection).migrate([_BEFORE])

            _assert_after_schema_and_recorder()
            row = TransactionModel._default_manager.get(pk=transaction_id)
            assert row.broker_reconciliation_state == state
            assert row.broker_reconciliation_details == details
    finally:
        if seeded is None:
            MigrationExecutor(connection).migrate(leaf_nodes)
        else:
            _cleanup_and_restore_leaf(leaf_nodes=leaf_nodes, seeded=seeded)
