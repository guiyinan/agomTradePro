"""ORM regressions for the ordinary UoW's retained V4 history guard.

The fixtures create persisted reservation/receipt/Trade rows through the real
component repositories. They do not enable a source adapter or qualify market
prices beyond the existing ordinary V3 contract.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, models, transaction

from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    ReleaseDueSimulatedSettlementsUseCase,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.order_reservation import (
    CancelSimulatedOrderReservationUseCase,
    ReserveSimulatedOrderUseCase,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionCalendarEvidence,
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.domain.order_reservation import OrderReservationStatus
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.simulated_trading import test_execution_settlement_uow as settlement_uow_tests
from tests.component.simulated_trading import (
    test_order_reservation_concurrency as reservation_concurrency,
)
from tests.component.simulated_trading import (
    test_order_reservation_fill_row_reader as row_reader_tests,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _calendar,
    _CalendarReader,
    _Clock,
    _IdentityReader,
    _intent,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _account_financial_state,
    _EventReader,
    _FixedClock,
    _invoke,
    _ledger_counts,
    _set_consistent_account_mark,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _READ_CUTOFF,
    _Rows,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _bundle_for_security,
    _create_position,
    _Harness,
    _intent_for,
    _SecurityScopedRuleReader,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


@dataclass(frozen=True, slots=True)
class _PersistedV4History:
    """Keep the actual completed V4 parent, receipt, and Trade rows together."""

    rows: _Rows
    reservation: SimulatedOrderReservationModel
    receipt: SimulatedOrderFillReceiptModel
    trade: SimulatedTradeModel


class _CurrentReferenceIdentityReader:
    """Return one exact, current-purpose V2 identity for ordinary UoW tests."""

    def __init__(self, evidence: ExecutionInstrumentIdentityEvidenceV2) -> None:
        self.evidence = evidence
        self.reads = 0

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2:
        """Return the V2 receipt only for its exact instrument and selected cutoff."""

        self.reads += 1
        if (
            security_id != self.evidence.security_id
            or asset_code != self.evidence.asset_code
            or as_of != self.evidence.selection.selected_at
        ):
            raise AssertionError("V2 fixture identity was requested outside its exact scope")
        return self.evidence


def _history_harness(
    base: _Harness,
    *,
    security_id: str,
) -> _Harness:
    """Compose a real reservation journey for one test-owned instrument ID."""

    bundle: ExecutionSettlementBundleV3 = _bundle_for_security(security_id)
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
    )
    execution_repository = DjangoSimulatedTradeExecutionRepository(using="default")
    preparer = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_SecurityScopedRuleReader(bundle),
        identity_reader=_IdentityReader(),
        calendar_reader=_CalendarReader(evidence),
        fee_policy_reader=execution_repository,
        repository=execution_repository,
        clock=_Clock(AS_OF),
    )
    reservation_repository = DjangoSimulatedOrderReservationRepository(using="default")
    return replace(
        base,
        repository=reservation_repository,
        preparer=preparer,
        reserve=ReserveSimulatedOrderUseCase(
            preparer=preparer,
            repository=reservation_repository,
            clock=_Clock(AS_OF),
        ),
        rule_reader=_SecurityScopedRuleReader(bundle),
    )


def _rows_for_instrument(
    base: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    *,
    security_id: str,
    asset_code: str,
) -> tuple[_Harness, _Rows]:
    """Build one ordinary sealed reservation with a test-owned exact identity."""

    harness = _history_harness(base, security_id=security_id)

    def intent_for_instrument(
        target: _Harness,
        *,
        side: SimulatedTradeSide,
        key: str,
    ) -> SimulatedTradeIntent:
        """Bind the existing fixture builder to this call's explicit identity."""

        return _intent_for(
            target,
            side=side,
            key=key,
            security_id=security_id,
            asset_code=asset_code,
        )

    with monkeypatch.context() as patch:
        patch.setattr(row_reader_tests, "_intent_for", intent_for_instrument)
        rows = row_reader_tests._reader_rows(harness)
    return harness, rows


