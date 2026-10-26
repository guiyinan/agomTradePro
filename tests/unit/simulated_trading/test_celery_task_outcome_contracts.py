"""Normalized Celery outcome contracts for simulated-trading maintenance tasks."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.data_center.application.price_service import PriceLookupResult
from apps.simulated_trading.application import performance_calculator as calculator_module
from apps.simulated_trading.application import (
    position_price_refresh,
    tasks,
)
from apps.simulated_trading.application.ports import PositionPriceRefreshInput
from core.exceptions import DataFetchError


def test_parameterized_tasks_reject_invalid_input_before_dependency_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Beat and CLI callers cannot bypass task-boundary validation."""

    def _unexpected_dependency() -> object:
        raise AssertionError("dependency must not be reached")

    monkeypatch.setattr(tasks, "get_simulated_account_repository", _unexpected_dependency)
    monkeypatch.setattr(tasks, "execute_realtime_price_polling", _unexpected_dependency)

    results = [
        tasks.daily_auto_trading_task.run(
            trade_date="not-a-date", account_ids=[1], invocation_key="invalid-date-boundary"
        ),
        tasks.update_position_prices_task.run(account_id=True),
        tasks.calculate_all_performance_task.run(trade_date="not-a-date"),
        tasks.calculate_all_performance_task.run(trade_date=""),
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


def test_performance_task_rejects_non_current_dates_before_dependency_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Historical current-value mismatch must fail before task setup reads data."""
    business_today = date(2026, 10, 25)
    dependency_calls: list[str] = []
    monkeypatch.setattr(
        calculator_module.timezone,
        "localdate",
        lambda value=None, timezone=None: business_today,
    )
    monkeypatch.setattr(
        tasks,
        "PerformanceCalculator",
        lambda: dependency_calls.append("calculator"),
    )
    monkeypatch.setattr(
        tasks,
        "get_simulated_account_repository",
        lambda: dependency_calls.append("account_repository"),
    )

    results = [
        tasks.calculate_all_performance_task.run("2026-10-24"),
        tasks.calculate_all_performance_task.run("2026-10-26"),
    ]

    for result in results:
        assert result["outcome"] == "failed"
        assert result["success"] is False
        assert (result["requested"], result["succeeded"], result["failed"], result["stored"]) == (
            1,
            0,
            1,
            0,
        )
        assert result["error_code"] == "PERFORMANCE_CURRENT_DATE_REQUIRED"
    assert dependency_calls == []


def test_performance_task_uses_configured_local_date_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omitted task dates use configured timezone even when active timezone is UTC."""
    instant = datetime(2026, 10, 25, 20, 15, tzinfo=UTC)
    monkeypatch.setattr(calculator_module.timezone, "now", lambda: instant)
    dependency_calls: list[str] = []
    monkeypatch.setattr(
        tasks,
        "PerformanceCalculator",
        lambda: dependency_calls.append("calculator") or object(),
    )
    monkeypatch.setattr(
        tasks,
        "get_simulated_account_repository",
        lambda: dependency_calls.append("account_repository")
        or SimpleNamespace(get_active_accounts=lambda: []),
    )

    with calculator_module.timezone.override(UTC):
        default_timezone = calculator_module.timezone.get_default_timezone()
        business_today = instant.astimezone(default_timezone).date()
        assert business_today == date(2026, 10, 26)
        previous_utc_date = instant.date()
        invalid = tasks.calculate_all_performance_task.run(previous_utc_date.isoformat())
        assert invalid["outcome"] == "failed"
        assert invalid["error_code"] == "PERFORMANCE_CURRENT_DATE_REQUIRED"
        assert dependency_calls == []

        result = tasks.calculate_all_performance_task.run()

    assert result["outcome"] == "noop"
    assert result["trade_date"] == business_today.isoformat()
    assert dependency_calls == ["calculator", "account_repository"]
    assert (result["requested"], result["succeeded"], result["failed"], result["stored"]) == (
        0,
        0,
        0,
        0,
    )


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
    monkeypatch.setattr(
        calculator_module.timezone,
        "localdate",
        lambda value=None, timezone=None: date(2026, 8, 11),
    )
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
    """Cleanup asks the repository to recheck status under the account lock."""
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
            self.deactivation_checks: list[tuple[int, date]] = []

        def get_by_id(self, account_id: int) -> object | None:
            return account if account_id == 1 else None

        def get_active_accounts(self) -> list[object]:
            return [account]

        def deactivate_if_inactive_since(self, account_id: int, cutoff_date: date) -> bool:
            self.deactivation_checks.append((account_id, cutoff_date))
            return account_id == 1

        def save(self, value: object) -> None:
            self.saved.append(value)

    class _PositionRepository:
        def __init__(self) -> None:
            self.current = position
            self.price_refresh_calls: list[tuple[int, dict[str, PositionPriceRefreshInput]]] = []

        def get_by_account(self, account_id: int) -> list[object]:
            assert account_id == 1
            return [self.current]

        def update_position_prices_for_account(
            self,
            account_id: int,
            price_by_code: dict[str, PositionPriceRefreshInput],
        ) -> int:
            self.price_refresh_calls.append((account_id, price_by_code))
            return 1

    account_repo = _AccountRepository()
    position_repo = _PositionRepository()
    monkeypatch.setattr(tasks, "get_simulated_account_repository", lambda: account_repo)
    monkeypatch.setattr(tasks, "get_simulated_position_repository", lambda: position_repo)
    monkeypatch.setattr(
        position_price_refresh,
        "get_simulated_account_repository",
        lambda: account_repo,
    )
    monkeypatch.setattr(
        position_price_refresh,
        "get_simulated_position_repository",
        lambda: position_repo,
    )
    source_observed_at = datetime(2020, 1, 1, tzinfo=UTC)

    class _PriceProvider:
        def require_latest_price_result(
            self,
            asset_code: str,
            asset_type: str | None = None,
        ) -> PriceLookupResult:
            assert asset_code == "510300.SH"
            assert asset_type == "fund"
            return PriceLookupResult(
                requested_code=asset_code,
                normalized_code=asset_code,
                price=11.0,
                as_of=None,
                source="Tushare",
                freshness="realtime",
                is_fallback=False,
                observed_at=source_observed_at,
            )

    monkeypatch.setattr(position_price_refresh, "UnifiedPriceService", _PriceProvider)

    price_result = tasks.update_position_prices_task.run(account_id=1)
    assert price_result["outcome"] == "success"
    assert (
        price_result["requested"],
        price_result["succeeded"],
        price_result["failed"],
        price_result["stored"],
    ) == (1, 1, 0, 2)
    assert position_repo.price_refresh_calls == [
        (
            1,
            {
                "510300.SH": PositionPriceRefreshInput(
                    asset_code="510300.SH",
                    asset_type="fund",
                    price=11.0,
                    source="Tushare",
                    freshness="realtime",
                    as_of=None,
                    observed_at=source_observed_at,
                )
            },
        )
    ]
    assert account_repo.saved == []

    cleanup_result = tasks.cleanup_inactive_accounts_task.run(inactive_days=30)
    assert cleanup_result["outcome"] == "success"
    assert (
        cleanup_result["requested"],
        cleanup_result["succeeded"],
        cleanup_result["failed"],
        cleanup_result["stored"],
    ) == (1, 1, 0, 1)
    assert account_repo.deactivation_checks == [(1, date.today() - timedelta(days=30))]
    assert account_repo.saved == []

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


def test_position_price_refresh_passes_source_evidence_to_account_scoped_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A qualified provider clock reaches only the atomic refresh repository."""
    account = SimpleNamespace(account_id=16)
    position = SimpleNamespace(
        account_id=16,
        asset_code="510300.SH",
        asset_type="fund",
        current_price=10.0,
    )
    source_observed_at = datetime(2026, 10, 24, 7, 30, tzinfo=UTC)

    class _AccountRepository:
        def __init__(self) -> None:
            self.saved: list[object] = []

        def get_by_id(self, account_id: int) -> SimpleNamespace | None:
            return account if account_id == account.account_id else None

        def save(self, account_value: object) -> None:
            self.saved.append(account_value)

    class _PositionRepository:
        def __init__(self) -> None:
            self.price_refresh_calls: list[tuple[int, dict[str, PositionPriceRefreshInput]]] = []

        def get_by_account(self, account_id: int) -> list[SimpleNamespace]:
            assert account_id == account.account_id
            return [position]

        def update_position_prices_for_account(
            self,
            account_id: int,
            price_by_code: dict[str, PositionPriceRefreshInput],
        ) -> int:
            self.price_refresh_calls.append((account_id, price_by_code))
            return len(price_by_code)

    class _PriceProvider:
        def require_latest_price_result(
            self,
            asset_code: str,
            asset_type: str | None = None,
        ) -> PriceLookupResult:
            assert asset_code == position.asset_code
            assert asset_type == position.asset_type
            return PriceLookupResult(
                requested_code=asset_code,
                normalized_code=asset_code,
                price=11.0,
                as_of=None,
                source="Tushare",
                freshness="realtime",
                is_fallback=False,
                observed_at=source_observed_at,
            )

    account_repo = _AccountRepository()
    position_repo = _PositionRepository()
    monkeypatch.setattr(
        position_price_refresh,
        "get_simulated_account_repository",
        lambda: account_repo,
    )
    monkeypatch.setattr(
        position_price_refresh,
        "get_simulated_position_repository",
        lambda: position_repo,
    )
    monkeypatch.setattr(position_price_refresh, "UnifiedPriceService", _PriceProvider)

    result = tasks.update_position_prices_task.run(account_id=account.account_id)

    assert result["outcome"] == "success"
    assert (result["requested"], result["succeeded"], result["failed"], result["stored"]) == (
        1,
        1,
        0,
        2,
    )
    assert position_repo.price_refresh_calls == [
        (
            16,
            {
                "510300.SH": PositionPriceRefreshInput(
                    asset_code="510300.SH",
                    asset_type="fund",
                    price=11.0,
                    source="Tushare",
                    freshness="realtime",
                    as_of=None,
                    observed_at=source_observed_at,
                )
            },
        )
    ]
    assert account_repo.saved == []


@pytest.mark.parametrize(
    ("cached_price", "expected_outcome", "expected_stored"),
    [(10.0, "success", 2), (0.0, "failed", 0)],
)
def test_position_price_refresh_cached_fallback_has_no_synthetic_provenance(
    monkeypatch: pytest.MonkeyPatch,
    cached_price: float,
    expected_outcome: str,
    expected_stored: int,
) -> None:
    """A provider failure never turns a cached numeric value into source evidence."""
    account = SimpleNamespace(account_id=17)
    position = SimpleNamespace(
        account_id=17,
        asset_code="510300.SH",
        asset_type="fund",
        current_price=cached_price,
    )

    class _AccountRepository:
        def get_by_id(self, account_id: int) -> SimpleNamespace | None:
            return account if account_id == account.account_id else None

    class _PositionRepository:
        def __init__(self) -> None:
            self.price_refresh_calls: list[tuple[int, dict[str, PositionPriceRefreshInput]]] = []

        def get_by_account(self, account_id: int) -> list[SimpleNamespace]:
            assert account_id == account.account_id
            return [position]

        def update_position_prices_for_account(
            self,
            account_id: int,
            price_by_code: dict[str, PositionPriceRefreshInput],
        ) -> int:
            self.price_refresh_calls.append((account_id, price_by_code))
            return len(price_by_code)

    class _UnavailablePriceProvider:
        def require_latest_price_result(
            self,
            asset_code: str,
            asset_type: str | None = None,
        ) -> PriceLookupResult:
            assert asset_code == position.asset_code
            assert asset_type == position.asset_type
            raise DataFetchError(
                "provider unavailable in fixture",
                details={"source": "unit fixture"},
            )

    account_repo = _AccountRepository()
    position_repo = _PositionRepository()
    monkeypatch.setattr(
        position_price_refresh,
        "get_simulated_account_repository",
        lambda: account_repo,
    )
    monkeypatch.setattr(
        position_price_refresh,
        "get_simulated_position_repository",
        lambda: position_repo,
    )
    monkeypatch.setattr(
        position_price_refresh,
        "UnifiedPriceService",
        _UnavailablePriceProvider,
    )

    result = tasks.update_position_prices_task.run(account_id=account.account_id)

    assert result["requested"] == 1
    assert result["outcome"] == expected_outcome
    assert result["stored"] == expected_stored
    if cached_price > 0:
        assert result["success"] is True
        assert (result["succeeded"], result["failed"], result["stored"]) == (1, 0, 2)
        assert result["warning_count"] == 1
        assert result["error_count"] == 0
        assert len(position_repo.price_refresh_calls) == 1
        input_row = position_repo.price_refresh_calls[0][1][position.asset_code]
        assert input_row.price == cached_price
        assert input_row.freshness == "cached"
        assert input_row.source is None
        assert input_row.as_of is None
        assert input_row.observed_at is None
    else:
        assert result["success"] is False
        assert result["succeeded"] == 0
        assert result["failed"] == 1
        assert result["stored"] == 0
        assert result["error_count"] == 1
        assert position_repo.price_refresh_calls == []


def test_position_price_refresh_reports_partial_when_one_account_has_no_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing price skips only its account and keeps aggregate counts exact."""
    accounts = [SimpleNamespace(account_id=17), SimpleNamespace(account_id=18)]
    positions = {
        17: SimpleNamespace(
            account_id=17,
            asset_code="510300.SH",
            asset_type="fund",
            current_price=0.0,
        ),
        18: SimpleNamespace(
            account_id=18,
            asset_code="159915.SZ",
            asset_type="fund",
            current_price=10.0,
        ),
    }
    source_observed_at = datetime(2020, 1, 1, tzinfo=UTC)

    class _AccountRepository:
        def __init__(self) -> None:
            self.saved: list[object] = []

        def get_active_accounts(self) -> list[SimpleNamespace]:
            return accounts

        def save(self, account: object) -> None:
            self.saved.append(account)

    class _PositionRepository:
        def __init__(self) -> None:
            self.price_refresh_calls: list[tuple[int, dict[str, PositionPriceRefreshInput]]] = []

        def get_by_account(self, account_id: int) -> list[SimpleNamespace]:
            return [positions[account_id]]

        def update_position_prices_for_account(
            self,
            account_id: int,
            price_by_code: dict[str, PositionPriceRefreshInput],
        ) -> int:
            self.price_refresh_calls.append((account_id, price_by_code))
            return len(price_by_code)

    class _PriceProvider:
        def require_latest_price_result(
            self,
            asset_code: str,
            asset_type: str | None = None,
        ) -> PriceLookupResult:
            assert asset_type == "fund"
            if asset_code == "510300.SH":
                raise DataFetchError("price unavailable", details={"asset_code": asset_code})
            return PriceLookupResult(
                requested_code=asset_code,
                normalized_code=asset_code,
                price=11.0,
                as_of=None,
                source="Tushare",
                freshness="realtime",
                is_fallback=False,
                observed_at=source_observed_at,
            )

    account_repo = _AccountRepository()
    position_repo = _PositionRepository()
    monkeypatch.setattr(
        position_price_refresh,
        "get_simulated_account_repository",
        lambda: account_repo,
    )
    monkeypatch.setattr(
        position_price_refresh,
        "get_simulated_position_repository",
        lambda: position_repo,
    )
    monkeypatch.setattr(position_price_refresh, "UnifiedPriceService", _PriceProvider)

    result = tasks.update_position_prices_task.run()

    assert result["outcome"] == "partial"
    assert result["success"] is True
    assert (result["requested"], result["succeeded"], result["failed"], result["stored"]) == (
        2,
        1,
        1,
        2,
    )
    assert result["error_count"] == 1
    assert result["errors"][0]["account_id"] == 17
    assert [account_id for account_id, _ in position_repo.price_refresh_calls] == [18]
    assert account_repo.saved == []


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
