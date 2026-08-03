"""Database wiring tests for the resumable A-share backfill control plane."""

from datetime import date
from types import SimpleNamespace

import pytest

from apps.data_center.application.tasks import backfill_active_a_share_core_data_batch_task
from apps.data_center.infrastructure.models import (
    SyncBatchModel,
    SyncCheckpointModel,
    SyncRunModel,
)


@pytest.mark.django_db
def test_backfill_persists_run_batch_and_checkpoint_rows(mocker) -> None:
    """The task's application wiring must persist one durable batch window."""

    mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill",
        return_value=["000001.SZ"],
    )
    mocker.patch(
        "apps.data_center.application.tasks.get_active_provider_id_by_source",
        return_value=7,
    )
    mocker.patch(
        "apps.data_center.application.tasks.latest_completed_cn_market_session",
        return_value=date(2026, 7, 31),
    )

    quote_use_case = mocker.Mock()
    quote_use_case.execute.return_value = SimpleNamespace(stored_count=1)
    price_use_case = mocker.Mock()
    price_use_case.execute.return_value = SimpleNamespace(stored_count=1)
    valuation_use_case = mocker.Mock()
    valuation_use_case.execute.return_value = SimpleNamespace(
        stored_count=1,
        succeeded_asset_codes=["000001.SZ"],
    )
    financial_use_case = mocker.Mock()
    financial_use_case.execute.return_value = SimpleNamespace(stored_count=1)
    mocker.patch(
        "apps.data_center.application.tasks.make_sync_quote_use_case",
        return_value=quote_use_case,
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_sync_price_use_case",
        return_value=price_use_case,
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_sync_current_valuation_batch_use_case",
        return_value=valuation_use_case,
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_sync_financial_use_case",
        return_value=financial_use_case,
    )

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=1)

    assert result["outcome"] == "success"
    run = SyncRunModel._default_manager.get(
        dataset_key="equity.core.backfill",
        trigger="celery.backfill_a_share_core",
    )
    batch = SyncBatchModel._default_manager.get(
        dataset_key="equity.core.backfill",
        run_id=run.run_id,
    )
    checkpoint = SyncCheckpointModel._default_manager.get(batch_id=batch.batch_id)
    assert run.outcome == "success"
    assert run.stored == 4
    assert run.published == 0
    assert batch.idempotency_key.startswith("equity.core.backfill:tushare:offset=0:window=1:")
    assert checkpoint.cursor_name == "asset_offset"
    assert '"complete":true' in checkpoint.cursor_value
    assert checkpoint.processed == 1
    assert checkpoint.failed == 0