def _persist_terminal_v4_history(
    base: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    *,
    security_id: str,
    asset_code: str,
) -> _PersistedV4History:
    """Persist a completed V4 chain through the actual source/economics writer."""

    harness, rows = _rows_for_instrument(
        base,
        monkeypatch,
        security_id=security_id,
        asset_code=asset_code,
    )
    _create_position(harness.account, asset_code=asset_code)
    harness.account.refresh_from_db()
    known_market_value = sum(
        PositionModel.objects.filter(account=harness.account).values_list(
            "market_value", flat=True
        ),
        Decimal("0.00"),
    )
    _set_consistent_account_mark(harness.account, market_value=known_market_value)

    final_event = replace(
        rows.event,
        event_kind=LocalSimulatedFillEventKind.FINAL_FILL,
        quantity=Decimal("100.000000"),
        event_payload_hash="f" * 64,
    )
    event_reader = _EventReader(final_event, [])
    fill_repository = DjangoSimulatedOrderFillRepository(
        event_reader=event_reader,
        using="default",
    )
    result = _invoke(
        fill_repository,
        final_event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )
    assert result.replayed is False
    reservation = SimulatedOrderReservationModel.objects.get(pk=rows.reservation.pk)
    assert reservation.status == SimulatedOrderReservationModel.STATUS_COMPLETED
    receipt = SimulatedOrderFillReceiptModel.objects.get(reservation=reservation)
    trade = SimulatedTradeModel.objects.get(pk=result.trade_id)
    return _PersistedV4History(
        rows=rows,
        reservation=reservation,
        receipt=receipt,
        trade=trade,
    )


def _release_v4_history(
    history: _PersistedV4History,
    *,
    as_of: datetime,
) -> int:
    """Release due shares through the public calendar-validated use case."""

    evidence = _calendar(
        as_of=as_of,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)},
        start=date(2026, 10, 16),
        end=date(2026, 10, 23),
    )
    account = history.reservation.account
    assert type(history.reservation.account_id) is int
    assert type(account.user_id) is int
    use_case = ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=_CalendarReader(evidence),
        repository=DjangoSimulatedTradeExecutionRepository(using="default"),
        clock=_FixedClock(as_of),
    )
    return use_case.execute(
        account_id=history.reservation.account_id,
        user_id=account.user_id,
        asset_code=history.rows.event.asset_code,
        exchange=history.rows.proof.settlement_exchange,
    )


def _other_owner_harness(base: _Harness, *, suffix: str) -> _Harness:
    """Create a separate simulated account while reusing real test adapters."""

    user = get_user_model().objects.create_user(
        username=f"w2b-v4-history-{suffix}",
        password="unused",
    )
    assert type(user.pk) is int
    account = SimulatedAccountModel.objects.create(
        user=user,
        account_name=f"w2b-v4-history-{suffix}",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
        is_active=True,
    )
    assert type(account.pk) is int
    return replace(base, account=account, user_id=user.pk)


def _cross_account_receipt_locator(
    base: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    *,
    foreign_locator: str,
) -> tuple[_PersistedV4History, _PersistedV4History, SimulatedOrderFillReceiptModel]:
    """Create real V4 histories, then corrupt exactly one Receipt FK scope."""

    local_history = _persist_terminal_v4_history(
        base,
        monkeypatch,
        security_id="SH.LOCAL.HISTORY.SECURITY",
        asset_code="000001.SH",
    )
    foreign_base = _other_owner_harness(base, suffix=foreign_locator)
    foreign_history = _persist_terminal_v4_history(
        foreign_base,
        monkeypatch,
        security_id="SH.FOREIGN.HISTORY.SECURITY",
        asset_code="000002.SH",
    )
    # The one-to-one Trade relation requires removing the foreign chain's
    # Receipt before the local row can be pointed at its Trade. Both references
    # are intentionally left damaged for the account-wide validator to find.
    models.QuerySet.delete(
        SimulatedOrderFillReceiptModel._base_manager.filter(
            pk=foreign_history.receipt.pk,
        )
    )
    if foreign_locator == "reservation":
        foreign_id = foreign_history.reservation.pk
        field = "reservation_id"
    elif foreign_locator == "trade":
        foreign_id = foreign_history.trade.pk
        field = "trade_id"
    else:
        raise ValueError("unsupported cross-account Receipt locator")
    assert type(foreign_id) is int
    models.QuerySet.update(
        SimulatedOrderFillReceiptModel._base_manager.filter(
            pk=local_history.receipt.pk,
        ),
        **{field: foreign_id},
    )
    damaged_receipt = SimulatedOrderFillReceiptModel._base_manager.get(
        pk=local_history.receipt.pk,
    )
    return local_history, foreign_history, damaged_receipt


