"""Structured business results returned by the daily auto-trading task."""

from __future__ import annotations

from collections.abc import ItemsView, Iterator, Mapping, Sequence
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock
from uuid import UUID

import pytest
from celery.exceptions import Retry

from apps.simulated_trading.application import interface_services, tasks
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingIssue,
    AutoTradingIssueKind,
)
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount
from tests.unit.simulated_trading.test_automatic_invocation_application import (
    _MemoryInvocationRepository,
)


def _patch_task_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    engine: Mock,
    *,
    active_account_ids: Sequence[int] = (),
    active_accounts: Sequence[object] | None = None,
) -> tuple[SimpleNamespace, Mock]:
    rows = (
        list(active_accounts)
        if active_accounts is not None
        else [
            SimpleNamespace(account_id=account_id, account_type=AccountType.SIMULATED)
            for account_id in active_account_ids
        ]
    )
    account_repository = SimpleNamespace(get_active_accounts=Mock(return_value=rows))
    invocation_repository = _MemoryInvocationRepository()
    monkeypatch.setattr(
        tasks,
        "get_simulated_account_repository",
        Mock(return_value=account_repository),
    )
    monkeypatch.setattr(
        tasks,
        "get_auto_invocation_repository",
        Mock(return_value=invocation_repository),
    )
    engine_factory = Mock(return_value=engine)
    monkeypatch.setattr(tasks, "build_auto_trading_engine", engine_factory)
    return account_repository, engine_factory


def _account(account_id: int, account_type: AccountType) -> SimulatedAccount:
    return SimulatedAccount(
        account_id=account_id,
        account_name=f"account-{account_id}",
        account_type=account_type,
        initial_capital=100.0,
        current_cash=100.0,
        current_market_value=0.0,
        total_value=100.0,
    )


def _forbid_retry(monkeypatch: pytest.MonkeyPatch) -> Mock:
    retry = Mock(side_effect=AssertionError("execution must not retry the whole batch"))
    monkeypatch.setattr(tasks.daily_auto_trading_task, "retry", retry)
    return retry


