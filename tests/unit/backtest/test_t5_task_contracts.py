"""Celery task orchestration and reporting contracts for backtests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.backtest.application import tasks
from core.exceptions import BusinessLogicError, ResourceNotFoundError


def _config() -> dict[str, object]:
    return {
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "initial_capital": 100000,
        "rebalance_frequency": "monthly",
        "transaction_cost_bps": 10.0,
    }


def test_run_backtest_task_persists_success_and_exercises_default_readers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MagicMock()
    repository.get_backtest_by_id.return_value = SimpleNamespace(id=7)
    monkeypatch.setattr(tasks, "get_backtest_repository", lambda: repository)
    snapshot = SimpleNamespace(
        dominant_regime="Recovery",
        confidence=0.8,
        growth_momentum_z=1.0,
        inflation_momentum_z=-0.2,
        distribution={"Recovery": 0.8},
    )
    monkeypatch.setattr(
        tasks,
        "build_default_regime_reader",
        lambda: lambda _date: {
            "dominant_regime": snapshot.dominant_regime,
            "confidence": snapshot.confidence,
        },
    )
    price_adapter = SimpleNamespace(get_price=lambda _asset, _date: 12.5)
    monkeypatch.setattr(
        tasks,
        "build_default_price_reader",
        MagicMock(return_value=price_adapter.get_price),
    )
    from shared.config import secrets

    monkeypatch.setattr(
        secrets,
        "get_secrets",
        lambda: SimpleNamespace(
            data_sources=SimpleNamespace(tushare_token="token", tushare_http_url="url")
        ),
    )

    result = SimpleNamespace(
        warnings=["sparse"],
        total_return=0.2,
        annualized_return=0.3,
        max_drawdown=-0.1,
        sharpe_ratio=1.5,
    )

    class FakeEngine:
        def __init__(self, **kwargs: object) -> None:
            self.regime_reader = kwargs["get_regime_func"]
            self.price_reader = kwargs["get_asset_price_func"]

        def run(self) -> SimpleNamespace:
            assert self.regime_reader(datetime.now(UTC).date())["dominant_regime"] == "Recovery"
            assert self.price_reader("equity", datetime.now(UTC).date()) == 12.5
            return result

    monkeypatch.setattr(tasks, "BacktestEngine", FakeEngine)

    response = tasks.run_backtest_task.run(7, _config())

    assert response["status"] == "completed"
    assert response["total_return"] == 0.2
    repository.update_status.assert_called_once_with(7, "running")
    repository.save_result.assert_called_once_with(7, result)


def test_run_backtest_task_returns_failed_outcome_for_missing_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MagicMock()
    repository.get_backtest_by_id.return_value = None
    monkeypatch.setattr(tasks, "get_backtest_repository", lambda: repository)

    with pytest.raises(ResourceNotFoundError, match="Backtest 404 not found"):
        tasks.run_backtest_task.run(404, _config())
    repository.update_status.assert_not_called()


def test_cleanup_old_backtests_deletes_only_completed_expired_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MagicMock()
    repository.delete_completed_before.return_value = 1
    monkeypatch.setattr(tasks, "get_backtest_repository", lambda: repository)

    assert tasks.cleanup_old_backtests.run(90) == 1
    repository.delete_completed_before.assert_called_once()
    assert repository.delete_completed_before.call_args.args[0] < timezone.now()


def test_generate_report_rejects_missing_or_incomplete_backtests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MagicMock()
    repository.get_backtest_by_id.return_value = None
    monkeypatch.setattr(tasks, "get_backtest_repository", lambda: repository)
    with pytest.raises(ResourceNotFoundError, match="Backtest 1 not found"):
        tasks.generate_backtest_report.run(1)

    repository.get_backtest_by_id.return_value = SimpleNamespace(status="running")
    with pytest.raises(BusinessLogicError, match="Backtest 1 is not completed"):
        tasks.generate_backtest_report.run(1)


def test_generate_report_and_analysis_helpers_summarize_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MagicMock()
    repository.get_backtest_by_id.return_value = SimpleNamespace(status="completed")
    domain_result = SimpleNamespace(
        to_summary_dict=lambda: {"total_return": 0.2},
        regime_history=[
            {"regime": "Recovery", "portfolio_value": 100},
            {"regime": "Recovery", "portfolio_value": 120},
            {"regime": "Single", "portfolio_value": 50},
            {"regime": "Zero", "portfolio_value": 0},
            {"regime": "Zero", "portfolio_value": 10},
        ],
        trades=[
            SimpleNamespace(action="buy", cost=1, notional=100),
            SimpleNamespace(action="sell", cost=2, notional=200),
        ],
        max_drawdown=-0.1,
        sharpe_ratio=1.5,
    )

    class FakeRepository:
        def get_backtest_by_id(self, backtest_id: int) -> SimpleNamespace:
            assert backtest_id == 1
            return repository.get_backtest_by_id(backtest_id)

        @staticmethod
        def to_domain_entity(backtest: SimpleNamespace) -> SimpleNamespace:
            assert backtest.status == "completed"
            return domain_result

    monkeypatch.setattr(tasks, "get_backtest_repository", FakeRepository)

    report = tasks.generate_backtest_report.run(1)

    assert report["summary"] == {"total_return": 0.2}
    assert report["regime_analysis"]["Recovery"]["total_return"] == 0.2
    assert report["regime_analysis"]["Zero"]["total_return"] == 0
    assert report["trade_analysis"]["cost_ratio"] == 0.01
    assert tasks._analyze_regime_performance([]) == {}
    assert tasks._analyze_trades([]) == {}
    zero_notional = [
        SimpleNamespace(action="buy", cost=1, notional=0),
    ]
    assert tasks._analyze_trades(zero_notional)["cost_ratio"] == 0