def _receipt_locator_state() -> tuple[tuple[int, int, int, str], ...]:
    """Capture every Receipt FK pair and seal for exact no-write assertions."""

    raw_rows = list(
        SimulatedOrderFillReceiptModel._base_manager.order_by("pk").values_list(
            "pk",
            "reservation_id",
            "trade_id",
            "receipt_hash",
        )
    )
    rows: list[tuple[int, int, int, str]] = []
    for row in raw_rows:
        assert type(row) is tuple and len(row) == 4
        receipt_id, reservation_id, trade_id, receipt_hash = cast(
            tuple[object, object, object, object],
            row,
        )
        assert type(receipt_id) is int
        assert type(reservation_id) is int
        assert type(trade_id) is int
        assert type(receipt_hash) is str
        rows.append((receipt_id, reservation_id, trade_id, receipt_hash))
    return tuple(rows)


def _ordinary_use_case_with_reader(
    account: SimulatedAccountModel,
    *,
    as_of: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ExecuteSettlementBoundSimulatedTradeUseCase, _CurrentReferenceIdentityReader]:
    """Compose ordinary V3 execution with the existing typed current-reference fixture."""

    assert type(account.pk) is int
    assert type(account.user_id) is int
    identity_intent = _intent(
        user_id=account.user_id,
        account_id=account.pk,
        key="ordinary-v3-current-reference-identity-fixture",
    )
    bundle = _bundle_for_security(identity_intent.security_id)
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    open_dates = {
        date(2026, 10, 16),
        date(2026, 10, 19),
        date(2026, 10, 20),
        date(2026, 10, 21),
        date(2026, 10, 22),
        date(2026, 10, 23),
    }
    calendar_evidence = _calendar(
        as_of=as_of,
        open_dates=open_dates,
        exchange="SH",
        end=date(2026, 10, 23),
    )

    def calendar_with_future_sessions(
        *,
        as_of: datetime,
        open_dates: set[date],
        exchange: str = "SH",
        start: date = date(2026, 10, 16),
        end: date = date(2026, 10, 21),
    ) -> ExecutionCalendarEvidence:
        """Give the existing V3 identity fixture the same complete open-session range."""

        del end
        return _calendar(
            as_of=as_of,
            open_dates=open_dates | {date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)},
            exchange=exchange,
            start=start,
            end=date(2026, 10, 23),
        )

    with monkeypatch.context() as patch:
        patch.setattr(settlement_uow_tests, "_calendar", calendar_with_future_sessions)
        _, _, identity = settlement_uow_tests._current_v3_plan(
            repository=repository,
            intent=identity_intent,
            as_of=as_of,
            source_exchange="SH",
            bundle=bundle,
        )
    identity.validate_for(intent=identity_intent, as_of=as_of)
    identity_reader = _CurrentReferenceIdentityReader(identity)
    use_case = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_SecurityScopedRuleReader(bundle),
        identity_reader=identity_reader,
        calendar_reader=_CalendarReader(calendar_evidence),
        fee_policy_reader=repository,
        repository=repository,
        clock=_Clock(as_of),
    )
    return use_case, identity_reader


def _ordinary_use_case(
    account: SimulatedAccountModel,
    *,
    monkeypatch: pytest.MonkeyPatch,
    as_of: datetime = AS_OF,
) -> ExecuteSettlementBoundSimulatedTradeUseCase:
    """Return the ordinary use case with a typed V2 identity reader."""

    return _ordinary_use_case_with_reader(
        account,
        as_of=as_of,
        monkeypatch=monkeypatch,
    )[0]


