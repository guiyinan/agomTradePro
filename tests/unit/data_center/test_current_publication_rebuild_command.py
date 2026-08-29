"""Operator boundary contracts for full-universe publication rebuilds."""

from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import CommandError, call_command


def test_rebuild_command_is_dry_run_by_default(mocker) -> None:
    coordinator = mocker.Mock()
    coordinator.preview.return_value = SimpleNamespace(
        ready=True,
        to_dict=lambda: {"ready": True, "member_count": 6},
    )
    factory = mocker.patch(
        "apps.data_center.management.commands."
        "rebuild_active_a_share_core_publications."
        "make_core_current_publication_rebuild_use_case",
        return_value=coordinator,
    )
    mocker.patch(
        "apps.data_center.management.commands."
        "rebuild_active_a_share_core_publications."
        "list_active_stock_codes_for_backfill",
        return_value=["000001.SZ", "600000.SH"],
    )
    stdout = StringIO()

    call_command("rebuild_active_a_share_core_publications", stdout=stdout)

    payload = json.loads(stdout.getvalue())
    assert payload["mode"] == "dry_run"
    assert payload["ready"] is True
    coordinator.preview.assert_called_once()
    coordinator.execute.assert_not_called()
    factory.assert_called_once_with(created_by="ops.current_publication_rebuild.preview")


def test_rebuild_command_requires_operator_for_execute() -> None:
    with pytest.raises(CommandError, match="operator"):
        call_command(
            "rebuild_active_a_share_core_publications",
            "--execute",
            stdout=StringIO(),
        )


def test_rebuild_command_executes_with_explicit_operator(mocker) -> None:
    result = SimpleNamespace(
        published_count=6,
        to_dict=lambda: {
            "published_count": 6,
            "publication_ids": ["price", "valuation", "financial"],
        },
    )
    coordinator = mocker.Mock()
    coordinator.execute.return_value = result
    factory = mocker.patch(
        "apps.data_center.management.commands."
        "rebuild_active_a_share_core_publications."
        "make_core_current_publication_rebuild_use_case",
        return_value=coordinator,
    )
    mocker.patch(
        "apps.data_center.management.commands."
        "rebuild_active_a_share_core_publications."
        "list_active_stock_codes_for_backfill",
        return_value=["000001.SZ", "600000.SH"],
    )
    stdout = StringIO()

    call_command(
        "rebuild_active_a_share_core_publications",
        "--execute",
        "--operator",
        "root-approval-A2",
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert payload["mode"] == "execute"
    assert payload["operator"] == "root-approval-A2"
    assert payload["published_count"] == 6
    coordinator.execute.assert_called_once()
    factory.assert_called_once_with(created_by="ops.current_publication_rebuild:root-approval-A2")


@pytest.mark.parametrize("operator", [" ", "x" * 101, "line\nbreak"])
def test_rebuild_command_rejects_invalid_operator(operator: str) -> None:
    with pytest.raises(CommandError, match="operator"):
        call_command(
            "rebuild_active_a_share_core_publications",
            "--execute",
            "--operator",
            operator,
            stdout=StringIO(),
        )
