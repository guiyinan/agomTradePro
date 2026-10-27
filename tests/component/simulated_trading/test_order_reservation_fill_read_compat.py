"""Read-path compatibility for real persisted V4 fill histories."""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import cast
from unittest.mock import patch

import pytest
from django.db import connection, connections, models
from django.test.utils import CaptureQueriesContext
from pytest_django.plugin import DjangoDbBlocker

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.infrastructure import order_reservation_fill_trade_read_guard
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.performance_repositories import (
    DjangoTradeHistoryRepository,
)
from apps.simulated_trading.infrastructure.share_account_gateway import (
    SimulatedTradingShareAccountGateway,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.trade_repository import DjangoTradeRepository
from apps.simulated_trading.infrastructure.trade_summary_repository import (
    DjangoTradeSummaryRepository,
)
from tests.component.simulated_trading import (
    test_order_reservation_fill_row_reader as fill_row_reader_test_module,
)
from tests.component.simulated_trading.test_execution_settlement_uow import AS_OF as AS_OF
from tests.component.simulated_trading.test_execution_settlement_uow import (
    DjangoSimulatedTradeExecutionRepository as DjangoSimulatedTradeExecutionRepository,
)
from tests.component.simulated_trading.test_execution_settlement_uow import _Clock as _Clock
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _current_v3_plan as _current_v3_plan,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_release import (
    _RELEASE_AT,
    _make_due_fills,
    _release,
    _release_evidence,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _EventReader,
    _FixedClock,
    _initial_position_mark,
    _InitialPositionMarkReader,
    _invoke,
    _set_consistent_account_mark,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    reservation_harness as reservation_harness,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _READ_CUTOFF,
    _reader_rows,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _create_position,
    _Harness,
    _intent_for,
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)

_ALL_READ_PATHS: tuple[str, ...] = (
    "trade_account",
    "trade_exact_owner",
    "trade_date_range",
    "trade_asset",
    "trade_account_page",
    "trade_count",
    "trade_date_count",
    "trade_date_summary",
    "trade_account_summary",
    "trade_incomplete_costs",
    "summary_account",
    "summary_global",
    "share_account",
    "share_trades",
    "performance_closed",
)
_V4_READ_ALIAS = "simulated_v4_history_read_alias"


@pytest.fixture
def v4_history_read_alias(django_db_blocker: DjangoDbBlocker) -> Iterator[str]:
    """Route a second Django connection to the same disposable test database."""

    if _V4_READ_ALIAS in connections.databases:
        raise RuntimeError(f"refusing preexisting database alias: {_V4_READ_ALIAS}")
    connections.databases[_V4_READ_ALIAS] = deepcopy(connections["default"].settings_dict)
    try:
        with django_db_blocker.unblock():
            yield _V4_READ_ALIAS
    finally:
        with django_db_blocker.unblock():
            connections[_V4_READ_ALIAS].close()
            del connections[_V4_READ_ALIAS]
            connections.databases.pop(_V4_READ_ALIAS, None)


def _reject_default(execute, sql, params, many, context):
    """Fail if any part of a selected-alias V4 history read touches default."""

    del execute, sql, params, many, context
    raise AssertionError("V4 history read escaped the selected database alias")


def _persist_v4_fill(
    harness: _Harness,
    *,
    side: SimulatedTradeSide,
    first_buy: bool = False,
) -> tuple[SimulatedTradeModel, SimulatedOrderFillReceiptModel]:
    """Use the real fill writer and return its persisted Trade and Receipt."""

    if first_buy:
        if side is not SimulatedTradeSide.BUY:
            raise AssertionError("the initial-position mark fixture requires a BUY")
        rows = _reader_rows(harness)
        _set_consistent_account_mark(harness.account, market_value=Decimal("0.00"))
        mark_reader = _InitialPositionMarkReader(_initial_position_mark(rows), [])
    else:
        rows = _reader_rows(harness, side=side)
        mark_reader = None
        if side is SimulatedTradeSide.SELL:
            _set_consistent_account_mark(harness.account, market_value=Decimal("1000.00"))

    rows.reservation.refresh_from_db()
    event_reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=event_reader,
        initial_position_mark_reader=mark_reader,
        using="default",
    )
    result = _invoke(
        repository,
        rows.event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )
    assert result.replayed is False
    trade = SimulatedTradeModel._default_manager.get(pk=result.trade_id)
    receipt = SimulatedOrderFillReceiptModel._default_manager.get(trade_id=trade.pk)
    assert trade.settlement_plan_binding_version == 4
    assert receipt.reservation_id == rows.reservation.pk
    assert receipt.trade_id == trade.pk
    return trade, receipt