def _ordinary_use_case_at(
    account: SimulatedAccountModel,
    *,
    as_of: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> ExecuteSettlementBoundSimulatedTradeUseCase:
    """Return the ordinary V3 use case with calendar coverage for later fills."""

    return _ordinary_use_case(
        account,
        as_of=as_of,
        monkeypatch=monkeypatch,
    )


def _account_state(account: SimulatedAccountModel) -> tuple[object, ...]:
    """Capture rows and financial counters around a rejected new execution."""

    return (
        _ledger_counts(account),
        _account_financial_state(account),
        tuple(
            PositionModel.objects.filter(account=account)
            .order_by("asset_code")
            .values_list(
                "asset_code",
                "quantity",
                "available_quantity",
                "total_cost",
                "market_value",
                "current_price",
            )
        ),
        tuple(
            SimulatedOrderReservationModel.objects.filter(account=account)
            .order_by("pk")
            .values_list(
                "pk",
                "status",
                "filled_quantity",
                "cash_consumed",
                "shares_consumed",
                "cash_released",
                "shares_released",
            )
        ),
        tuple(
            SimulatedTradeModel.objects.filter(account=account)
            .order_by("pk")
            .values_list("pk", "request_payload_hash", "settlement_plan_binding_version")
        ),
        tuple(
            SimulatedOrderFillReceiptModel.objects.filter(trade__account=account)
            .order_by("pk")
            .values_list("pk", "reservation_id", "trade_id", "receipt_hash")
        ),
    )


def test_valid_unrelated_terminal_v4_history_allows_ordinary_v3_buy(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A complete unrelated retained chain does not disable ordinary trading."""

    del persisted_receipt_schema
    _persist_terminal_v4_history(
        reservation_harness,
        monkeypatch,
        security_id="SH.HISTORY.SECURITY",
        asset_code="000001.SH",
    )
    use_case = _ordinary_use_case(reservation_harness.account, monkeypatch=monkeypatch)
    intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, reservation_harness.account.pk),
        key="ordinary-after-unrelated-v4-history",
    )

    result = use_case.execute(intent)

    assert result.replayed is False
    trade = SimulatedTradeModel.objects.get(pk=result.trade_id)
    assert trade.settlement_plan_binding_version == 3
    assert not SimulatedOrderFillReceiptModel.objects.filter(trade=trade).exists()


def test_valid_unrelated_terminal_v4_history_allows_ordinary_v3_sell(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A complete unrelated chain leaves an ordinary available-share SELL usable."""

    del persisted_receipt_schema
    account = reservation_harness.account
    _create_position(account, asset_code="600000.SH")
    history = _persist_terminal_v4_history(
        reservation_harness,
        monkeypatch,
        security_id="SH.HISTORY.SECURITY",
        asset_code="000001.SH",
    )
    v4_receipt_before = cast(
        dict[str, object],
        SimulatedOrderFillReceiptModel.objects.filter(pk=history.receipt.pk).values().get(),
    )
    use_case = _ordinary_use_case_at(
        account,
        as_of=history.rows.proof.calendar_read_cutoff + timedelta(minutes=1),
        monkeypatch=monkeypatch,
    )
    intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, account.pk),
        side=SimulatedTradeSide.SELL,
        key="ordinary-sell-after-valid-unrelated-v4-history",
    )
    account.refresh_from_db()
    cash_before = account.current_cash

    result = use_case.execute(intent)

    assert result.replayed is False
    trade = SimulatedTradeModel.objects.get(pk=result.trade_id)
    assert trade.action == "sell"
    assert trade.quantity == intent.quantity
    assert trade.settlement_plan_binding_version == 3
    assert not SimulatedOrderFillReceiptModel.objects.filter(trade=trade).exists()
    assert not PositionModel.objects.filter(account=account, asset_code="600000.SH").exists()
    account.refresh_from_db()
    assert account.current_cash == cash_before + trade.amount - trade.total_cost
    assert (
        cast(
            dict[str, object],
            SimulatedOrderFillReceiptModel.objects.filter(pk=history.receipt.pk).values().get(),
        )
        == v4_receipt_before
    )


@pytest.mark.parametrize(
    "side",
    (SimulatedTradeSide.BUY, SimulatedTradeSide.SELL),
)
def test_corrupt_unrelated_terminal_v4_receipt_blocks_before_any_ledger_write(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    side: SimulatedTradeSide,
) -> None:
    """A damaged account-wide V4 seal blocks ordinary BUY and SELL writes."""

    del persisted_receipt_schema
    if side is SimulatedTradeSide.SELL:
        _create_position(reservation_harness.account, asset_code="600000.SH")
    history = _persist_terminal_v4_history(
        reservation_harness,
        monkeypatch,
        security_id="SH.HISTORY.SECURITY",
        asset_code="000001.SH",
    )
    models.QuerySet.update(
        SimulatedOrderFillReceiptModel._base_manager.filter(pk=history.receipt.pk),
        receipt_hash="0" * 64,
    )
    before = _account_state(reservation_harness.account)
    use_case = _ordinary_use_case_at(
        reservation_harness.account,
        as_of=history.rows.proof.calendar_read_cutoff + timedelta(minutes=1),
        monkeypatch=monkeypatch,
    )
    intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, reservation_harness.account.pk),
        side=side,
        key="ordinary-must-not-pass-corrupt-v4-history",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        use_case.execute(intent)

    assert blocked.value.code == "SIMULATED_FILL_RECEIPT_CHAIN_INVALID"
    assert _account_state(reservation_harness.account) == before


