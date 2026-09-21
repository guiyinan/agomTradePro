"""Management-command safety tests for resumable A-share backfills."""

from io import StringIO
from unittest.mock import Mock

import pytest
from django.core.management import CommandError, call_command

from apps.data_center.management.commands import backfill_active_a_share_core_data as module


def test_backfill_command_stops_on_partial_without_advancing_checkpoint(monkeypatch) -> None:
    """A partial batch must be retried instead of silently skipped."""

    result = {
        "outcome": "partial",
        "checkpoint": {
            "offset": 340,
            "next_offset": 360,
            "total_assets": 5533,
            "complete": False,
        },
        "requested": 20,
        "succeeded": 19,
        "failed": 1,
        "stored": 11563,
    }
    run = Mock(return_value=result)
    monkeypatch.setattr(module.backfill_active_a_share_core_data_batch_task, "run", run)

    with pytest.raises(CommandError, match="outcome=partial.*offset 340"):
        call_command(
            "backfill_active_a_share_core_data",
            resume_offset=340,
            batch_size=20,
            source="akshare",
            max_batches=5,
            execute=True,
            operator="service:data02",
            stdout=StringIO(),
        )

    run.assert_called_once_with(
        offset=340,
        batch_size=20,
        source="akshare",
        history_days=756,
        financial_periods=8,
        operator="service:data02",
        universe_hash="",
    )


def test_backfill_command_requires_explicit_execute(monkeypatch) -> None:
    """The production writer must not start from an accidental bare command."""

    run = Mock()
    monkeypatch.setattr(module.backfill_active_a_share_core_data_batch_task, "run", run)

    with pytest.raises(CommandError, match="--execute is required"):
        call_command("backfill_active_a_share_core_data", stdout=StringIO())

    run.assert_not_called()


def test_backfill_command_carries_frozen_universe_hash_between_batches(monkeypatch) -> None:
    """The synchronous runner binds every later offset to the first universe."""

    universe_hash = "d" * 64
    run = Mock(
        side_effect=[
            {
                "outcome": "success",
                "checkpoint": {
                    "offset": 0,
                    "next_offset": 1,
                    "total_assets": 2,
                    "complete": False,
                    "universe_hash": universe_hash,
                },
            },
            {
                "outcome": "success",
                "checkpoint": {
                    "offset": 1,
                    "next_offset": 2,
                    "total_assets": 2,
                    "complete": True,
                    "universe_hash": universe_hash,
                },
            },
        ]
    )
    monkeypatch.setattr(module.backfill_active_a_share_core_data_batch_task, "run", run)

    call_command(
        "backfill_active_a_share_core_data",
        execute=True,
        operator="service:data02",
        batch_size=1,
        stdout=StringIO(),
    )

    assert run.call_args_list[0].kwargs["universe_hash"] == ""
    assert run.call_args_list[1].kwargs["universe_hash"] == universe_hash


def test_backfill_command_requires_bounded_operator(monkeypatch) -> None:
    """The task receives one bounded identity for server-side actor binding."""

    run = Mock()
    monkeypatch.setattr(module.backfill_active_a_share_core_data_batch_task, "run", run)

    with pytest.raises(CommandError, match="--operator must be"):
        call_command(
            "backfill_active_a_share_core_data",
            execute=True,
            operator="bad\nactor",
            stdout=StringIO(),
        )

    run.assert_not_called()