def test_task_aggregates_typed_account_outcomes_in_account_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    engine.run_daily_trading.return_value = {
        1: AccountAutoTradingOutcome(account_id=1, buy_count=2, sell_count=1),
        2: AccountAutoTradingOutcome(
            account_id=2,
            buy_count=0,
            sell_count=0,
            issues=(
                AutoTradingIssue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="risk_check",
                    code="ACCOUNT_BLOCKED",
                ),
            ),
        ),
    }
    _patch_task_dependencies(monkeypatch, engine)
    retry = _forbid_retry(monkeypatch)

    result = tasks.daily_auto_trading_task.run(
        trade_date="2026-04-30", account_ids=[1, 2], invocation_key="outcome-aggregate-001"
    )

    assert result["outcome"] == "partial"
    assert result["success"] is True
    assert result["requested"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["stored"] == 3
    assert result["counts_unavailable"] is False
    assert result["buy_count"] == 2
    assert result["sell_count"] == 1
    assert result["confirmed_trade_count"] == 3
    assert result["count_unit"] == "account"
    assert result["stored_count_unit"] == "trade"
    assert result["count_units"]["buy_count"] == "trade"
    assert result["stable_error_code"] == "ACCOUNT_BLOCKED"
    assert result["total_accounts"] == 2
    assert result["summary"] == {
        "total_buy_count": 2,
        "total_sell_count": 1,
        "confirmed_trade_count": 3,
        "stored_trade_count": 3,
        "counts_unavailable": False,
    }
    assert result["results"][2]["outcome"] == "blocked"
    engine.run_daily_trading.assert_called_once_with(tasks.date(2026, 4, 30), account_ids=[1, 2])
    retry.assert_not_called()


def test_task_keeps_confirmed_trades_but_marks_uncertain_storage_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    engine.run_daily_trading.return_value = {
        1: AccountAutoTradingOutcome(
            account_id=1,
            buy_count=1,
            sell_count=0,
            issues=(
                AutoTradingIssue(
                    kind=AutoTradingIssueKind.FAILED,
                    stage="trade_write",
                    code="TRADE_RESULT_UNKNOWN",
                    effects_indeterminate=True,
                ),
            ),
        )
    }
    _patch_task_dependencies(monkeypatch, engine)
    retry = _forbid_retry(monkeypatch)

    result = tasks.daily_auto_trading_task.run(
        trade_date="2026-04-30", account_ids=[1], invocation_key="outcome-unknown-storage-001"
    )

    assert result["outcome"] == "partial"
    assert result["buy_count"] == 1
    assert result["sell_count"] == 0
    assert result["confirmed_trade_count"] == 1
    assert result["stored"] is None
    assert result["counts_unavailable"] is True
    assert result["summary"]["stored_trade_count"] is None
    assert result["summary"]["counts_unavailable"] is True
    engine.run_daily_trading.assert_called_once()
    retry.assert_not_called()


def test_engine_exception_after_execution_starts_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    engine.run_daily_trading.side_effect = RuntimeError("vendor write outcome unknown")
    _patch_task_dependencies(monkeypatch, engine)
    retry = _forbid_retry(monkeypatch)

    result = tasks.daily_auto_trading_task.run(
        trade_date="2026-04-30", account_ids=[1, 2], invocation_key="outcome-engine-error-001"
    )

    assert result["outcome"] == "failed"
    assert result["success"] is False
    assert result["requested"] == 2
    assert result["succeeded"] == 0
    assert result["failed"] == 2
    assert result["stored"] is None
    assert result["counts_unavailable"] is True
    assert all(account["issues"][0]["effects_indeterminate"] for account in result["accounts"])
    engine.run_daily_trading.assert_called_once()
    retry.assert_not_called()


def test_default_scope_is_frozen_before_engine_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    engine.run_daily_trading.return_value = {
        4: AccountAutoTradingOutcome(account_id=4, buy_count=0, sell_count=0),
    }
    account_repository, engine_factory = _patch_task_dependencies(
        monkeypatch,
        engine,
        active_accounts=(
            _account(4, AccountType.SIMULATED),
            _account(9, AccountType.REAL),
        ),
    )
    _forbid_retry(monkeypatch)

    result = tasks.daily_auto_trading_task.run(trade_date="2026-04-30", invocation_key="test-run-1")

    account_repository.get_active_accounts.assert_called_once_with()
    engine.run_daily_trading.assert_called_once_with(tasks.date(2026, 4, 30), account_ids=[4])
    engine_factory.assert_called_once()
    assert result["requested"] == 1
    assert result["outcome"] == "noop"
    assert result["stored"] == 0


def test_default_scope_with_only_real_accounts_is_an_empty_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    account_repository, engine_factory = _patch_task_dependencies(
        monkeypatch,
        engine,
        active_accounts=(_account(9, AccountType.REAL),),
    )

    result = tasks.daily_auto_trading_task.run(
        trade_date="2026-04-30", invocation_key="outcome-real-only-001"
    )

    account_repository.get_active_accounts.assert_called_once_with()
    engine_factory.assert_not_called()
    engine.run_daily_trading.assert_not_called()
    assert result["outcome"] == "noop"
    assert (result["requested"], result["succeeded"], result["failed"], result["stored"]) == (
        0,
        0,
        0,
        0,
    )
    assert result["count_units"]["requested"] == "account"


def test_explicit_real_account_remains_in_scope_for_engine_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    engine.run_daily_trading.return_value = {
        9: AccountAutoTradingOutcome(
            account_id=9,
            buy_count=0,
            sell_count=0,
            issues=(
                AutoTradingIssue(
                    kind=AutoTradingIssueKind.BLOCKED,
                    stage="account",
                    code="AUTO_TRADING_ACCOUNT_TYPE_UNSUPPORTED",
                ),
            ),
        )
    }
    _patch_task_dependencies(monkeypatch, engine)

    result = tasks.daily_auto_trading_task.run(
        trade_date="2026-04-30", account_ids=[9], invocation_key="outcome-explicit-real-001"
    )

    engine.run_daily_trading.assert_called_once_with(tasks.date(2026, 4, 30), account_ids=[9])
    assert result["outcome"] == "blocked"
    assert result["requested"] == 1
    assert result["succeeded"] == 0
    assert result["failed"] == 1
    assert result["stored"] == 0
    assert result["accounts"][0]["issues"][0]["code"] == ("AUTO_TRADING_ACCOUNT_TYPE_UNSUPPORTED")


def test_default_scope_failure_does_not_invent_account_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_repository = SimpleNamespace(
        get_active_accounts=Mock(side_effect=RuntimeError("scope unavailable"))
    )
    monkeypatch.setattr(
        tasks,
        "get_simulated_account_repository",
        Mock(return_value=account_repository),
    )
    monkeypatch.setattr(
        tasks,
        "get_auto_invocation_repository",
        Mock(return_value=_MemoryInvocationRepository()),
    )
    monkeypatch.setattr(
        tasks,
        "build_auto_trading_engine",
        Mock(side_effect=AssertionError("must not be reached")),
    )

    class _ExhaustedTask:
        request = SimpleNamespace(retries=3)
        max_retries = 3

        def retry(self, *, exc: BaseException, countdown: int) -> BaseException:
            raise AssertionError("retries are exhausted")

    run_function = tasks.daily_auto_trading_task.run.__func__
    result = run_function(
        _ExhaustedTask(),
        trade_date="2026-04-30",
        invocation_key="test-run-2",
    )

    assert result["outcome"] == "failed"
    assert result["reason_code"] == "ACCOUNT_SCOPE_UNAVAILABLE"
    assert result["requested"] is None
    assert result["succeeded"] is None
    assert result["failed"] is None
    assert result["stored"] == 0
    assert result["counts_unavailable"] is True


def test_reporting_invalid_engine_mapping_preserves_typed_confirmed_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    engine.run_daily_trading.return_value = {
        1: AccountAutoTradingOutcome(account_id=1, buy_count=2, sell_count=0),
        "invalid-key": object(),
    }
    _patch_task_dependencies(monkeypatch, engine)
    retry = _forbid_retry(monkeypatch)

    result = tasks.daily_auto_trading_task.run(
        trade_date="2026-04-30", account_ids=[1, 2], invocation_key="outcome-invalid-map-001"
    )

    assert result["buy_count"] == 2
    assert result["confirmed_trade_count"] == 2
    assert result["counts_unavailable"] is True
    assert result["stored"] is None
    assert result["accounts"][0]["issues"][-1]["code"] == "TASK_RESULT_CONTRACT_INVALID"
    assert result["accounts"][1]["issues"][0]["effects_indeterminate"] is True
    engine.run_daily_trading.assert_called_once()
    retry.assert_not_called()


def test_unrequested_engine_result_makes_storage_count_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock()
    engine.run_daily_trading.return_value = {
        1: AccountAutoTradingOutcome(account_id=1, buy_count=2, sell_count=0),
        99: AccountAutoTradingOutcome(account_id=99, buy_count=1, sell_count=0),
    }
    _patch_task_dependencies(monkeypatch, engine)
    retry = _forbid_retry(monkeypatch)

    result = tasks.daily_auto_trading_task.run(
        trade_date="2026-04-30", account_ids=[1], invocation_key="outcome-extra-result-001"
    )

    assert result["buy_count"] == 2
    assert result["confirmed_trade_count"] == 2
    assert result["stored"] is None
    assert result["counts_unavailable"] is True
    assert result["accounts"][0]["issues"][-1] == {
        "kind": "failed",
        "stage": "task_result",
        "code": "TASK_RESULT_CONTRACT_INVALID",
        "asset_code": None,
        "effects_indeterminate": True,
    }
    retry.assert_not_called()


def test_engine_mapping_read_failure_becomes_unknown_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenResultMapping(Mapping[int, AccountAutoTradingOutcome]):
        def __getitem__(self, key: int) -> AccountAutoTradingOutcome:
            if key != 1:
                raise KeyError(key)
            return AccountAutoTradingOutcome(account_id=1, buy_count=2, sell_count=0)

        def __iter__(self) -> Iterator[int]:
            return iter((1,))

        def __len__(self) -> int:
            return 1

        def items(self) -> ItemsView[int, AccountAutoTradingOutcome]:
            raise RuntimeError("mapping iteration failed")

    engine = Mock()
    engine.run_daily_trading.return_value = _BrokenResultMapping()
    _patch_task_dependencies(monkeypatch, engine)
    retry = _forbid_retry(monkeypatch)

    result = tasks.daily_auto_trading_task.run(
        trade_date="2026-04-30", account_ids=[1], invocation_key="outcome-mapping-read-001"
    )

    assert result["outcome"] == "failed"
    assert result["buy_count"] == 0
    assert result["confirmed_trade_count"] == 0
    assert result["stored"] is None
    assert result["counts_unavailable"] is True
    assert result["accounts"][0]["issues"][0]["code"] == "EXECUTION_RESULT_UNKNOWN"
    retry.assert_not_called()


def test_engine_mapping_iteration_failure_preserves_already_read_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = AccountAutoTradingOutcome(account_id=1, buy_count=1, sell_count=0)

    class _PartialIterationMapping(Mapping[int, AccountAutoTradingOutcome]):
        def __getitem__(self, key: int) -> AccountAutoTradingOutcome:
            if key != 1:
                raise KeyError(key)
            return outcome

        def __iter__(self) -> Iterator[int]:
            yield 1
            raise RuntimeError("mapping iteration failed after one account")

        def __len__(self) -> int:
            return 2

    engine = Mock()
    engine.run_daily_trading.return_value = _PartialIterationMapping()
    _patch_task_dependencies(monkeypatch, engine)
    retry = _forbid_retry(monkeypatch)

    result = tasks.daily_auto_trading_task.run(
        trade_date="2026-04-30", account_ids=[1, 2], invocation_key="outcome-mapping-iterate-001"
    )

    assert result["outcome"] == "partial"
    assert result["buy_count"] == 1
    assert result["confirmed_trade_count"] == 1
    assert result["stored"] is None
    assert result["accounts"][0]["issues"][-1]["effects_indeterminate"] is True
    assert result["accounts"][1]["issues"][0]["code"] == "EXECUTION_RESULT_UNKNOWN"
    retry.assert_not_called()


def test_empty_scope_is_noop_without_constructing_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_repository, engine_factory = _patch_task_dependencies(monkeypatch, Mock())
    _forbid_retry(monkeypatch)

    result = tasks.daily_auto_trading_task.run(
        trade_date="2026-04-30", account_ids=[], invocation_key="outcome-empty-scope-001"
    )

    assert result["outcome"] == "noop"
    assert result["requested"] == 0
    assert result["stored"] == 0
    account_repository.get_active_accounts.assert_not_called()
    engine_factory.assert_not_called()


def test_api_application_scope_rejects_bad_date_and_oversize_before_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_engine = Mock()
    monkeypatch.setattr(interface_services, "build_auto_trading_engine", build_engine)

    with pytest.raises(ValueError, match="trade_date"):
        interface_services.run_auto_trading_for_scope(
            trade_date=cast(date, datetime(2026, 4, 30, tzinfo=UTC)),
            account_ids=(1,),
        )
    with pytest.raises(ValueError, match="account_ids"):
        interface_services.run_auto_trading_for_scope(
            trade_date=date(2026, 4, 30),
            account_ids=tuple(range(1, interface_services.MAX_AUTO_TRADING_ACCOUNT_SCOPE_SIZE + 2)),
        )

    build_engine.assert_not_called()


def test_api_engine_builder_injects_execution_link_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "get_simulated_account_repository",
        "get_simulated_position_repository",
        "get_simulated_trade_repository",
        "get_signal_repository",
        "get_asset_pool_query_repository",
        "GetAccountPerformanceUseCase",
        "AssetPoolQueryService",
        "build_decision_rhythm_exit_advisor",
    ):
        monkeypatch.setattr(interface_services, name, Mock(return_value=object()))
    invocation_id = UUID("06eaad8e-37b0-4c44-a310-e154b1453b7e")
    bridge = SimpleNamespace(
        buy_use_case=object(),
        sell_use_case=object(),
        price_provider=object(),
    )
    bridge_factory = Mock(return_value=bridge)
    monkeypatch.setattr(interface_services, "get_automatic_trade_execution_bridge", bridge_factory)
    recorder = object()
    monkeypatch.setattr(
        interface_services,
        "build_decision_execution_link_recorder",
        Mock(return_value=recorder),
    )
    engine_factory = Mock(side_effect=lambda **kwargs: kwargs)
    monkeypatch.setattr(interface_services, "AutoTradingEngine", engine_factory)

    engine_args = interface_services.build_auto_trading_engine(invocation_id=invocation_id)

    bridge_factory.assert_called_once_with(invocation_id)
    assert engine_args["buy_use_case"] is bridge.buy_use_case
    assert engine_args["sell_use_case"] is bridge.sell_use_case
    assert engine_args["price_provider"] is bridge.price_provider
    assert engine_args["execution_link_recorder"] is recorder