def test_v4_trade_marker_without_receipt_blocks_ordinary_execution(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Trade marker side remains visible even if its Receipt is missing."""

    del persisted_receipt_schema
    history = _persist_terminal_v4_history(
        reservation_harness,
        monkeypatch,
        security_id="SH.HISTORY.SECURITY",
        asset_code="000001.SH",
    )
    models.QuerySet.delete(
        SimulatedOrderFillReceiptModel._base_manager.filter(pk=history.receipt.pk)
    )
    before = _account_state(reservation_harness.account)
    use_case = _ordinary_use_case(reservation_harness.account, monkeypatch=monkeypatch)
    intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, reservation_harness.account.pk),
        key="ordinary-must-not-pass-unreceipted-v4-trade",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        use_case.execute(intent)

    assert blocked.value.code == "SIMULATED_FILL_RECEIPT_CHAIN_INVALID"
    assert _account_state(reservation_harness.account) == before


def test_filled_parent_without_receipt_or_v4_trade_marker_blocks(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive parent accrual remains evidence when both locators are gone."""

    del persisted_receipt_schema
    history = _persist_terminal_v4_history(
        reservation_harness,
        monkeypatch,
        security_id="SH.HISTORY.SECURITY",
        asset_code="000001.SH",
    )
    models.QuerySet.delete(
        SimulatedOrderFillReceiptModel._base_manager.filter(pk=history.receipt.pk)
    )
    models.QuerySet.update(
        SimulatedTradeModel._base_manager.filter(pk=history.trade.pk),
        settlement_plan_binding_version=0,
        settlement_plan_binding_payload=None,
        settlement_plan_binding_hash=None,
        settlement_exchange=None,
    )
    history.reservation.refresh_from_db()
    assert history.reservation.filled_quantity > Decimal("0")
    assert history.reservation.cash_consumed > Decimal("0")
    assert history.trade.pk is not None
    history.trade.refresh_from_db()
    assert history.trade.settlement_plan_binding_version == 0
    before = _account_state(reservation_harness.account)
    use_case = _ordinary_use_case(reservation_harness.account, monkeypatch=monkeypatch)
    intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, reservation_harness.account.pk),
        key="ordinary-must-not-pass-unlocated-filled-parent",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        use_case.execute(intent)

    assert blocked.value.code == "SIMULATED_FILL_RECEIPT_CHAIN_INVALID"
    assert _account_state(reservation_harness.account) == before


@pytest.mark.parametrize("foreign_locator", ("reservation", "trade"))
def test_cross_account_receipt_locator_blocks_before_any_ledger_write(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    foreign_locator: str,
) -> None:
    """Either Receipt FK crossing owners blocks without changing either ledger."""

    del persisted_receipt_schema
    local_history, foreign_history, damaged_receipt = _cross_account_receipt_locator(
        reservation_harness,
        monkeypatch,
        foreign_locator=foreign_locator,
    )
    if foreign_locator == "reservation":
        assert damaged_receipt.reservation_id == foreign_history.reservation.pk
        assert damaged_receipt.trade_id == local_history.trade.pk
    else:
        assert foreign_locator == "trade"
        assert damaged_receipt.reservation_id == local_history.reservation.pk
        assert damaged_receipt.trade_id == foreign_history.trade.pk

    before_local = _account_state(reservation_harness.account)
    before_foreign = _account_state(foreign_history.reservation.account)
    before_receipts = _receipt_locator_state()
    use_case = _ordinary_use_case(reservation_harness.account, monkeypatch=monkeypatch)
    intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, reservation_harness.account.pk),
        key=f"ordinary-cross-account-{foreign_locator}-must-block",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        use_case.execute(intent)

    assert blocked.value.code == "SIMULATED_FILL_RECEIPT_CHAIN_INVALID"
    assert _account_state(reservation_harness.account) == before_local
    assert _account_state(foreign_history.reservation.account) == before_foreign
    assert _receipt_locator_state() == before_receipts