def _read_path(
    path: str,
    *,
    account_id: int,
    owner_id: int,
    trade_id: int,
    execution_date: date,
) -> object:
    """Invoke one real adapter path without bypassing its V4 validation."""

    trade_repository = DjangoTradeRepository()
    if path == "trade_account":
        return trade_repository.get_by_account(account_id)
    if path == "trade_exact_owner":
        return trade_repository.get_owned_trade_by_id(
            trade_id=trade_id,
            account_id=account_id,
            user_id=owner_id,
        )
    if path == "trade_date_range":
        return trade_repository.get_by_date_range(
            account_id,
            execution_date,
            execution_date,
        )
    if path == "trade_asset":
        trade = SimulatedTradeModel._default_manager.get(pk=trade_id)
        return trade_repository.get_by_asset(account_id, trade.asset_code)
    if path == "trade_account_page":
        return trade_repository.list_trade_models_for_account(account_id, limit=1)
    if path == "trade_count":
        return trade_repository.count_trade_models()
    if path == "trade_date_count":
        return trade_repository.count_by_execution_date(account_id, execution_date)
    if path == "trade_date_summary":
        return trade_repository.summarize_trade_models_for_date(execution_date)
    if path == "trade_account_summary":
        return trade_repository.get_trade_model_summary_for_account(account_id)
    if path == "trade_incomplete_costs":
        return trade_repository.has_incomplete_closed_trade_costs(account_id)
    if path == "summary_account":
        return DjangoTradeSummaryRepository().get_trade_model_summary_for_account(account_id)
    if path == "summary_global":
        return DjangoTradeSummaryRepository().sum_realized_pnl_for_closed_trades()
    if path == "share_account":
        return SimulatedTradingShareAccountGateway().get_owned_account(
            owner_id=owner_id,
            account_id=account_id,
        )
    if path == "share_trades":
        return SimulatedTradingShareAccountGateway().list_owned_trades(
            owner_id=owner_id,
            account_id=account_id,
            limit=20,
        )
    if path == "performance_closed":
        return DjangoTradeHistoryRepository().list_closed_trades(
            account_id,
            start_date=execution_date,
            end_date=execution_date,
        )
    raise AssertionError(f"unknown read path: {path}")


def test_nondefault_v4_history_read_stays_on_selected_alias(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    v4_history_read_alias: str,
) -> None:
    """Validate a real SELL receipt chain without escaping its selected alias."""

    del persisted_receipt_schema
    trade, receipt = _persist_v4_fill(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
    )
    assert receipt.trade_id == trade.pk
    trade_rows = SimulatedTradeModel._default_manager.using(v4_history_read_alias).filter(
        pk=trade.pk
    )
    assert trade_rows.db == v4_history_read_alias

    with (
        connections["default"].execute_wrapper(_reject_default),
        CaptureQueriesContext(connections[v4_history_read_alias]) as captured,
    ):
        order_reservation_fill_trade_read_guard.validate_v4_trade_history(trade_rows)
        assert (
            DjangoTradeRepository().has_incomplete_closed_trade_costs(
                cast(int, reservation_harness.account.pk),
                using=v4_history_read_alias,
            )
            is True
        )

    assert captured.captured_queries


