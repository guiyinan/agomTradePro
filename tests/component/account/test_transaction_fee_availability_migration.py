"""Private historical-row fidelity test for Account migration 0067."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

_PARTIAL_APP_NAMES = ("django.contrib.auth", "django.contrib.contenttypes")
_BEFORE = ("account", "0066_account_authority_generation_lock")
_AFTER = ("account", "0067_transaction_fee_availability_flags")

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=list(_PARTIAL_APP_NAMES),
)


@pytest.fixture(autouse=True)
def _migration_executor_uses_full_app_registry(transactional_db: None) -> Iterator[None]:
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


def test_0067_preserves_legacy_fees_and_leaves_all_availability_unknown(
    django_db_use_migrations: bool,
) -> None:
    """Real historical rows keep money and execution time without inferred flags."""

    if not django_db_use_migrations:
        pytest.skip("Account fee migration proof requires a migrations-enabled test database")
    assert settings.AUTH_USER_MODEL == "auth.User"

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    assert _AFTER in executor.loader.graph.nodes

    username = f"fee-schema-{uuid4().hex}"
    portfolio_name = f"fee-schema-{uuid4().hex}"
    before_apps = None
    transaction_ids: list[int] = []

    try:
        executor.migrate([_BEFORE])
        executor = MigrationExecutor(connection)
        before_apps = executor.loader.project_state([_BEFORE]).apps
        User = before_apps.get_model("auth", "User")
        Portfolio = before_apps.get_model("account", "PortfolioModel")
        Transaction = before_apps.get_model("account", "TransactionModel")

        User._default_manager.bulk_create(
            [
                User(
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
            ]
        )
        user = User._default_manager.get(username=username)
        portfolio = Portfolio._default_manager.create(
            user_id=user.pk,
            name=portfolio_name,
        )

        expected_rows: dict[
            int,
            tuple[tuple[Decimal, Decimal, Decimal, Decimal], datetime],
        ] = {}
        examples = (
            (
                (Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")),
                datetime(2024, 3, 4, 1, 2, tzinfo=UTC),
                Decimal("0.01"),
                {"fees": {"commission": "0.00", "slippage": "0.00"}},
            ),
            (
                (Decimal("1.25"), Decimal("0.50"), Decimal("0.30"), Decimal("0.05")),
                datetime(2025, 7, 8, 9, 10, tzinfo=UTC),
                Decimal("2.10"),
                {
                    "fees": {
                        "commission": "1.25",
                        "slippage": "0.50",
                        "stamp_duty": "0.30",
                        "transfer_fee": "0.05",
                    }
                },
            ),
        )
        for index, (fees, traded_at, estimate, raw_payload) in enumerate(examples):
            record = Transaction._default_manager.create(
                portfolio_id=portfolio.pk,
                action="buy",
                asset_code=f"MIGRATION-{index}",
                shares=10.0,
                price=Decimal("12.3400"),
                notional=Decimal("123.40"),
                commission=fees[0],
                slippage=fees[1],
                stamp_duty=fees[2],
                transfer_fee=fees[3],
                estimated_cost=estimate,
                raw_payload=raw_payload,
                traded_at=traded_at,
                notes="fee availability migration fixture",
            )
            transaction_ids.append(record.pk)
            expected_rows[record.pk] = (fees, traded_at)

        executor = MigrationExecutor(connection)
        executor.migrate([_AFTER])
        after_apps = MigrationExecutor(connection).loader.project_state([_AFTER]).apps
        MigratedTransaction = after_apps.get_model("account", "TransactionModel")
        migrated_rows = {
            row.pk: row
            for row in MigratedTransaction._default_manager.filter(pk__in=transaction_ids)
        }

        assert set(migrated_rows) == set(expected_rows)
        for transaction_id, (expected_fees, expected_traded_at) in expected_rows.items():
            row = migrated_rows[transaction_id]
            assert (
                row.commission,
                row.slippage,
                row.stamp_duty,
                row.transfer_fee,
            ) == expected_fees
            assert row.traded_at == expected_traded_at
            assert (
                row.commission_known,
                row.slippage_known,
                row.stamp_duty_known,
                row.transfer_fee_known,
            ) == (None, None, None, None)
    finally:
        try:
            if before_apps is not None:
                Transaction = before_apps.get_model("account", "TransactionModel")
                Portfolio = before_apps.get_model("account", "PortfolioModel")
                User = before_apps.get_model("auth", "User")
                Transaction._default_manager.filter(pk__in=transaction_ids).delete()
                Portfolio._default_manager.filter(name=portfolio_name).delete()
                User._default_manager.filter(username=username).delete()
        finally:
            MigrationExecutor(connection).migrate(leaf_nodes)
