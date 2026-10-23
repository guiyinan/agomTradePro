"""Exercise fee storage limits through the real settlement-bound UoW."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import connection, models

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import AS_OF as AS_OF
from tests.component.simulated_trading.test_execution_settlement_uow import _calendar as _calendar
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _execute_use_case as _execute_use_case,
)
from tests.component.simulated_trading.test_execution_settlement_uow import _intent as _intent
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _seed_fee_policy as _seed_fee_policy,
)
from tests.support.isolated_schema import isolated_schema
from tests.support.native_postgres_database import (  # noqa: F401
    native_postgres_test_database as _native_postgres_test_database_fixture,
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)

_FEE_STORAGE_ERROR_CODE = "SIMULATED_TRADE_FEE_STORAGE_INVALID"
_FEE_LIMIT = Decimal("100000000.00")
_MAX_STORED_FEE = Decimal("99999999.99")


@dataclass(frozen=True, slots=True)
class _FeeStorageCase:
    """Describe one synthetic exact-policy fee calculation at a field boundary."""

    name: str
    component: Literal["commission", "transfer_fee", "stamp_duty", "slippage"]
    side: SimulatedTradeSide
    quantity: Decimal
    price: Decimal
    initial_cash: Decimal
    market_value: Decimal
    minimum_commission: float = 1.0
    transfer_fee_rate: float = 0.00002
    stamp_duty_rate: float = 0.001
    slippage_rate: float = 0.001


_OVER_LIMIT_CASES: tuple[_FeeStorageCase, ...] = (
    _FeeStorageCase(
        name="commission",
        component="commission",
        side=SimulatedTradeSide.BUY,
        quantity=Decimal("100"),
        price=Decimal("10.00"),
        initial_cash=Decimal("300000000.00"),
        market_value=Decimal("0.00"),
        minimum_commission=100000000.00,
    ),
    _FeeStorageCase(
        name="transfer-fee",
        component="transfer_fee",
        side=SimulatedTradeSide.BUY,
        quantity=Decimal("100000"),
        price=Decimal("1000.00"),
        initial_cash=Decimal("500000000.00"),
        market_value=Decimal("0.00"),
        transfer_fee_rate=1.0,
    ),
    _FeeStorageCase(
        name="stamp-duty",
        component="stamp_duty",
        side=SimulatedTradeSide.SELL,
        quantity=Decimal("100000"),
        price=Decimal("1000.00"),
        initial_cash=Decimal("200000000.00"),
        market_value=Decimal("100000000.00"),
        stamp_duty_rate=1.0,
    ),
    _FeeStorageCase(
        name="slippage",
        component="slippage",
        side=SimulatedTradeSide.BUY,
        quantity=Decimal("100000"),
        price=Decimal("1000.00"),
        initial_cash=Decimal("500000000.00"),
        market_value=Decimal("0.00"),
        slippage_rate=1.0,
    ),
)

_MAXIMUM_CASE = _FeeStorageCase(
    name="maximum-commission",
    component="commission",
    side=SimulatedTradeSide.BUY,
    quantity=Decimal("1000"),
    price=Decimal("10.00"),
    initial_cash=Decimal("200000000.00"),
    market_value=Decimal("0.00"),
    minimum_commission=99999999.99,
)


@pytest.fixture
def fee_ledger(
    request: pytest.FixtureRequest,
    fee_case: _FeeStorageCase,
) -> Iterator[tuple[AbstractBaseUser, SimulatedAccountModel]]:
    """Create only the account, fee, and exact receipt tables used by this UoW test."""

    if connection.vendor == "postgresql":
        native_test_database = request.getfixturevalue("native_postgres_test_database")
        if (
            not isinstance(native_test_database, str)
            or connection.settings_dict["NAME"] != native_test_database
        ):
            raise RuntimeError("Native PostgreSQL test connection differs from TEST.NAME")
    elif connection.vendor != "sqlite":
        raise RuntimeError("Fee storage component tests require SQLite or PostgreSQL")

    user_model = get_user_model()
    model_types: tuple[type[models.Model], ...] = (
        user_model,
        AccountProfileModel,
        SimulatedAccountModel,
        PositionModel,
        SimulatedTradeModel,
        SimulatedOrderReservationModel,
        SimulatedOrderFillReceiptModel,
        FeeConfigModel,
    )
    with isolated_schema(model_types):
        user = user_model.objects.create_user(
            username=f"fee-storage-{fee_case.name}",
            password="unused",
        )
        account = SimulatedAccountModel.objects.create(
            user=user,
            account_name=f"fee-storage-{fee_case.name}",
            account_type="simulated",
            initial_capital=fee_case.initial_cash,
            current_cash=fee_case.initial_cash,
            current_market_value=fee_case.market_value,
            total_value=fee_case.initial_cash + fee_case.market_value,
            is_active=True,
        )
        if fee_case.side is SimulatedTradeSide.SELL:
            trade_value = fee_case.quantity * fee_case.price
            PositionModel.objects.create(
                account=account,
                asset_code="600000.SH",
                asset_name="Synthetic fee-boundary security",
                asset_type="equity",
                quantity=fee_case.quantity,
                available_quantity=fee_case.quantity,
                avg_cost=fee_case.price,
                total_cost=trade_value,
                cost_basis_known=True,
                current_price=fee_case.price,
                market_value=trade_value,
                valuation_known=True,
                unrealized_pnl=Decimal("0.00"),
                unrealized_pnl_pct=0.0,
                first_buy_date=date(2026, 10, 1),
            )
        fee_row = FeeConfigModel.objects.create(
            config_name=f"fee-storage-{fee_case.name}",
            asset_type="equity",
            commission_rate_buy=0.0003,
            commission_rate_sell=0.0003,
            min_commission=fee_case.minimum_commission,
            stamp_duty_rate=fee_case.stamp_duty_rate,
            transfer_fee_rate=fee_case.transfer_fee_rate,
            min_transfer_fee=0.0,
            slippage_rate=fee_case.slippage_rate,
            is_default=False,
            is_active=False,
        )
        _seed_fee_policy(fee_row)
        yield user, account


def _rows_for_account(
    model_type: type[models.Model],
    *,
    account_id: int,
    scope_column: str,
) -> tuple[tuple[object, ...], ...]:
    """Read raw database values to avoid SQLite DecimalField conversion masking writes."""

    quote = connection.ops.quote_name
    table_name = quote(model_type._meta.db_table)
    columns = tuple(quote(field.column) for field in model_type._meta.concrete_fields)
    primary_key = quote(model_type._meta.pk.column)
    statement = (
        f"SELECT {', '.join(columns)} FROM {table_name} "
        f"WHERE {quote(scope_column)} = %s ORDER BY {primary_key}"
    )
    with connection.cursor() as cursor:
        cursor.execute(statement, (account_id,))
        return tuple(tuple(row) for row in cursor.fetchall())


def _receipt_rows_for_account(account_id: int) -> tuple[tuple[object, ...], ...]:
    """Read receipt rows through their protected reservation account scope."""

    quote = connection.ops.quote_name
    receipt_table = quote(SimulatedOrderFillReceiptModel._meta.db_table)
    reservation_table = quote(SimulatedOrderReservationModel._meta.db_table)
    columns = tuple(
        f"receipt.{quote(field.column)}"
        for field in SimulatedOrderFillReceiptModel._meta.concrete_fields
    )
    receipt_key = quote(SimulatedOrderFillReceiptModel._meta.pk.column)
    reservation_key = quote(SimulatedOrderReservationModel._meta.pk.column)
    statement = (
        f"SELECT {', '.join(columns)} FROM {receipt_table} AS receipt "
        f"JOIN {reservation_table} AS reservation "
        f"ON receipt.{quote('reservation_id')} = reservation.{reservation_key} "
        f"WHERE reservation.{quote('account_id')} = %s "
        f"ORDER BY receipt.{receipt_key}"
    )
    with connection.cursor() as cursor:
        cursor.execute(statement, (account_id,))
        return tuple(tuple(row) for row in cursor.fetchall())


def _financial_snapshot(account_id: int) -> tuple[tuple[tuple[object, ...], ...], ...]:
    """Capture all account-scoped rows affected by the settlement transaction."""

    return (
        _rows_for_account(
            SimulatedAccountModel,
            account_id=account_id,
            scope_column=SimulatedAccountModel._meta.pk.column,
        ),
        _rows_for_account(
            PositionModel,
            account_id=account_id,
            scope_column="account_id",
        ),
        _rows_for_account(
            SimulatedTradeModel,
            account_id=account_id,
            scope_column="account_id",
        ),
        _rows_for_account(
            SimulatedOrderReservationModel,
            account_id=account_id,
            scope_column="account_id",
        ),
        _receipt_rows_for_account(account_id),
    )


def _build_use_case(
    account_id: int,
    user_id: int,
) -> ExecuteSettlementBoundSimulatedTradeUseCase:
    """Build the public use case with test-owned source and calendar evidence."""

    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
    )
    use_case, _, _ = _execute_use_case(
        account_id=account_id,
        user_id=user_id,
        as_of=AS_OF,
        evidence=evidence,
    )
    return use_case


def _calculated_component(
    case: _FeeStorageCase,
    *,
    user_id: int,
    account_id: int,
) -> Decimal:
    """Return one real V2 fee component before invoking the UoW writer."""

    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    policy = repository.get_execution_fee_policy(
        account_id=account_id,
        user_id=user_id,
        asset_type="equity",
        market="SH",
        board="MAIN",
        side=case.side,
        as_of=AS_OF,
    )
    assert policy is not None
    fees = policy.calculate_for(
        asset_type="equity",
        market="SH",
        board="MAIN",
        side=case.side,
        amount=case.quantity * case.price,
        as_of=AS_OF,
    )
    components: dict[str, Decimal] = {
        "commission": fees.commission,
        "transfer_fee": fees.transfer_fee,
        "stamp_duty": fees.stamp_duty,
        "slippage": fees.slippage,
    }
    return components[case.component]


@pytest.mark.parametrize("fee_case", _OVER_LIMIT_CASES, ids=lambda case: case.name)
def test_over_limit_fee_components_block_without_any_account_writes(
    fee_case: _FeeStorageCase,
    fee_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
) -> None:
    """Reject each real V2 component over its field limit and preserve the ledger."""

    user, account = fee_ledger
    assert isinstance(user.pk, int)
    assert isinstance(account.pk, int)
    assert (
        _calculated_component(
            fee_case,
            user_id=user.pk,
            account_id=account.pk,
        )
        == _FEE_LIMIT
    )
    use_case = _build_use_case(account.pk, user.pk)
    intent = _intent(
        user_id=user.pk,
        account_id=account.pk,
        side=fee_case.side,
        key=f"fee-storage-{fee_case.name}",
        quantity=fee_case.quantity,
        price=fee_case.price,
    )
    before = _financial_snapshot(account.pk)

    for _ in range(2):
        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            use_case.execute(intent)
        assert blocked.value.code == _FEE_STORAGE_ERROR_CODE
        assert _financial_snapshot(account.pk) == before


@pytest.mark.parametrize("fee_case", (_OVER_LIMIT_CASES[1],), ids=["transfer-fee"])
def test_blocked_fee_rolls_back_due_pending_settlement_release_and_retry(
    fee_case: _FeeStorageCase,
    fee_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
) -> None:
    """A fee block rolls back an earlier due release on both durable attempts."""

    user, account = fee_ledger
    assert isinstance(user.pk, int)
    assert isinstance(account.pk, int)

    seed_use_case = _build_use_case(account.pk, user.pk)
    seed_receipt = seed_use_case.execute(
        _intent(
            user_id=user.pk,
            account_id=account.pk,
            key="fee-storage-pending-release-seed",
            quantity=Decimal("1"),
            price=Decimal("10.00"),
        )
    )
    pending_trade = SimulatedTradeModel.objects.get(pk=seed_receipt.trade_id)
    position = PositionModel.objects.get(account=account, asset_code="600000.SH")
    release_time = AS_OF + timedelta(days=5)
    release_evidence = _calendar(
        as_of=release_time,
        open_dates={
            date(2026, 10, 16),
            date(2026, 10, 19),
            date(2026, 10, 20),
            date(2026, 10, 21),
            date(2026, 10, 22),
            date(2026, 10, 23),
        },
        end=date(2026, 10, 23),
    )
    assert pending_trade.settlement_status == "pending"
    assert pending_trade.settlement_release_date is not None
    assert pending_trade.settlement_release_date <= release_evidence.current_open_session(
        release_time
    )
    assert position.available_quantity == Decimal("0.000000")

    assert (
        _calculated_component(
            fee_case,
            user_id=user.pk,
            account_id=account.pk,
        )
        == _FEE_LIMIT
    )

    use_case, _, _ = _execute_use_case(
        account_id=account.pk,
        user_id=user.pk,
        as_of=release_time,
        evidence=release_evidence,
    )
    intent = _intent(
        user_id=user.pk,
        account_id=account.pk,
        side=fee_case.side,
        key="fee-storage-pending-release-block",
        quantity=fee_case.quantity,
        price=fee_case.price,
    )
    before = _financial_snapshot(account.pk)

    for _ in range(2):
        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            use_case.execute(intent)
        assert blocked.value.code == _FEE_STORAGE_ERROR_CODE
        assert _financial_snapshot(account.pk) == before

    pending_trade.refresh_from_db()
    position.refresh_from_db()
    assert pending_trade.settlement_status == "pending"
    assert pending_trade.settlement_released_at is None
    assert position.available_quantity == Decimal("0.000000")


@pytest.mark.parametrize("fee_case", (_MAXIMUM_CASE,), ids=lambda case: case.name)
def test_maximum_storable_fee_executes_and_exact_replay_adds_no_rows(
    fee_case: _FeeStorageCase,
    fee_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
) -> None:
    """Allow the exact 10-digit upper fee and preserve ordinary idempotent replay."""

    user, account = fee_ledger
    assert isinstance(user.pk, int)
    assert isinstance(account.pk, int)
    assert (
        _calculated_component(
            fee_case,
            user_id=user.pk,
            account_id=account.pk,
        )
        == _MAX_STORED_FEE
    )
    use_case = _build_use_case(account.pk, user.pk)
    intent = _intent(
        user_id=user.pk,
        account_id=account.pk,
        key="fee-storage-maximum-commission",
        quantity=fee_case.quantity,
        price=fee_case.price,
    )

    first = use_case.execute(intent)
    trade = SimulatedTradeModel.objects.get(pk=first.trade_id)
    assert trade.commission == _MAX_STORED_FEE
    after_first = _financial_snapshot(account.pk)

    replay = use_case.execute(intent)
    assert replay.trade_id == first.trade_id
    assert replay.replayed is True
    assert _financial_snapshot(account.pk) == after_first


@pytest.mark.parametrize("fee_case", (_MAXIMUM_CASE,), ids=lambda case: case.name)
def test_storable_fee_with_unrepresentable_average_cost_blocks_without_writes(
    fee_case: _FeeStorageCase,
    fee_ledger: tuple[AbstractBaseUser, SimulatedAccountModel],
) -> None:
    """A storable commission does not bypass the separate ledger price bound."""

    user, account = fee_ledger
    assert isinstance(user.pk, int)
    assert isinstance(account.pk, int)
    assert (
        _calculated_component(
            fee_case,
            user_id=user.pk,
            account_id=account.pk,
        )
        == _MAX_STORED_FEE
    )
    use_case = _build_use_case(account.pk, user.pk)
    intent = _intent(
        user_id=user.pk,
        account_id=account.pk,
        key="fee-storage-average-cost-bound",
        quantity=Decimal("100"),
        price=fee_case.price,
    )
    before = _financial_snapshot(account.pk)

    for _ in range(2):
        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            use_case.execute(intent)
        assert blocked.value.code == "SIMULATED_TRADE_EXECUTION_BLOCKED"
        assert _financial_snapshot(account.pk) == before
