"""Reliability and input-boundary tests for backtest Celery tasks."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.backtest.application import repository_provider, tasks
from apps.backtest.application.tasks import (
    _build_backtest_config,
    cleanup_old_backtests,
    run_backtest_task,
)
from apps.backtest.domain.entities import BacktestConfig
from apps.backtest.infrastructure.models import BacktestResultModel
from apps.backtest.infrastructure.repositories import DjangoBacktestRepository
from core.exceptions import InvalidInputError


def _config_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "initial_capital": 1_000_000.0,
        "rebalance_frequency": "monthly",
        "use_pit_data": False,
        "transaction_cost_bps": 10.0,
        "trust_status": "exploratory",
    }
    payload.update(overrides)
    return payload


class _BacktestRepository:
    def __init__(self) -> None:
        self.statuses: list[tuple[int, str, str | None]] = []
        self.saved_results: list[object] = []

    @staticmethod
    def get_backtest_by_id(backtest_id: int) -> object | None:
        return SimpleNamespace(id=backtest_id)

    def update_status(
        self,
        backtest_id: int,
        status: str,
        error_message: str | None = None,
    ) -> bool:
        self.statuses.append((backtest_id, status, error_message))
        return True

    def save_result(self, _backtest_id: int, result: object) -> bool:
        self.saved_results.append(result)
        return True


def test_runtime_failure_requests_retry_without_marking_result_failed(monkeypatch) -> None:
    repository = _BacktestRepository()
    retry_error = RuntimeError("retry requested")
    observed: dict[str, object] = {}

    class _FailingEngine:
        def __init__(self, **_kwargs: object) -> None:
            pass

        @staticmethod
        def run() -> object:
            raise ConnectionError("price source unavailable")

    def _retry(*, exc: BaseException, countdown: int) -> BaseException:
        observed["exc"] = exc
        observed["countdown"] = countdown
        return retry_error

    monkeypatch.setattr(tasks, "get_backtest_repository", lambda: repository)
    monkeypatch.setattr(tasks, "build_default_regime_reader", lambda: lambda _day: None)
    monkeypatch.setattr(
        tasks,
        "build_default_price_reader",
        lambda: lambda _asset, _day: None,
    )
    monkeypatch.setattr(tasks, "BacktestEngine", _FailingEngine)
    monkeypatch.setattr(run_backtest_task, "retry", _retry)

    with pytest.raises(RuntimeError, match="retry requested"):
        run_backtest_task.run(7, _config_payload())

    assert isinstance(observed["exc"], ConnectionError)
    assert observed["countdown"] == 60
    assert repository.statuses == [(7, "running", None)]
    assert repository.saved_results == []


def test_invalid_config_fails_permanently_and_marks_record_failed(monkeypatch) -> None:
    repository = _BacktestRepository()
    monkeypatch.setattr(tasks, "get_backtest_repository", lambda: repository)
    monkeypatch.setattr(
        run_backtest_task,
        "retry",
        lambda **_kwargs: pytest.fail("invalid task input must not retry"),
    )

    with pytest.raises(InvalidInputError, match="initial_capital"):
        run_backtest_task.run(7, _config_payload(initial_capital=float("nan")))

    assert repository.statuses == [(7, "failed", "initial_capital must be a finite number")]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("initial_capital", True),
        ("initial_capital", float("inf")),
        ("transaction_cost_bps", float("nan")),
        ("use_pit_data", 1),
    ],
)
def test_config_payload_rejects_noncanonical_values(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(InvalidInputError):
        _build_backtest_config(_config_payload(**{field_name: value}))


@pytest.mark.parametrize("days_old", [True, 0, -1, 3651])
def test_cleanup_rejects_unsafe_retention_without_querying(
    days_old: object,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        tasks,
        "get_backtest_repository",
        lambda: pytest.fail("invalid retention must not access the database"),
    )

    with pytest.raises(InvalidInputError, match="days_old"):
        cleanup_old_backtests.run(days_old=days_old)


def test_cleanup_uses_one_bulk_repository_delete(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class _CleanupRepository:
        @staticmethod
        def delete_completed_before(cutoff: datetime) -> int:
            observed["cutoff"] = cutoff
            return 12

    monkeypatch.setattr(
        tasks,
        "get_backtest_repository",
        lambda: _CleanupRepository(),
    )

    result = cleanup_old_backtests.run(days_old=90)
    assert result["deleted_count"] == 12
    assert result["outcome"] == "success"
    assert isinstance(observed["cutoff"], datetime)
    assert observed["cutoff"].tzinfo is not None


@pytest.mark.django_db
def test_bulk_cleanup_deletes_only_old_completed_backtests() -> None:
    def _create(name: str, status: str) -> BacktestResultModel:
        return BacktestResultModel.objects.create(
            name=name,
            status=status,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=1_000_000,
            rebalance_frequency="monthly",
        )

    old_completed = _create("old-completed", "completed")
    recent_completed = _create("recent-completed", "completed")
    old_failed = _create("old-failed", "failed")
    old_date = timezone.now() - timedelta(days=120)
    BacktestResultModel.objects.filter(id__in=[old_completed.id, old_failed.id]).update(
        created_at=old_date
    )

    deleted = DjangoBacktestRepository().delete_completed_before(
        timezone.now() - timedelta(days=90)
    )

    assert deleted == 1
    assert not BacktestResultModel.objects.filter(id=old_completed.id).exists()
    assert BacktestResultModel.objects.filter(id=recent_completed.id).exists()
    assert BacktestResultModel.objects.filter(id=old_failed.id).exists()


def test_default_price_reader_reuses_one_adapter(monkeypatch) -> None:
    created: list[object] = []
    calls: list[tuple[str, date]] = []

    class _Adapter:
        @staticmethod
        def get_price(asset_class: str, as_of_date: date) -> float:
            calls.append((asset_class, as_of_date))
            return 100.0

    def _factory(**_kwargs: object) -> _Adapter:
        adapter = _Adapter()
        created.append(adapter)
        return adapter

    monkeypatch.setattr(
        "shared.config.secrets.get_secrets",
        lambda: SimpleNamespace(
            data_sources=SimpleNamespace(tushare_token="", tushare_http_url="")
        ),
    )
    monkeypatch.setattr(repository_provider, "create_default_price_adapter", _factory)

    reader = repository_provider.build_default_price_reader()
    first_date = date(2025, 1, 1)
    second_date = date(2025, 2, 1)

    assert reader("gold", first_date) == 100.0
    assert reader("gold", second_date) == 100.0
    assert len(created) == 1
    assert calls == [("gold", first_date), ("gold", second_date)]


@pytest.mark.parametrize(
    ("initial_capital", "transaction_cost_bps"),
    [
        (float("nan"), 10.0),
        (float("inf"), 10.0),
        (1_000_000.0, float("-inf")),
    ],
)
def test_domain_config_rejects_nonfinite_financial_values(
    initial_capital: float,
    transaction_cost_bps: float,
) -> None:
    with pytest.raises(ValueError, match="finite"):
        BacktestConfig(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            initial_capital=initial_capital,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=transaction_cost_bps,
        )
