"""Command safety tests for exact-date historical market-fact backfills."""

from contextlib import contextmanager
from datetime import date
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.management import CommandError, call_command

from apps.data_center.management.commands import backfill_historical_a_share_market_facts as module


@pytest.fixture
def _historical_scope(monkeypatch):
    scope = SimpleNamespace(
        target_date=date(2026, 7, 31),
        candidate_codes=("000001.SZ", "002156.SZ"),
        requested_codes=("000001.SZ", "002156.SZ"),
        excluded_not_yet_listed=(),
        unknown_listing_date_codes=("002156.SZ",),
    )
    monkeypatch.setattr(
        module,
        "load_open_cn_market_sessions",
        lambda start, end: (start,) if start == end else (),
    )
    monkeypatch.setattr(
        module,
        "build_target_date_a_share_universe_scope",
        lambda _target: scope,
    )
    return scope


def test_historical_market_backfill_defaults_to_zero_write_preview(
    monkeypatch,
    _historical_scope,
) -> None:
    run = Mock()
    monkeypatch.setattr(module.backfill_active_a_share_core_data_batch_task, "run", run)
    stdout = StringIO()

    call_command(
        "backfill_historical_a_share_market_facts",
        target_trade_date="2026-07-31",
        stdout=stdout,
    )

    output = stdout.getvalue()
    assert '"stage": "dry_run"' in output
    assert '"requested": 2' in output
    assert '"stored": 0' in output
    assert '"published": 0' in output
    assert '"current_publication_changed": false' in output
    run.assert_not_called()


def test_historical_market_backfill_advances_partial_batches_and_reports_final_partial(
    monkeypatch,
    _historical_scope,
) -> None:
    universe_hash = "d" * 64
    run = Mock(
        side_effect=[
            {
                "outcome": "partial",
                "requested": 1,
                "succeeded": 0,
                "failed": 1,
                "stored": 2,
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
                "requested": 1,
                "succeeded": 1,
                "failed": 0,
                "stored": 3,
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
    entered: list[bool] = []

    @contextmanager
    def _cache_scope():
        entered.append(True)
        yield

    monkeypatch.setattr(module, "cache_tushare_historical_session_frames", _cache_scope)

    with pytest.raises(CommandError, match="unresolved provider rows"):
        call_command(
            "backfill_historical_a_share_market_facts",
            target_trade_date="2026-07-31",
            execute=True,
            operator="service:data02",
            batch_size=1,
            stdout=StringIO(),
        )

    assert run.call_count == 2
    assert entered == [True]
    assert run.call_args_list[0].kwargs["universe_hash"] == ""
    assert run.call_args_list[1].kwargs["universe_hash"] == universe_hash
    assert all(call.kwargs["historical_market_date"] == "2026-07-31" for call in run.call_args_list)


def test_historical_market_backfill_execute_requires_operator(
    monkeypatch,
    _historical_scope,
) -> None:
    run = Mock()
    monkeypatch.setattr(module.backfill_active_a_share_core_data_batch_task, "run", run)

    with pytest.raises(CommandError, match="--operator must be"):
        call_command(
            "backfill_historical_a_share_market_facts",
            target_trade_date="2026-07-31",
            execute=True,
            stdout=StringIO(),
        )

    run.assert_not_called()
