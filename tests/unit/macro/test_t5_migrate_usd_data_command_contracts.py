"""T5 safety and conversion contracts for the canonical USD migration command."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from django.core.management.base import CommandError

from apps.data_center.domain.entities import MacroFact
from apps.macro.management.commands import migrate_usd_data
from apps.macro.management.commands.migrate_usd_data import Command


def _command() -> Command:
    """Build a command with output capture."""

    command = Command()
    command.stdout = MagicMock()
    command.stderr = MagicMock()
    return command


def _fact(code: str, value: float = 10.0) -> MacroFact:
    """Build a governed-looking canonical macro fact for command tests."""

    return MacroFact(
        indicator_code=code,
        reporting_period=date(2026, 1, 1),
        value=value,
        unit="亿美元",
        source="test",
        fetched_at=datetime(2026, 1, 2, tzinfo=UTC),
        extra={
            "source_type": "test",
            "original_unit": "亿美元",
            "display_unit": "亿美元",
            "dimension_key": "currency",
            "multiplier_to_storage": 1.0,
            "matched_rule_id": 1,
            "period_type": "M",
        },
    )


def test_live_migration_requires_explicit_backup_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live migration must stop before canonical data access without confirmation."""

    command = _command()
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    list_facts = MagicMock()
    monkeypatch.setattr(migrate_usd_data, "list_macro_facts_by_original_unit", list_facts)

    command.handle(dry_run=False, exchange_rate=None)

    list_facts.assert_not_called()
    assert any("迁移已取消" in str(call.args[0]) for call in command.stdout.write.call_args_list)


def test_dry_run_uses_manual_rate_and_handles_empty_queryset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dry runs skip confirmation, honor manual rates, and stop on no data."""

    command = _command()
    list_facts = MagicMock(return_value=[])
    monkeypatch.setattr(migrate_usd_data, "list_macro_facts_by_original_unit", list_facts)

    command.handle(dry_run=True, exchange_rate=7.2)

    list_facts.assert_called_once_with("美元")
    assert any(
        "使用手动指定汇率: 7.2" in str(call.args[0]) for call in command.stdout.write.call_args_list
    )
    assert any(
        "没有需要迁移的数据" in str(call.args[0]) for call in command.stdout.write.call_args_list
    )


def test_dry_run_reports_conversions_and_fails_closed_on_row_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview mode reports valid rows but rejects an incomplete migration batch."""

    command = _command()
    monkeypatch.setattr(
        migrate_usd_data,
        "list_macro_facts_by_original_unit",
        lambda _unit: [_fact("USD_GDP"), _fact("BAD")],
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

    with pytest.raises(CommandError, match="macro_usd_data_migration_failed"):
        command.handle(dry_run=True, exchange_rate=None)

    assert any("[DRY RUN]" in str(call.args[0]) for call in command.stdout.write.call_args_list)
    assert any(
        "macro_usd_data_migration_failed" in str(call.args[0])
        for call in command.stderr.write.call_args_list
    )
    assert "invalid row" not in str(command.stdout.write.call_args_list)


def test_confirmed_migration_persists_canonical_values_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmed execution persists normalized canonical facts atomically."""

    command = _command()
    facts = [_fact(f"USD_{index}") for index in range(100)]
    save_facts = MagicMock(return_value=100)
    monkeypatch.setattr(migrate_usd_data, "list_macro_facts_by_original_unit", lambda _unit: facts)
    monkeypatch.setattr(migrate_usd_data, "save_macro_facts", save_facts)
    monkeypatch.setattr("builtins.input", lambda _prompt: "YES")
    monkeypatch.setattr(
        migrate_usd_data,
        "normalize_currency_unit",
        lambda *_args, **_kwargs: (70.0, "元"),
    )
    monkeypatch.setattr(migrate_usd_data.transaction, "atomic", nullcontext)

    command.handle(dry_run=False, exchange_rate=7.0)

    saved_facts = save_facts.call_args.args[0]
    assert len(saved_facts) == 100
    assert all(fact.value == 70.0 for fact in saved_facts)
    assert all(fact.unit == "元" for fact in saved_facts)
    assert any(
        "迁移完成: 100/100 成功" in str(call.args[0])
        for call in command.stdout.write.call_args_list
    )