def test_pre_engine_assembly_failure_can_still_schedule_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RetryingTask:
        request = SimpleNamespace(retries=0)
        max_retries = 3

        def retry(self, *, exc: BaseException, countdown: int) -> BaseException:
            assert isinstance(exc, RuntimeError)
            assert countdown == 60
            return Retry("pre-engine retry")

    monkeypatch.setattr(
        tasks,
        "get_simulated_account_repository",
        Mock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        tasks,
        "get_auto_invocation_repository",
        Mock(return_value=_MemoryInvocationRepository()),
    )
    monkeypatch.setattr(
        tasks,
        "build_auto_trading_engine",
        Mock(side_effect=RuntimeError("setup unavailable")),
    )
    run_function = tasks.daily_auto_trading_task.run.__func__

    with pytest.raises(Retry):
        run_function(
            _RetryingTask(),
            trade_date="2026-04-30",
            account_ids=[1],
            invocation_key="outcome-retry-setup-001",
        )


def test_pre_engine_failure_after_retry_exhaustion_has_known_zero_write_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tasks,
        "get_simulated_account_repository",
        Mock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        tasks,
        "get_auto_invocation_repository",
        Mock(return_value=_MemoryInvocationRepository()),
    )
    monkeypatch.setattr(
        tasks,
        "build_auto_trading_engine",
        Mock(side_effect=RuntimeError("setup unavailable")),
    )

    class _ExhaustedTask:
        request = SimpleNamespace(retries=3)
        max_retries = 3

        def retry(self, *, exc: BaseException, countdown: int) -> BaseException:
            raise AssertionError("retries are exhausted")

    run_function = tasks.daily_auto_trading_task.run.__func__
    result = run_function(
        _ExhaustedTask(),
        trade_date="2026-04-30",
        account_ids=[1, 2],
        invocation_key="outcome-retry-exhausted-001",
    )

    assert result["outcome"] == "failed"
    assert result["requested"] == 2
    assert result["succeeded"] == 0
    assert result["failed"] == 2
    assert result["stored"] == 0
    assert result["counts_unavailable"] is False
    assert all(
        account["issues"][0]["code"] == "TASK_SETUP_FAILED" for account in result["accounts"]
    )
