"""T5 safety and conversion contracts for the legacy USD migration command."""

from __future__ import annotations

from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.macro.management.commands import migrate_usd_data
from apps.macro.management.commands.migrate_usd_data import Command


def _command() -> Command:
    """Build a command with output capture."""
    command = Command()
    command.stdout = MagicMock()
    return command


def test_live_migration_requires_explicit_backup_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live migration must stop before data access without exact confirmation."""
    command = _command()
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    manager = MagicMock()
    monkeypatch.setattr(
        migrate_usd_data,
        "MacroIndicator",
        SimpleNamespace(_default_manager=manager),
    )

    command.handle(dry_run=False, exchange_rate=None)

    manager.filter.assert_not_called()
    assert any(
        "迁移已取消" in str(call.args[0])
        for call in command.stdout.write.call_args_list
    )


def test_dry_run_uses_manual_rate_and_handles_empty_queryset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dry runs must skip confirmation, honor manual rates, and stop on no data."""
    command = _command()
    queryset = MagicMock()
    queryset.count.return_value = 0
    manager = MagicMock()
    manager.filter.return_value = queryset
    monkeypatch.setattr(
        migrate_usd_data,
        "MacroIndicator",
        SimpleNamespace(_default_manager=manager),
    )

    command.handle(dry_run=True, exchange_rate=7.2)

    manager.filter.assert_called_once_with(original_unit__icontains="美元")
    assert any("使用手动指定汇率: 7.2" in str(call.args[0]) for call in command.stdout.write.call_args_list)
    assert any("没有需要迁移的数据" in str(call.args[0]) for call in command.stdout.write.call_args_list)


def test_dry_run_reports_conversions_and_isolates_row_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview mode must report each conversion without saving and retain row errors."""
    command = _command()
    good = SimpleNamespace(
        code="USD_GDP",
        reporting_period="2026Q1",
        value=Decimal("10"),
        original_unit="亿美元",
        save=MagicMock(),
    )
    bad = SimpleNamespace(
        code="BAD",
        reporting_period="2026Q1",
        value=Decimal("5"),
        original_unit="亿美元",
        save=MagicMock(),
    )
    queryset = MagicMock()
    queryset.count.return_value = 2
    queryset.__iter__.return_value = iter([good, bad])
    manager = MagicMock()
    manager.filter.return_value = queryset
    monkeypatch.setattr(
        migrate_usd_data,
        "MacroIndicator",
        SimpleNamespace(_default_manager=manager),
    )
    monkeypatch.setattr(
        migrate_usd_data.ExchangeRateService,
        "get_usd_cny_rate",
        lambda: 7.1,
    )
    monkeypatch.setattr(
        migrate_usd_data,
        "normalize_currency_unit",
        MagicMock(side_effect=[(71.0, "元"), RuntimeError("invalid row")]),
    )
    monkeypatch.setattr(migrate_usd_data.transaction, "atomic", nullcontext)

    command.handle(dry_run=True, exchange_rate=None)

    good.save.assert_not_called()
    assert any("[DRY RUN]" in str(call.args[0]) for call in command.stdout.write.call_args_list)
    assert any("invalid row" in str(call.args[0]) for call in command.stdout.write.call_args_list)
    assert any("错误: 1 条" in str(call.args[0]) for call in command.stdout.write.call_args_list)


def test_confirmed_migration_persists_values_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmed execution must persist normalized values and periodic progress."""
    command = _command()
    indicators = [
        SimpleNamespace(
            code=f"USD_{index}",
            reporting_period="2026Q1",
            value=Decimal("10"),
            original_unit="亿美元",
            unit="亿美元",
            save=MagicMock(),
        )
        for index in range(100)
    ]
    queryset = MagicMock()
    queryset.count.return_value = len(indicators)
    queryset.__iter__.return_value = iter(indicators)
    manager = MagicMock()
    manager.filter.return_value = queryset
    monkeypatch.setattr(
        migrate_usd_data,
        "MacroIndicator",
        SimpleNamespace(_default_manager=manager),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "YES")
    monkeypatch.setattr(
        migrate_usd_data,
        "normalize_currency_unit",
        lambda *_args, **_kwargs: (70.0, "元"),
    )
    monkeypatch.setattr(migrate_usd_data.transaction, "atomic", nullcontext)

    command.handle(dry_run=False, exchange_rate=7.0)

    assert all(indicator.value == 70.0 for indicator in indicators)
    assert all(indicator.unit == "元" for indicator in indicators)
    assert all(indicator.save.call_count == 1 for indicator in indicators)
    assert any("已迁移 100/100" in str(call.args[0]) for call in command.stdout.write.call_args_list)
    assert any("迁移完成: 100/100 成功" in str(call.args[0]) for call in command.stdout.write.call_args_list)