def test_real_v4_sell_remains_readable_and_unknown_pnl_stays_unknown(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Core, summary, Share, and performance adapters preserve persisted facts."""

    del persisted_receipt_schema
    trade, receipt = _persist_v4_fill(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
    )
    account_id = cast(int, reservation_harness.account.pk)
    trade_id = cast(int, trade.pk)
    owner_id = reservation_harness.user_id
    assert receipt.receipt_version == 1
    assert trade.realized_pnl is None
    assert trade.realized_pnl_pct is None

    repository = DjangoTradeRepository()
    exact = repository.get_owned_trade_by_id(
        trade_id=trade_id,
        account_id=account_id,
        user_id=owner_id,
    )
    assert exact is not None
    assert exact.trade_id == trade_id
    assert exact.realized_pnl is None
    assert exact.realized_pnl_pct is None
    assert len(repository.get_by_account(account_id)) == 1
    assert (
        len(repository.get_by_date_range(account_id, trade.execution_date, trade.execution_date))
        == 1
    )
    assert len(repository.get_by_asset(account_id, trade.asset_code)) == 1
    assert len(repository.list_trade_models_for_account(account_id, limit=1)) == 1
    assert repository.count_by_execution_date(account_id, trade.execution_date) == 1
    assert repository.summarize_trade_models_for_date(trade.execution_date) == {
        "buy_count": 0,
        "sell_count": 1,
    }

    summary_repository = DjangoTradeSummaryRepository()
    assert summary_repository.has_incomplete_closed_trade_costs(account_id) is True
    account_summary = summary_repository.get_trade_model_summary_for_account(account_id)
    assert account_summary["total_realized_pnl_known"] is False
    assert account_summary["total_realized_pnl"] is None
    global_summary = summary_repository.sum_realized_pnl_for_closed_trades()
    assert global_summary["known"] is False
    assert global_summary["realized_pnl"] is None
    assert global_summary["executed_sell_count"] == 1
    assert global_summary["covered_executed_sell_count"] == 0

    gateway = SimulatedTradingShareAccountGateway()
    share_account = gateway.get_owned_account(owner_id=owner_id, account_id=account_id)
    assert share_account is not None
    assert share_account.realized_trade_metrics_known is False
    share_trades = gateway.list_owned_trades(
        owner_id=owner_id,
        account_id=account_id,
        limit=20,
    )
    assert len(share_trades) == 1
    assert share_trades[0].action == "sell"

    performance_rows = DjangoTradeHistoryRepository().list_closed_trades(
        account_id,
        start_date=trade.execution_date,
        end_date=trade.execution_date,
    )
    assert len(performance_rows) == 1
    assert performance_rows[0]["realized_pnl"] is None
    assert performance_rows[0]["cost_basis_known"] is None
    assert performance_rows[0]["fee_amounts_known"] is True

    other_owner = owner_id + 1
    assert (
        repository.get_owned_trade_by_id(
            trade_id=trade_id,
            account_id=account_id,
            user_id=other_owner,
        )
        is None
    )
    assert (
        gateway.list_owned_trades(
            owner_id=other_owner,
            account_id=account_id,
            limit=20,
        )
        == []
    )


def test_two_real_fills_validate_the_complete_parent_chain_once(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Two persisted siblings cause one real full-chain Domain validation."""

    del persisted_receipt_schema
    fills = _make_due_fills(reservation_harness)
    original_validator = (
        order_reservation_fill_trade_read_guard.validate_order_reservation_fill_chain
    )
    with patch.object(
        order_reservation_fill_trade_read_guard,
        "validate_order_reservation_fill_chain",
        wraps=original_validator,
    ) as chain_validator:
        rows = DjangoTradeRepository().get_by_account(cast(int, reservation_harness.account.pk))

    assert len(rows) == 2
    assert fills.first_result.trade_id != fills.second_result.trade_id
    assert chain_validator.call_count == 1
    call = chain_validator.call_args
    assert call is not None
    assert len(call.kwargs["entries"]) == 2


def test_v4_trade_read_blocks_when_its_persisted_receipt_is_missing(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A committed V4 Trade cannot fall back to legacy mapping without its receipt."""

    del persisted_receipt_schema
    trade, receipt = _persist_v4_fill(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
    )
    receipt_query = SimulatedOrderFillReceiptModel._default_manager.filter(pk=receipt.pk)
    deleted, details = models.QuerySet.delete(receipt_query)
    assert (deleted, sum(details.values())) == (1, 1)

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        DjangoTradeRepository().get_owned_trade_by_id(
            trade_id=cast(int, trade.pk),
            account_id=cast(int, trade.account_id),
            user_id=reservation_harness.user_id,
        )
    assert blocked.value.code == "ORDER_RESERVATION_FILL_HISTORY_INVALID"


@pytest.mark.parametrize("path", _ALL_READ_PATHS)
def test_every_persisted_v4_sell_read_path_blocks_fee_mirror_drift(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    path: str,
) -> None:
    """A persisted Trade fee mismatch cannot escape any selected read surface."""

    del persisted_receipt_schema
    trade, _ = _persist_v4_fill(reservation_harness, side=SimulatedTradeSide.SELL)
    account_id = cast(int, reservation_harness.account.pk)
    trade_id = cast(int, trade.pk)
    next_commission = trade.commission + Decimal("0.01")
    trade_query = SimulatedTradeModel._default_manager.filter(pk=trade_id)
    changed = models.QuerySet.update(trade_query, commission=next_commission)
    assert changed == 1

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _read_path(
            path,
            account_id=account_id,
            owner_id=reservation_harness.user_id,
            trade_id=trade_id,
            execution_date=trade.execution_date,
        )
    assert blocked.value.code == "ORDER_RESERVATION_FILL_HISTORY_INVALID"


@pytest.mark.parametrize("path", _ALL_READ_PATHS)
def test_every_read_path_blocks_a_receipt_backed_trade_version_downgrade(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    path: str,
) -> None:
    """A receipt FK keeps downgraded V4 rows on the strict history path."""

    del persisted_receipt_schema
    trade, receipt = _persist_v4_fill(reservation_harness, side=SimulatedTradeSide.SELL)
    trade_id = cast(int, trade.pk)
    trade_query = SimulatedTradeModel._default_manager.filter(pk=trade_id)
    assert models.QuerySet.update(trade_query, settlement_plan_binding_version=3) == 1
    trade.refresh_from_db()
    assert trade.settlement_plan_binding_version == 3
    assert SimulatedOrderFillReceiptModel._default_manager.filter(
        pk=receipt.pk,
        trade_id=trade_id,
    ).exists()

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _read_path(
            path,
            account_id=cast(int, reservation_harness.account.pk),
            owner_id=reservation_harness.user_id,
            trade_id=trade_id,
            execution_date=trade.execution_date,
        )
    assert blocked.value.code == "ORDER_RESERVATION_FILL_HISTORY_INVALID"


def test_legacy_v3_trade_without_a_receipt_remains_readable(
    reservation_harness: _Harness,
) -> None:
    """Ordinary V3 settlement history remains compatible without fill receipts."""

    intent = _intent_for(reservation_harness, key="legacy-v3-no-fill-receipt")
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    plan, execution_bundle, _ = _current_v3_plan(
        repository=repository,
        intent=intent,
        as_of=AS_OF,
    )
    execution_receipt = repository.execute_trade(
        plan=plan,
        execution_bundle=execution_bundle,
        clock=_Clock(AS_OF),
    )
    trade = SimulatedTradeModel._default_manager.get(pk=execution_receipt.trade_id)
    assert trade.settlement_plan_binding_version == 3
    assert not SimulatedOrderFillReceiptModel._default_manager.filter(trade_id=trade.pk).exists()

    rows = DjangoTradeRepository().get_by_account(cast(int, reservation_harness.account.pk))
    assert len(rows) == 1
    assert rows[0].trade_id == trade.pk


def test_foreign_trade_with_a_v4_locator_does_not_poison_owner_read(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A foreign orphan locator is isolated by the exact account/parent pair."""

    del persisted_receipt_schema
    trade, receipt = _persist_v4_fill(reservation_harness, side=SimulatedTradeSide.SELL)
    foreign_account = SimulatedAccountModel._default_manager.create(
        user_id=reservation_harness.user_id,
        account_name="foreign-locator-read-fixture",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        total_value=Decimal("10000.00"),
    )
    foreign_trade = SimulatedTradeModel._default_manager.get(pk=trade.pk)
    foreign_trade.pk = None
    foreign_trade.account = foreign_account
    foreign_trade.save(force_insert=True)
    foreign_trade_id = cast(int, foreign_trade.pk)
    assert foreign_trade_id != trade.pk
    assert foreign_trade.settlement_plan_binding_payload == trade.settlement_plan_binding_payload
    assert (
        SimulatedOrderFillReceiptModel._default_manager.filter(trade_id=foreign_trade_id).count()
        == 0
    )
    assert SimulatedOrderFillReceiptModel._default_manager.filter(pk=receipt.pk).exists()

    owner_rows = DjangoTradeRepository().get_by_account(cast(int, trade.account_id))
    assert [row.trade_id for row in owner_rows] == [trade.pk]

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        DjangoTradeRepository().get_by_account(cast(int, foreign_account.pk))
    assert blocked.value.code == "ORDER_RESERVATION_FILL_HISTORY_INVALID"


def test_global_sell_summary_uses_exact_account_reservation_pairs(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A non-SELL locator cannot cross-poison two selected SELL parent scopes."""

    del persisted_receipt_schema
    sell_a, receipt_sell_a = _persist_v4_fill(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
    )
    account_b = SimulatedAccountModel._default_manager.create(
        user_id=reservation_harness.user_id,
        account_name="cartesian-scope-account-b",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        total_value=Decimal("10000.00"),
    )
    harness_b = replace(reservation_harness, account=account_b)
    sell_b, receipt_sell_b = _persist_v4_fill(
        harness_b,
        side=SimulatedTradeSide.SELL,
    )
    assert sell_a.account_id != sell_b.account_id
    assert receipt_sell_a.reservation_id != receipt_sell_b.reservation_id

    original_intent_builder = fill_row_reader_test_module._intent_for

    def distinct_buy_intent(
        selected_harness: _Harness,
        *,
        side: SimulatedTradeSide = SimulatedTradeSide.BUY,
        key: str = "fill-row-reader-order",
    ) -> SimulatedTradeIntent:
        """Give the second account's BUY a separate persisted order identity."""

        return original_intent_builder(
            selected_harness,
            side=side,
            key=f"{key}-cartesian-buy",
        )

    with patch.object(
        fill_row_reader_test_module,
        "_intent_for",
        new=distinct_buy_intent,
    ):
        buy_b, receipt_buy_b = _persist_v4_fill(
            harness_b,
            side=SimulatedTradeSide.BUY,
        )

    sell_parent_ids = {receipt_sell_a.reservation_id, receipt_sell_b.reservation_id}
    assert receipt_buy_b.reservation_id not in sell_parent_ids
    assert buy_b.account_id == account_b.pk
    assert buy_b.action == "buy"

    tampered_locator = cast(dict[str, object], buy_b.settlement_plan_binding_payload).copy()
    tampered_locator["reservation_id"] = receipt_sell_a.reservation_id
    buy_query = SimulatedTradeModel._default_manager.filter(pk=buy_b.pk)
    assert (
        models.QuerySet.update(
            buy_query,
            settlement_plan_binding_payload=tampered_locator,
        )
        == 1
    )

    summary = DjangoTradeSummaryRepository().sum_realized_pnl_for_closed_trades()
    assert summary["executed_sell_count"] == 2
    assert summary["covered_executed_sell_count"] == 0
    assert summary["known"] is False
    assert summary["realized_pnl"] is None


def test_public_read_blocks_released_lagged_v4_when_both_proof_fields_are_missing(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A real lagged V4 release cannot bypass its proof through a public reader."""

    del persisted_receipt_schema
    fills = _make_due_fills(reservation_harness)
    assert (
        _release(
            account_id=cast(int, reservation_harness.account.pk),
            user_id=reservation_harness.user_id,
            as_of=_RELEASE_AT,
            evidence=_release_evidence(_RELEASE_AT),
        )
        == 2
    )
    trade_id = cast(int, fills.first_result.trade_id)
    trade_query = SimulatedTradeModel._default_manager.filter(pk=trade_id)
    assert (
        models.QuerySet.update(
            trade_query,
            settlement_release_proof_payload=None,
            settlement_release_proof_hash=None,
        )
        == 1
    )

    trade = SimulatedTradeModel._default_manager.get(pk=trade_id)
    assert trade.settlement_status == "released"
    assert trade.settlement_lag_sessions is not None
    assert trade.settlement_lag_sessions > 0
    assert trade.settlement_release_proof_payload is None
    assert trade.settlement_release_proof_hash is None
    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        DjangoTradeRepository().get_by_account(cast(int, trade.account_id))
    assert blocked.value.code == "ORDER_RESERVATION_FILL_HISTORY_INVALID"


@pytest.mark.parametrize("damage", ("changed", "missing"))
def test_first_buy_marked_v4_row_blocks_after_persisted_mark_evidence_damage(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    damage: str,
) -> None:
    """A real V2 BUY receipt is readable, while damaged or absent evidence blocks."""

    del persisted_receipt_schema
    trade, receipt = _persist_v4_fill(
        reservation_harness,
        side=SimulatedTradeSide.BUY,
        first_buy=True,
    )
    assert receipt.receipt_version == 2
    assert receipt.initial_position_mark_evidence is not None
    assert len(DjangoTradeRepository().get_by_account(cast(int, trade.account_id))) == 1

    if damage == "changed":
        mark_payload: dict[str, object] | None = cast(
            dict[str, object], receipt.initial_position_mark_evidence
        ).copy()
        mark_payload["source_record_id"] = "tampered-mark-record"
    else:
        mark_payload = None
    receipt_query = SimulatedOrderFillReceiptModel._default_manager.filter(pk=receipt.pk)
    changed = models.QuerySet.update(
        receipt_query,
        receipt_version=2 if mark_payload is not None else 1,
        initial_position_mark_evidence=mark_payload,
    )
    assert changed == 1

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        DjangoTradeRepository().get_by_account(cast(int, trade.account_id))
    assert blocked.value.code == "ORDER_RESERVATION_FILL_HISTORY_INVALID"


def test_released_v4_row_blocks_after_persisted_release_proof_changes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A stored T+1 release proof is part of every exposed V4 history."""

    del persisted_receipt_schema
    fills = _make_due_fills(reservation_harness)
    released_count = _release(
        account_id=cast(int, reservation_harness.account.pk),
        user_id=reservation_harness.user_id,
        as_of=_RELEASE_AT,
        evidence=_release_evidence(_RELEASE_AT),
    )
    assert released_count == 2
    trade = (
        SimulatedTradeModel._default_manager.filter(account=reservation_harness.account)
        .order_by("pk")
        .first()
    )
    assert trade is not None
    assert trade.settlement_status == "released"
    assert trade.settlement_release_proof_payload is not None
    assert fills.rows.reservation.account_id == trade.account_id
    readable = DjangoTradeRepository().get_by_account(cast(int, trade.account_id))
    assert len(readable) == 2

    release_payload = cast(dict[str, object], trade.settlement_release_proof_payload).copy()
    release_payload["receipt_hash"] = "0" * 64
    trade_query = SimulatedTradeModel._default_manager.filter(pk=trade.pk)
    changed = models.QuerySet.update(
        trade_query,
        settlement_release_proof_payload=release_payload,
    )
    assert changed == 1

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        DjangoTradeRepository().get_by_account(cast(int, trade.account_id))
    assert blocked.value.code == "ORDER_RESERVATION_FILL_HISTORY_INVALID"


def test_share_position_snapshot_does_not_query_trade_history(
    reservation_harness: _Harness,
) -> None:
    """The Share position snapshot remains a position-only read boundary."""

    position = _create_position(reservation_harness.account)
    with CaptureQueriesContext(connection) as captured:
        result = SimulatedTradingShareAccountGateway().list_owned_positions(
            owner_id=reservation_harness.user_id,
            account_id=cast(int, reservation_harness.account.pk),
        )

    assert len(result) == 1
    assert result[0].asset_code == position.asset_code
    sql = tuple(str(query["sql"]).lower() for query in captured.captured_queries)
    trade_table = SimulatedTradeModel._meta.db_table.lower()
    receipt_table = SimulatedOrderFillReceiptModel._meta.db_table.lower()
    assert all(trade_table not in statement for statement in sql)
    assert all(receipt_table not in statement for statement in sql)


def test_sibling_v4_query_chunks_more_than_one_thousand_exact_parent_pairs(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Large exact scopes stay bounded and exclude a cross-account JSON locator."""

    del persisted_receipt_schema
    trade, receipt = _persist_v4_fill(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
    )
    foreign_account = SimulatedAccountModel._default_manager.create(
        user_id=reservation_harness.user_id,
        account_name="large-sibling-scope-foreign-account",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        total_value=Decimal("10000.00"),
    )
    foreign_trade = SimulatedTradeModel._default_manager.get(pk=trade.pk)
    foreign_trade.pk = None
    foreign_trade.account = foreign_account
    foreign_trade.save(force_insert=True)

    account_id = cast(int, trade.account_id)
    reservation_id = cast(int, receipt.reservation_id)
    foreign_account_id = cast(int, foreign_account.pk)
    parent_scopes: list[tuple[int, int]] = [
        (account_id, reservation_id),
        (foreign_account_id, reservation_id + 1),
    ]
    parent_scopes.extend(
        (
            account_id if offset % 2 == 0 else foreign_account_id,
            1_000_000 + offset,
        )
        for offset in range(999)
    )
    assert len(parent_scopes) == 1001
    assert len(set(parent_scopes)) == 1001

    with CaptureQueriesContext(connection) as captured:
        sibling_ids = order_reservation_fill_trade_read_guard._sibling_v4_trade_ids(
            tuple(parent_scopes)
        )

    assert len(captured.captured_queries) == 11
    assert sibling_ids == {cast(int, trade.pk)}
    assert cast(int, foreign_trade.pk) not in sibling_ids
