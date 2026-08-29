"""Database wiring tests for the resumable A-share backfill control plane."""

from datetime import date
from types import SimpleNamespace

import pytest
from django.db import connection

from apps.data_center.application.tasks import backfill_active_a_share_core_data_batch_task
from apps.data_center.infrastructure.models import (
    SyncBatchModel,
    SyncCheckpointModel,
    SyncRunModel,
)


class _FakeBackfillUseCase:
    """Return a deterministic sync result or emulate one provider failure."""

    def __init__(self, result: object, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def execute(self, *args: object, **kwargs: object) -> object:
        """Implement the application use-case port used by the backfill task."""

        del args, kwargs
        if self._error is not None:
            raise self._error
        return self._result


def _require_postgresql() -> None:
    """Keep durable control-plane evidence scoped to the PostgreSQL CI fixture."""

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL control-plane evidence requires the CI database fixture")


def _patch_fake_backfill_dependencies(mocker, *, failure_domain: str | None = None) -> None:
    """Inject provider-shaped fake use cases while exercising real task persistence."""

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

    use_cases = {
        "quote": _FakeBackfillUseCase(SimpleNamespace(stored_count=1)),
        "price": _FakeBackfillUseCase(SimpleNamespace(stored_count=1)),
        "valuation": _FakeBackfillUseCase(
            SimpleNamespace(stored_count=1, succeeded_asset_codes=["000001.SZ"])
        ),
        "financial": _FakeBackfillUseCase(SimpleNamespace(stored_count=1)),
    }
    if failure_domain is not None:
        use_cases[failure_domain] = _FakeBackfillUseCase(
            SimpleNamespace(stored_count=0),
            error=RuntimeError(f"fake provider failure: {failure_domain}"),
        )
    factory_names = {
        "quote": "make_backfill_sync_quote_use_case",
        "price": "make_backfill_sync_price_use_case",
        "valuation": "make_backfill_sync_current_valuation_batch_use_case",
        "financial": "make_backfill_sync_financial_use_case",
    }
    for domain_name, factory_name in factory_names.items():
        mocker.patch(
            f"apps.data_center.application.tasks.{factory_name}",
            return_value=use_cases[domain_name],
        )
    coordinator = mocker.Mock()
    coordinator.execute.return_value = SimpleNamespace(published_count=3)
    mocker.patch(
        "apps.data_center.application.tasks." "make_core_current_publication_rebuild_use_case",
        return_value=coordinator,
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
        "apps.data_center.application.tasks.make_backfill_sync_quote_use_case",
        return_value=quote_use_case,
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_backfill_sync_price_use_case",
        return_value=price_use_case,
    )
    mocker.patch(
        "apps.data_center.application.tasks." "make_backfill_sync_current_valuation_batch_use_case",
        return_value=valuation_use_case,
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_backfill_sync_financial_use_case",
        return_value=financial_use_case,
    )
    coordinator = mocker.Mock()
    coordinator.execute.return_value = SimpleNamespace(published_count=3)
    mocker.patch(
        "apps.data_center.application.tasks." "make_core_current_publication_rebuild_use_case",
        return_value=coordinator,
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
    assert run.published == 3
    assert batch.idempotency_key.startswith("equity.core.backfill:tushare:offset=0:window=1:")
    assert checkpoint.cursor_name == "asset_offset"
    assert '"complete":true' in checkpoint.cursor_value
    assert checkpoint.processed == 1
    assert checkpoint.failed == 0


@pytest.mark.django_db
def test_backfill_control_plane_snapshot_rolls_back_if_checkpoint_persistence_fails(
    mocker,
) -> None:
    """A failed checkpoint write must not leave an orphan run or batch row."""

    _patch_fake_backfill_dependencies(mocker)
    checkpoint_repository = mocker.Mock()
    checkpoint_repository.save.side_effect = RuntimeError("checkpoint store unavailable")
    mocker.patch(
        "apps.data_center.composition.get_sync_checkpoint_repository",
        return_value=checkpoint_repository,
    )

    with pytest.raises(RuntimeError, match="checkpoint store unavailable"):
        backfill_active_a_share_core_data_batch_task.run(batch_size=1)

    assert SyncRunModel._default_manager.count() == 0
    assert SyncBatchModel._default_manager.count() == 0
    assert SyncCheckpointModel._default_manager.count() == 0


@pytest.mark.django_db
def test_postgresql_backfill_first_run_and_same_parameter_retry_are_idempotent(mocker) -> None:
    """A retry reuses one run, batch and checkpoint for the same request window."""

    _require_postgresql()
    _patch_fake_backfill_dependencies(mocker)

    first_result = backfill_active_a_share_core_data_batch_task.run(batch_size=1)
    first_run = SyncRunModel._default_manager.get(
        dataset_key="equity.core.backfill",
        trigger="celery.backfill_a_share_core",
    )
    first_batch = SyncBatchModel._default_manager.get(
        dataset_key="equity.core.backfill",
        run_id=first_run.run_id,
    )
    first_checkpoint = SyncCheckpointModel._default_manager.get(batch_id=first_batch.batch_id)
    assert first_result["outcome"] == "success"
    assert SyncRunModel._default_manager.count() == 1
    assert SyncBatchModel._default_manager.count() == 1
    assert SyncCheckpointModel._default_manager.count() == 1

    retry_result = backfill_active_a_share_core_data_batch_task.run(batch_size=1)

    assert retry_result["outcome"] == "success"
    assert SyncRunModel._default_manager.count() == 1
    assert SyncBatchModel._default_manager.count() == 1
    assert SyncCheckpointModel._default_manager.count() == 1
    retry_run = SyncRunModel._default_manager.get(run_id=first_run.run_id)
    retry_batch = SyncBatchModel._default_manager.get(batch_id=first_batch.batch_id)
    retry_checkpoint = SyncCheckpointModel._default_manager.get(
        checkpoint_id=first_checkpoint.checkpoint_id
    )
    assert retry_run.run_id == first_batch.run_id
    assert retry_batch.run_id == retry_run.run_id
    assert retry_checkpoint.batch_id == retry_batch.batch_id
    assert retry_checkpoint.cursor_value == first_checkpoint.cursor_value


@pytest.mark.django_db
def test_postgresql_backfill_provider_domain_failure_persists_partial_outcome(mocker) -> None:
    """One fake provider-domain failure is durable as partial, not a false success."""

    _require_postgresql()
    _patch_fake_backfill_dependencies(mocker, failure_domain="price")

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=1)

    assert result["success"] is True
    assert result["outcome"] == "partial"
    assert result["domains"]["price"]["failed"] == 1
    assert result["errors"] == [
        {"domain": "price", "asset_code": "000001.SZ", "error": "sync_failed"}
    ]
    run = SyncRunModel._default_manager.get(
        dataset_key="equity.core.backfill",
        trigger="celery.backfill_a_share_core",
    )
    batch = SyncBatchModel._default_manager.get(run_id=run.run_id)
    checkpoint = SyncCheckpointModel._default_manager.get(batch_id=batch.batch_id)
    assert run.outcome == "partial"
    assert run.requested == 1
    assert run.succeeded == 0
    assert run.failed == 1
    assert run.stored == 3
    assert batch.state == "failed"
    assert checkpoint.state == "failed"
    assert checkpoint.processed == 0
    assert checkpoint.failed == 1