@pytest.mark.parametrize("foreign_locator", ("reservation", "trade"))
def test_postgres_cross_account_receipt_blocks_without_waiting_for_foreign_lock(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    django_db_use_migrations: bool,
    foreign_locator: str,
) -> None:
    """A locked foreign target cannot stall the local account's typed rejection."""

    del persisted_receipt_schema
    if not django_db_use_migrations:
        pytest.skip("cross-account row-lock behavior requires normal migrations")
    if connection.vendor != "postgresql":
        pytest.skip("cross-account row-lock behavior requires native PostgreSQL")
    assert_native_postgres_test_database()
    local_history, foreign_history, _ = _cross_account_receipt_locator(
        reservation_harness,
        monkeypatch,
        foreign_locator=foreign_locator,
    )
    if foreign_locator == "reservation":
        foreign_model = SimulatedOrderReservationModel
        foreign_pk = foreign_history.reservation.pk
    else:
        assert foreign_locator == "trade"
        foreign_model = SimulatedTradeModel
        foreign_pk = foreign_history.trade.pk
    assert type(foreign_pk) is int
    local_account = reservation_harness.account
    local_before = _account_state(local_account)
    receipts_before = _receipt_locator_state()
    use_case = _ordinary_use_case(local_account, monkeypatch=monkeypatch)
    intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, local_account.pk),
        key=f"ordinary-locked-foreign-{foreign_locator}-must-block",
    )

    def execute_local() -> object:
        """Run the local account's ordinary use case on the worker connection."""

        return use_case.execute(intent)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                holder_row = cursor.fetchone()
            assert holder_row is not None and type(holder_row[0]) is int
            holder_pid = holder_row[0]
            locked_foreign_row = foreign_model._base_manager.select_for_update(of=("self",)).get(
                pk=foreign_pk
            )
            assert locked_foreign_row.account_id == foreign_history.reservation.account_id
            assert locked_foreign_row.account_id != local_account.pk

            worker = reservation_concurrency._submit_worker(executor, execute_local)
            assert worker.backend_pids[0] != holder_pid
            try:
                outcome = worker.future.result(timeout=6)
            except FutureTimeoutError as error:
                raise AssertionError(
                    "account-local history validation waited for a foreign row lock"
                ) from error

            assert outcome.backend_pid == worker.backend_pids[0]
            assert outcome.blocked_code == "SIMULATED_FILL_RECEIPT_CHAIN_INVALID"
            assert outcome.value is None
            assert worker.future.done()
            assert _account_state(local_account) == local_before
            assert _receipt_locator_state() == receipts_before


@pytest.mark.parametrize(
    ("history_security_id", "history_asset_code"),
    (
        ("SH.UOW.SECURITY", "600001.SH"),
        ("SH.HISTORY.SECURITY", "600000.SH"),
    ),
)
def test_security_asset_alias_in_retained_v4_history_blocks_new_trade(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    history_security_id: str,
    history_asset_code: str,
) -> None:
    """Either direction of a security/asset alias fails with a typed block."""

    del persisted_receipt_schema
    _persist_terminal_v4_history(
        reservation_harness,
        monkeypatch,
        security_id=history_security_id,
        asset_code=history_asset_code,
    )
    before = _account_state(reservation_harness.account)
    use_case = _ordinary_use_case(reservation_harness.account, monkeypatch=monkeypatch)
    intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, reservation_harness.account.pk),
        key="ordinary-v4-identity-alias",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        use_case.execute(intent)

    assert blocked.value.code == "ORDER_RESERVATION_IDENTITY_CONFLICT"
    assert _account_state(reservation_harness.account) == before


