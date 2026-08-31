"""Operator boundary contracts for current-fact remediation."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import CommandError, call_command

from core.exceptions import MissingConfigError

NOW = datetime(2026, 8, 30, 1, 0, tzinfo=UTC)
SESSION_DATE = date(2026, 8, 28)
COMMAND_MODULE = "apps.data_center.management.commands.repair_active_a_share_current_facts"


def _patch_command_dependencies(mocker, coordinator):
    mocker.patch(
        f"{COMMAND_MODULE}.list_active_stock_codes_for_backfill",
        return_value=["000001.SZ", "600000.SH"],
    )
    mocker.patch(f"{COMMAND_MODULE}.timezone.now", return_value=NOW)
    mocker.patch(
        f"{COMMAND_MODULE}.latest_completed_cn_market_session",
        return_value=SESSION_DATE,
    )
    return mocker.patch(
        f"{COMMAND_MODULE}.make_core_current_fact_refresh_use_case",
        return_value=coordinator,
    )


def test_current_fact_repair_is_dry_run_by_default(mocker) -> None:
    coordinator = mocker.Mock()
    coordinator.preview.return_value = SimpleNamespace(
        to_dict=lambda: {"ready_without_provider_refresh": False}
    )
    factory = _patch_command_dependencies(mocker, coordinator)
    stdout = StringIO()

    call_command("repair_active_a_share_current_facts", stdout=stdout)

    payload = json.loads(stdout.getvalue())
    assert payload["mode"] == "dry_run"
    assert payload["asset_count"] == 2
    assert payload["session_date"] == "2026-08-28"
    coordinator.preview.assert_called_once()
    coordinator.execute.assert_not_called()
    factory.assert_called_once_with(
        source_type="akshare",
        created_by="ops.current_fact_refresh.preview",
    )


def test_current_fact_repair_fails_closed_when_universe_config_is_missing(mocker) -> None:
    mocker.patch(
        f"{COMMAND_MODULE}.list_active_stock_codes_for_backfill",
        side_effect=MissingConfigError("Production coverage universe config is not initialized"),
    )
    factory = mocker.patch(f"{COMMAND_MODULE}.make_core_current_fact_refresh_use_case")

    with pytest.raises(CommandError, match="not initialized"):
        call_command("repair_active_a_share_current_facts", stdout=StringIO())

    factory.assert_not_called()


def test_current_fact_repair_requires_operator_for_execute() -> None:
    with pytest.raises(CommandError, match="operator"):
        call_command(
            "repair_active_a_share_current_facts",
            "--execute",
            stdout=StringIO(),
        )


def test_current_fact_repair_executes_with_explicit_operator(mocker) -> None:
    coordinator = mocker.Mock()
    coordinator.execute.return_value = SimpleNamespace(
        to_dict=lambda: {"quote_stored_count": 2, "publication_ids": ["all"]}
    )
    factory = _patch_command_dependencies(mocker, coordinator)
    stdout = StringIO()

    call_command(
        "repair_active_a_share_current_facts",
        "--execute",
        "--operator",
        "root-approval-A3",
        "--batch-size",
        "2",
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert payload["mode"] == "execute"
    assert payload["operator"] == "root-approval-A3"
    assert payload["quote_stored_count"] == 2
    coordinator.execute.assert_called_once_with(
        asset_codes=["000001.SZ", "600000.SH"],
        session_date=SESSION_DATE,
        recorded_at=NOW,
        batch_size=2,
    )
    factory.assert_called_once_with(
        source_type="akshare",
        created_by="ops.current_fact_refresh:root-approval-A3",
    )


@pytest.mark.parametrize("operator", [" ", "x" * 101, "line\nbreak"])
def test_current_fact_repair_rejects_invalid_operator(operator: str) -> None:
    with pytest.raises(CommandError, match="operator"):
        call_command(
            "repair_active_a_share_current_facts",
            "--execute",
            "--operator",
            operator,
            stdout=StringIO(),
        )


@pytest.mark.parametrize("batch_size", ["0", "501"])
def test_current_fact_repair_rejects_invalid_batch_size(batch_size: str) -> None:
    with pytest.raises(CommandError, match="batch-size"):
        call_command(
            "repair_active_a_share_current_facts",
            "--batch-size",
            batch_size,
            stdout=StringIO(),
        )
