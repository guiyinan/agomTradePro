"""Normalized Celery outcome contracts for simulated-trading maintenance tasks."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from apps.simulated_trading.application import tasks


def test_parameterized_tasks_reject_invalid_input_before_dependency_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Beat and CLI callers cannot bypass task-boundary validation."""

    def _unexpected_dependency() -> object:
        raise AssertionError("dependency must not be reached")

    monkeypatch.setattr(tasks, "get_simulated_account_repository", _unexpected_dependency)
    monkeypatch.setattr(tasks, "execute_realtime_price_polling", _unexpected_dependency)

    results = [
        tasks.daily_auto_trading_task.run(trade_date="not-a-date", account_ids=[1]),
        tasks.update_position_prices_task.run(account_id=True),
        tasks.calculate_all_performance_task.run(trade_date="not-a-date"),
        tasks.cleanup_inactive_accounts_task.run(inactive_days=True),
        tasks.send_performance_summary_task.run(account_ids=[True]),
        tasks.daily_portfolio_inspection_task.run(
            account_id=1,
            strategy_id=2,
            inspection_date="not-a-date",
        ),
        tasks.update_all_prices_after_close.run(account_id=True),
    ]

    assert [result["outcome"] for result in results] == ["failed"] * len(results)
    assert all(result["success"] is False for result in results)
    assert all(result["requested"] == 1 for result in results)
    assert all(result["succeeded"] == 0 for result in results)
    assert all(result["failed"] == 1 for result in results)
    assert all(result["stored"] == 0 for result in results)

    scoped_polling = tasks.update_all_prices_after_close.run(account_id=7)
    assert scoped_polling["outcome"] == "blocked"
    assert scoped_polling["success"] is False
    assert scoped_polling["reason"] == "account_scoped_realtime_polling_unavailable"


def test_performance_batch_reports_partial_and_complete_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-account failures remain visible in the aggregate business result."""
    accounts = [
        SimpleNamespace(account_id=1, account_name="one"),
        SimpleNamespace(account_id=2, account_name="two"),
    ]

    class _Calculator:
        fail_all = False

        def calculate_and_update_performance(
            self,
            *,
            account_id: int,
            trade_date: object,
        ) -> dict[str, float]:
            del trade_date
            if self.fail_all or account_id == 2:
                raise RuntimeError("performance unavailable")
            return {}

    calculator = _Calculator()
    monkeypatch.setattr(tasks, "PerformanceCalculator", lambda: calculator)
    monkeypatch.setattr(
        tasks,
        "get_simulated_account_repository",
        lambda: SimpleNamespace(get_active_accounts=lambda: accounts),
    )

    partial = tasks.calculate_all_performance_task.run("2026-08-11")
    assert partial["outcome"] == "partial"
    assert partial["success"] is True
    assert (partial["requested"], partial["succeeded"], partial["failed"], partial["stored"]) == (
        2,
        1,
        1,
        1,
    )

    calculator.fail_all = True
    failed = tasks.calculate_all_performance_task.run("2026-08-11")
    assert failed["outcome"] == "failed"
    assert failed["success"] is False
    assert (failed["requested"], failed["succeeded"], failed["failed"], failed["stored"]) == (
        2,
        0,
        2,
        0,
    )


def test_maintenance_and_inspection_publish_noop_blocked_and_success_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero mutation and business gates are not presented as ordinary success."""
    account_repo = SimpleNamespace(
        get_active_accounts=lambda: [],
        get_by_id=lambda account_id: None,
    )
    monkeypatch.setattr(tasks, "get_simulated_account_repository", lambda: account_repo)

    cleanup = tasks.cleanup_inactive_accounts_task.run(inactive_days=30)
    assert cleanup["outcome"] == "noop"
    assert (cleanup["requested"], cleanup["succeeded"], cleanup["failed"], cleanup["stored"]) == (
        0,
        0,
        0,
        0,
    )

    missing_config = tasks.daily_portfolio_inspection_task.run()
    assert missing_config["outcome"] == "blocked"
    assert missing_config["stored"] == 0

    missing_account = tasks.daily_portfolio_inspection_task.run(account_id=7, strategy_id=9)
    assert missing_account["outcome"] == "blocked"
    assert missing_account["stored"] == 0