def test_exact_ordinary_replay_returns_before_v4_history_scan(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exact committed V3 replay stays read-only when later V4 history is bad."""

    del persisted_receipt_schema
    account = reservation_harness.account
    intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, account.pk),
        key="ordinary-replay-before-history-scan",
    )
    use_case, identity_reader = _ordinary_use_case_with_reader(
        account,
        as_of=AS_OF,
        monkeypatch=monkeypatch,
    )
    first = use_case.execute(intent)
    assert identity_reader.reads == 1
    first_trade = SimulatedTradeModel.objects.get(pk=first.trade_id)
    assert first_trade.settlement_plan_binding_version == 3
    history = _persist_terminal_v4_history(
        reservation_harness,
        monkeypatch,
        security_id="SH.HISTORY.SECURITY",
        asset_code="000001.SH",
    )
    models.QuerySet.update(
        SimulatedOrderFillReceiptModel._base_manager.filter(pk=history.receipt.pk),
        receipt_hash="0" * 64,
    )
    before = _account_state(account)

    def unexpected_history_scan(
        *,
        account: SimulatedAccountModel,
        intent: SimulatedTradeIntent,
        using: str,
    ) -> None:
        """Fail if replay reaches the new-history guard."""

        del account, intent, using
        raise AssertionError("exact V3 replay must return before history validation")

    monkeypatch.setattr(
        "apps.simulated_trading.infrastructure.execution_settlement_uow_repository"
        ".validate_account_v4_fill_history",
        unexpected_history_scan,
        raising=False,
    )
    replay = use_case.execute(intent)

    assert replay.replayed is True
    assert replay.trade_id == first.trade_id
    assert identity_reader.reads == 1
    assert _account_state(account) == before


def test_full_sell_then_buy_reentry_remains_available_after_terminal_v4_history(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid history scan does not make a normally closed Position permanent."""

    del persisted_receipt_schema
    account = reservation_harness.account
    _create_position(account)
    _persist_terminal_v4_history(
        reservation_harness,
        monkeypatch,
        security_id="SH.HISTORY.SECURITY",
        asset_code="000001.SH",
    )
    use_case = _ordinary_use_case(account, monkeypatch=monkeypatch)
    sell_intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, account.pk),
        side=SimulatedTradeSide.SELL,
        key="ordinary-full-exit-after-v4-history",
    )
    v4_receipt = SimulatedOrderFillReceiptModel.objects.get(
        reservation__account=account,
    )
    v4_receipt_hash = v4_receipt.receipt_hash

    sold = use_case.execute(sell_intent)

    assert sold.replayed is False
    sell_trade = SimulatedTradeModel.objects.get(pk=sold.trade_id)
    assert sell_trade.settlement_plan_binding_version == 3
    assert not PositionModel.objects.filter(account=account, asset_code="600000.SH").exists()
    assert (
        SimulatedOrderFillReceiptModel.objects.get(pk=v4_receipt.pk).receipt_hash == v4_receipt_hash
    )

    buy_intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, account.pk),
        side=SimulatedTradeSide.BUY,
        key="ordinary-reentry-after-full-exit",
    )
    bought = use_case.execute(buy_intent)

    assert bought.replayed is False
    buy_trade = SimulatedTradeModel.objects.get(pk=bought.trade_id)
    assert buy_trade.settlement_plan_binding_version == 3
    assert PositionModel.objects.filter(account=account, asset_code="600000.SH").exists()
    assert (
        SimulatedOrderFillReceiptModel.objects.get(pk=v4_receipt.pk).receipt_hash == v4_receipt_hash
    )


