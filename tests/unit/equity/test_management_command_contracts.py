"""Equity bootstrap, sync, and scheduler command contracts."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management.base import CommandError

from apps.equity.management.commands import (
    init_equity_config,
    init_scoring_weights,
    setup_equity_valuation_sync,
    sync_equity_financial,
    sync_equity_valuation,
    validate_equity_valuation_quality,
)


def test_equity_config_bootstrap_publishes_all_database_driven_defaults(monkeypatch) -> None:
    """Bootstrap delegates every regime rule and preference to its repository."""
    monkeypatch.setattr(init_equity_config.transaction, "atomic", nullcontext)
    calls: dict[str, list[dict[str, object]]] = {
        "rules": [],
        "sectors": [],
        "funds": [],
    }
    overwrite_flags: list[bool] = []

    def _record(
        category: str,
        payload: dict[str, object],
        *,
        overwrite: bool,
    ) -> str:
        calls[category].append(payload)
        overwrite_flags.append(overwrite)
        return "created"

    repository = SimpleNamespace(
        upsert_stock_screening_rule=lambda payload, *, overwrite: _record(
            "rules", payload, overwrite=overwrite
        ),
        upsert_sector_preference=lambda payload, *, overwrite: _record(
            "sectors", payload, overwrite=overwrite
        ),
        upsert_fund_type_preference=lambda payload, *, overwrite: _record(
            "funds", payload, overwrite=overwrite
        ),
    )
    command = init_equity_config.Command(stdout=StringIO())
    command._get_repository = lambda: repository
    command.handle(force=False)
    assert len(calls["rules"]) == 4
    assert len(calls["sectors"]) == 13
    assert len(calls["funds"]) == 7
    assert overwrite_flags == [False] * 24
    assert {item["regime"] for item in calls["rules"]} == {
        "Recovery",
        "Overheat",
        "Stagflation",
        "Deflation",
    }
    assert "created=24" in command.stdout.getvalue()


def test_equity_config_bootstrap_rejects_non_boolean_force_before_repository() -> None:
    """Dynamic callers cannot enable destructive overwrite with a truthy value."""

    command = init_equity_config.Command(stdout=StringIO())
    command._get_repository = lambda: pytest.fail("repository constructed")

    with pytest.raises(CommandError, match="--force"):
        command.handle(force="true")


def test_equity_interface_package_does_not_publish_bootstrap_business_logic() -> None:
    """The Interface package root remains free of management-command behavior."""

    from apps.equity import interface

    assert not hasattr(interface, "Command")
    assert not hasattr(interface, "init_stock_screening_rules")


def test_legacy_equity_config_script_delegates_to_management_command(monkeypatch) -> None:
    """The compatibility script contains no independent bootstrap implementation."""

    import django
    from django.core import management

    from scripts import init_equity_config as script

    calls: list[str] = []
    monkeypatch.setattr(django, "setup", lambda: None)
    monkeypatch.setattr(management, "call_command", lambda name: calls.append(name))

    script.main()

    assert calls == ["init_equity_config"]


class _ScoringManager:
    def __init__(self, *, count: int = 0) -> None:
        self.existing_count = count
        self.current_name = ""
        self.created: list[str] = []

    def count(self) -> int:
        return self.existing_count

    def filter(self, **kwargs: object) -> _ScoringManager:
        self.current_name = str(kwargs["name"])
        return self

    def exists(self) -> bool:
        return self.current_name == "成长型配置"

    def create(self, **kwargs: object) -> object:
        if kwargs["name"] == "价值型配置":
            raise RuntimeError("constraint")
        self.created.append(str(kwargs["name"]))
        return object()


def test_scoring_weight_command_covers_cancel_skip_create_and_error(monkeypatch) -> None:
    """Scoring defaults remain idempotent and isolate one invalid database row."""
    manager = _ScoringManager(count=1)
    monkeypatch.setattr(
        init_scoring_weights,
        "ScoringWeightConfigModel",
        SimpleNamespace(_default_manager=manager),
    )
    cancelled = init_scoring_weights.Command(stdout=StringIO())
    monkeypatch.setattr(cancelled, "confirm", lambda message: False)
    cancelled.handle()
    assert manager.created == []

    command = init_scoring_weights.Command(stdout=StringIO())
    monkeypatch.setattr(command, "confirm", lambda message: True)
    command.handle()
    assert manager.created == ["默认配置"]
    output = command.stdout.getvalue()
    assert '成长型配置" 已存在' in output
    assert '价值型配置" 失败' in output

    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert command.confirm("continue") is True


def test_financial_sync_command_handles_empty_success_and_provider_error(monkeypatch) -> None:
    """Financial sync rejects an empty universe and isolates per-stock provider failures."""

    class _Stocks(list):
        def exists(self) -> bool:
            return bool(self)

        def filter(self, **kwargs: object) -> _Stocks:
            return self

        def order_by(self, *args: object) -> _Stocks:
            return self

    empty = _Stocks()
    monkeypatch.setattr(
        sync_equity_financial,
        "StockInfoModel",
        SimpleNamespace(objects=empty),
    )
    with pytest.raises(CommandError, match="没有找到"):
        sync_equity_financial.Command(stdout=StringIO()).handle(
            stock_codes=None,
            periods=4,
            source="akshare",
        )

    stocks = _Stocks(
        [
            SimpleNamespace(stock_code="000001.SZ"),
            SimpleNamespace(stock_code="600000.SH"),
        ]
    )
    monkeypatch.setattr(
        sync_equity_financial,
        "StockInfoModel",
        SimpleNamespace(objects=stocks),
    )
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(
        sync_equity_financial,
        "FinancialDataModel",
        SimpleNamespace(
            objects=SimpleNamespace(update_or_create=lambda **kwargs: saved.append(kwargs))
        ),
    )
    record = SimpleNamespace(
        stock_code="000001.SZ",
        report_date=date(2026, 6, 30),
        report_type="quarterly",
        revenue=1,
        net_profit=1,
        revenue_growth=1,
        net_profit_growth=1,
        total_assets=1,
        total_liabilities=1,
        equity=1,
        roe=1,
        roa=1,
        debt_ratio=1,
    )

    class _Gateway:
        def fetch(self, stock_code: str, periods: int):
            if stock_code.startswith("600"):
                raise RuntimeError("provider offline")
            return SimpleNamespace(records=[record])

    monkeypatch.setattr(sync_equity_financial, "AKShareFinancialGateway", _Gateway)
    output = StringIO()
    errors = StringIO()
    sync_equity_financial.Command(stdout=output, stderr=errors).handle(
        stock_codes=["000001.SZ", "600000.SH"],
        periods=4,
        source="akshare",
    )
    assert len(saved) == 1
    assert "1 records, 1 errors" in output.getvalue()
    assert "provider offline" not in errors.getvalue()
    assert "RuntimeError" in errors.getvalue()


def test_valuation_sync_and_quality_commands_map_success_and_failure(monkeypatch) -> None:
    """Valuation commands map request dates and turn use-case failures into CommandError."""
    sync_requests: list[object] = []

    class _SyncUseCase:
        def __init__(self, **kwargs: object) -> None:
            pass

        def execute(self, request: object):
            sync_requests.append(request)
            return SimpleNamespace(success=True, error="", data={"synced": 3})

    monkeypatch.setattr(sync_equity_valuation, "SyncEquityValuationUseCase", _SyncUseCase)
    command = sync_equity_valuation.Command(stdout=StringIO())
    command.handle(
        start_date="2026-07-01",
        end_date="2026-07-24",
        days_back=1,
        stock_codes=["000001.SZ"],
        primary_source="akshare",
        fallback_source="tushare",
    )
    assert sync_requests[0].start_date == date(2026, 7, 1)
    assert "synced: 3" in command.stdout.getvalue()

    class _FailedSync(_SyncUseCase):
        def execute(self, request: object):
            return SimpleNamespace(success=False, error="database-password=private", data={})

    monkeypatch.setattr(sync_equity_valuation, "SyncEquityValuationUseCase", _FailedSync)
    with pytest.raises(CommandError, match="Equity valuation sync failed") as sync_error:
        sync_equity_valuation.Command(stdout=StringIO()).handle(
            start_date=None,
            end_date="2026-07-24",
            days_back=2,
            stock_codes=None,
            primary_source="akshare",
            fallback_source="tushare",
        )
    assert "database-password" not in str(sync_error.value)

    class _Quality:
        def __init__(self, **kwargs: object) -> None:
            pass

        def execute(self, request: object):
            return SimpleNamespace(success=True, error="", data={"coverage": 0.99})

    monkeypatch.setattr(
        validate_equity_valuation_quality,
        "ValidateEquityValuationQualityUseCase",
        _Quality,
    )
    quality = validate_equity_valuation_quality.Command(stdout=StringIO())
    quality.handle(date="2026-07-24", primary_source="akshare")
    assert "coverage" in quality.stdout.getvalue()

    class _FailedQuality(_Quality):
        def execute(self, request: object):
            return SimpleNamespace(success=False, error="database-password=private", data={})

    monkeypatch.setattr(
        validate_equity_valuation_quality,
        "ValidateEquityValuationQualityUseCase",
        _FailedQuality,
    )
    with pytest.raises(
        CommandError,
        match="Equity valuation quality validation failed",
    ) as quality_error:
        validate_equity_valuation_quality.Command(stdout=StringIO()).handle(
            date=None,
            primary_source="akshare",
        )
    assert "database-password" not in str(quality_error.value)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"start_date": "2026-02-30"}, "YYYY-MM-DD"),
        ({"days_back": True}, "days-back"),
        ({"stock_codes": "000001.SZ"}, "stock-code"),
    ),
)
def test_valuation_sync_command_rejects_invalid_dynamic_options(
    kwargs: dict[str, object],
    message: str,
) -> None:
    options: dict[str, object] = {
        "start_date": None,
        "end_date": None,
        "days_back": 1,
        "stock_codes": None,
        "primary_source": "akshare",
        "fallback_source": "tushare",
    }
    options.update(kwargs)

    with pytest.raises(CommandError, match=message):
        sync_equity_valuation.Command(stdout=StringIO()).handle(**options)


def test_equity_valuation_scheduler_configures_three_task_shapes(monkeypatch) -> None:
    """Scheduler command owns one daily cadence and one freshness interval."""
    tasks: dict[str, object] = {}
    monkeypatch.setattr(
        setup_equity_valuation_sync.transaction,
        "atomic",
        nullcontext,
    )

    class _Task:
        def __init__(self, name: str) -> None:
            self.name = name

        def save(self) -> None:
            tasks[self.name] = self

    manager = SimpleNamespace(get_or_create=lambda name: (_Task(name), name not in tasks))
    monkeypatch.setattr(
        setup_equity_valuation_sync.PeriodicTask,
        "objects",
        manager,
    )
    monkeypatch.setattr(
        setup_equity_valuation_sync.CrontabSchedule,
        "objects",
        SimpleNamespace(get_or_create=lambda **kwargs: (SimpleNamespace(), True)),
    )
    monkeypatch.setattr(
        setup_equity_valuation_sync.IntervalSchedule,
        "objects",
        SimpleNamespace(get_or_create=lambda **kwargs: (SimpleNamespace(), True)),
    )
    output = StringIO()
    setup_equity_valuation_sync.Command(stdout=output).handle(
        disable=False,
        hour=21,
        minute=30,
    )
    assert set(tasks) == {
        "equity-valuation-daily-sync",
        "equity-valuation-quality-validate",
        "equity-valuation-freshness-check",
    }
    assert all(task.enabled for task in tasks.values())
    assert "21:30" in output.getvalue()


@pytest.mark.parametrize(
    ("hour", "minute", "message"),
    ((24, 0, "hour"), (0, 60, "minute"), (True, 0, "hour")),
)
def test_equity_valuation_scheduler_rejects_invalid_time(
    hour: object,
    minute: object,
    message: str,
) -> None:
    with pytest.raises(CommandError, match=message):
        setup_equity_valuation_sync.Command(stdout=StringIO()).handle(
            disable=False,
            hour=hour,
            minute=minute,
        )