def test_price_cleanup_and_inspection_success_count_actual_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation tasks count saved records independently from processed work items."""

    def _replace(value: object, **changes: object) -> SimpleNamespace:
        fields = vars(value).copy()
        fields.update(changes)
        return SimpleNamespace(**fields)

    monkeypatch.setattr(tasks, "replace", _replace)
    account = SimpleNamespace(
        account_id=1,
        account_name="one",
        current_cash=100.0,
        current_market_value=10.0,
        total_value=110.0,
        last_trade_date=date(2020, 1, 1),
        is_active=True,
        auto_trading_enabled=True,
    )
    position = SimpleNamespace(
        account_id=1,
        asset_code="510300.SH",
        asset_type="fund",
        quantity=2.0,
        avg_cost=9.0,
        current_price=10.0,
        market_value=20.0,
    )

    class _AccountRepository:
        def __init__(self) -> None:
            self.saved: list[object] = []

        def get_by_id(self, account_id: int) -> object | None:
            return account if account_id == 1 else None

        def get_active_accounts(self) -> list[object]:
            return [account]

        def save(self, value: object) -> None:
            self.saved.append(value)

    class _PositionRepository:
        def __init__(self) -> None:
            self.current = position
            self.saved: list[object] = []

        def get_by_account(self, account_id: int) -> list[object]:
            assert account_id == 1
            return [self.current]

        def save(self, value: object) -> None:
            self.current = value
            self.saved.append(value)

    account_repo = _AccountRepository()
    position_repo = _PositionRepository()
    monkeypatch.setattr(tasks, "get_simulated_account_repository", lambda: account_repo)
    monkeypatch.setattr(tasks, "get_simulated_position_repository", lambda: position_repo)
    monkeypatch.setattr(
        tasks,
        "UnifiedPriceService",
        lambda: SimpleNamespace(require_latest_price=lambda *args, **kwargs: 11.0),
    )

    price_result = tasks.update_position_prices_task.run(account_id=1)
    assert price_result["outcome"] == "success"
    assert (
        price_result["requested"],
        price_result["succeeded"],
        price_result["failed"],
        price_result["stored"],
    ) == (1, 1, 0, 2)
    assert len(position_repo.saved) == 1
    assert len(account_repo.saved) == 1

    account_repo.saved.clear()
    cleanup_result = tasks.cleanup_inactive_accounts_task.run(inactive_days=30)
    assert cleanup_result["outcome"] == "success"
    assert (
        cleanup_result["requested"],
        cleanup_result["succeeded"],
        cleanup_result["failed"],
        cleanup_result["stored"],
    ) == (1, 1, 0, 1)
    assert len(account_repo.saved) == 1

    inspection_evidence = {
        "account_id": 1,
        "report_id": 41,
        "status": "ok",
        "proposal_created": False,
        "proposal_id": None,
    }
    monkeypatch.setattr(
        tasks.DailyInspectionService,
        "run_and_create_proposal",
        lambda **kwargs: inspection_evidence,
    )
    monkeypatch.setattr(tasks, "_send_daily_inspection_email", lambda **kwargs: None)
    monkeypatch.setattr(tasks, "_send_rebalance_proposal_notification", lambda **kwargs: None)

    inspection_result = tasks.daily_portfolio_inspection_task.run(account_id=1, strategy_id=2)
    assert inspection_result["outcome"] == "success"
    assert (
        inspection_result["requested"],
        inspection_result["succeeded"],
        inspection_result["failed"],
        inspection_result["stored"],
    ) == (1, 1, 0, 1)


def test_invalidation_and_price_polling_failures_have_stable_task_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider and malformed polling evidence become explicit task failures."""
    from apps.simulated_trading.application import position_invalidation_checker

    monkeypatch.setattr(
        position_invalidation_checker,
        "check_and_invalidate_positions",
        lambda: (_ for _ in ()).throw(RuntimeError("checker offline")),
    )
    monkeypatch.setattr(
        position_invalidation_checker,
        "get_invalidated_positions_summary",
        lambda: (_ for _ in ()).throw(RuntimeError("summary offline")),
    )
    monkeypatch.setattr(
        tasks,
        "execute_realtime_price_polling",
        lambda: {
            "total_assets": 3,
            "success_count": 1,
            "failed_count": 2,
            "success_rate": 1 / 3,
        },
    )

    check_result = tasks.check_position_invalidation_task.run()
    notify_result = tasks.notify_invalidated_positions_task.run()
    price_result = tasks.update_all_prices_after_close.run()

    assert check_result["outcome"] == "failed"
    assert notify_result["outcome"] == "failed"
    assert price_result["outcome"] == "partial"
    assert price_result["success"] is True
    assert (
        price_result["requested"],
        price_result["succeeded"],
        price_result["failed"],
        price_result["stored"],
    ) == (3, 1, 2, 1)


def test_compatibility_aliases_delegate_exactly_to_canonical_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy names remain argument-preserving wrappers, not duplicate business tasks."""
    calls: list[tuple[str, dict[str, object]]] = []

    def _runner(name: str):
        def _run(**kwargs: object) -> dict[str, object]:
            calls.append((name, kwargs))
            return {"outcome": "noop", "name": name}

        return _run

    pairs = [
        (tasks.update_position_prices_task, "prices"),
        (tasks.calculate_all_performance_task, "performance"),
        (tasks.cleanup_inactive_accounts_task, "cleanup"),
        (tasks.send_performance_summary_task, "summary"),
        (tasks.check_position_invalidation_task, "check"),
        (tasks.notify_invalidated_positions_task, "notify"),
    ]
    for canonical, name in pairs:
        monkeypatch.setattr(canonical, "run", _runner(name))

    assert tasks.update_position_prices_task_alias.run(account_id=3)["name"] == "prices"
    assert tasks.calculate_all_performance_task_alias.run(trade_date="2026-08-11")["name"] == (
        "performance"
    )
    assert tasks.cleanup_inactive_accounts_task_alias.run(inactive_days=45)["name"] == "cleanup"
    assert tasks.send_performance_summary_task_alias.run(account_ids=[3])["name"] == "summary"
    assert tasks.check_position_invalidation_task_alias.run()["name"] == "check"
    assert tasks.notify_invalidated_positions_task_alias.run()["name"] == "notify"
    assert calls == [
        ("prices", {"account_id": 3}),
        ("performance", {"trade_date": "2026-08-11"}),
        ("cleanup", {"inactive_days": 45}),
        ("summary", {"account_ids": [3]}),
        ("check", {}),
        ("notify", {}),
    ]