def test_same_asset_v4_full_exit_releases_then_allows_buy_reentry(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Release real V4 T+1 shares, then fully exit and reenter that same asset."""

    del persisted_receipt_schema
    account = reservation_harness.account
    history = _persist_terminal_v4_history(
        reservation_harness,
        monkeypatch,
        security_id="SH.UOW.SECURITY",
        asset_code="600000.SH",
    )
    assert history.rows.proof.settlement_lag_sessions == 2
    assert history.rows.proof.expected_release_session == date(2026, 10, 20)
    position = PositionModel.objects.get(account=account, asset_code="600000.SH")
    full_quantity = position.quantity
    assert full_quantity == Decimal("200.000000")
    assert position.available_quantity < full_quantity
    assert history.trade.settlement_status == "pending"

    release_at = AS_OF + timedelta(days=4)
    assert _release_v4_history(history, as_of=release_at) == 1
    position.refresh_from_db()
    history.trade.refresh_from_db()
    assert history.trade.settlement_status == "released"
    assert history.trade.settlement_release_session == date(2026, 10, 20)
    assert history.trade.settlement_release_proof_payload is not None
    assert type(history.trade.settlement_release_proof_hash) is str
    assert position.quantity == full_quantity
    assert position.available_quantity == full_quantity

    v4_receipt_before = cast(
        dict[str, object],
        SimulatedOrderFillReceiptModel.objects.filter(pk=history.receipt.pk).values().get(),
    )
    v4_trade_before = cast(
        dict[str, object],
        SimulatedTradeModel.objects.filter(pk=history.trade.pk).values().get(),
    )
    execution_at = release_at + timedelta(minutes=1)
    use_case = _ordinary_use_case_at(
        account,
        as_of=execution_at,
        monkeypatch=monkeypatch,
    )
    sell_intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, account.pk),
        side=SimulatedTradeSide.SELL,
        key="ordinary-sell-entire-same-asset-v4-position",
        quantity=full_quantity,
    )
    account.refresh_from_db()
    cash_before_sell = account.current_cash

    sold = use_case.execute(sell_intent)

    assert sold.replayed is False
    sell_trade = SimulatedTradeModel.objects.get(pk=sold.trade_id)
    assert sell_trade.action == "sell"
    assert sell_trade.settlement_plan_binding_version == 3
    assert sell_trade.quantity == full_quantity
    assert sell_trade.asset_code == "600000.SH"
    assert not PositionModel.objects.filter(account=account, asset_code="600000.SH").exists()
    account.refresh_from_db()
    assert account.current_cash == cash_before_sell + sell_trade.amount - sell_trade.total_cost
    assert (
        cast(
            dict[str, object],
            SimulatedOrderFillReceiptModel.objects.filter(pk=history.receipt.pk).values().get(),
        )
        == v4_receipt_before
    )
    assert (
        cast(
            dict[str, object],
            SimulatedTradeModel.objects.filter(pk=history.trade.pk).values().get(),
        )
        == v4_trade_before
    )

    buy_intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, account.pk),
        side=SimulatedTradeSide.BUY,
        key="ordinary-buy-reenters-same-v4-asset",
    )
    cash_before_buy = account.current_cash
    bought = use_case.execute(buy_intent)

    assert bought.replayed is False
    buy_trade = SimulatedTradeModel.objects.get(pk=bought.trade_id)
    assert buy_trade.action == "buy"
    assert buy_trade.settlement_plan_binding_version == 3
    assert buy_trade.asset_code == "600000.SH"
    assert buy_trade.quantity == buy_intent.quantity
    assert PositionModel.objects.get(account=account, asset_code="600000.SH").quantity == (
        buy_intent.quantity
    )
    account.refresh_from_db()
    assert account.current_cash == cash_before_buy - buy_trade.total_cost
    assert (
        cast(
            dict[str, object],
            SimulatedOrderFillReceiptModel.objects.filter(pk=history.receipt.pk).values().get(),
        )
        == v4_receipt_before
    )
    assert (
        cast(
            dict[str, object],
            SimulatedTradeModel.objects.filter(pk=history.trade.pk).values().get(),
        )
        == v4_trade_before
    )


def test_zero_fill_cancelled_reservation_does_not_require_a_v4_receipt(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal G1 cancellation without any fill stays compatible."""

    del persisted_receipt_schema
    intent = _intent_for(reservation_harness, key="zero-fill-cancel-before-v3-trade")
    reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    cancelled = CancelSimulatedOrderReservationUseCase(
        repository=reservation_harness.repository,
        clock=_Clock(AS_OF + timedelta(minutes=1)),
    ).execute(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        idempotency_key=intent.idempotency_key,
    )
    assert cancelled.status is OrderReservationStatus.CANCELLED
    assert cancelled.filled_quantity == Decimal("0.000000")
    assert not SimulatedOrderFillReceiptModel.objects.filter(
        reservation__account=reservation_harness.account,
    ).exists()

    use_case = _ordinary_use_case(reservation_harness.account, monkeypatch=monkeypatch)
    ordinary_intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, reservation_harness.account.pk),
        key="ordinary-after-zero-fill-cancel",
    )
    result = use_case.execute(ordinary_intent)

    assert result.replayed is False
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 1


def test_ordinary_v3_execution_remains_available_without_retained_v4_history(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new guard preserves the existing empty-history V3 execution path."""

    del persisted_receipt_schema
    use_case = _ordinary_use_case(reservation_harness.account, monkeypatch=monkeypatch)
    intent = _intent(
        user_id=reservation_harness.user_id,
        account_id=cast(int, reservation_harness.account.pk),
        key="ordinary-v3-empty-history-compatibility",
    )

    result = use_case.execute(intent)

    assert result.replayed is False
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 1
    trade = SimulatedTradeModel.objects.get(account=reservation_harness.account)
    assert trade.settlement_plan_binding_version == 3
    assert not SimulatedOrderFillReceiptModel.objects.filter(
        trade__account=reservation_harness.account
    ).exists()
