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
            stdout=StringIO(),
        )

    run.assert_called_once_with(
        offset=340,
        batch_size=20,
        source="akshare",
        history_days=756,
        financial_periods=8,
    )
