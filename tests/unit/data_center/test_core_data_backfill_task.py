"""Active A-share core-data backfill task outcome contracts."""

import json
from datetime import date
from types import SimpleNamespace

import pytest

from apps.data_center.application.tasks import (
    backfill_active_a_share_core_data_batch_task,
)


@pytest.fixture(autouse=True)
def _patch_control_plane_repositories(mocker):
    """Keep unit tests in-memory while exercising the durable save calls."""

    repositories = {name: mocker.Mock() for name in ("run", "batch", "checkpoint")}
    snapshot = mocker.patch(
        "apps.data_center.application.tasks.persist_sync_control_plane_snapshot"
    )
    snapshot.side_effect = lambda run, batch, checkpoint: (
        repositories["run"].save(run),
        repositories["batch"].save(batch),
        repositories["checkpoint"].save(checkpoint),
    )
    return repositories


def _patch_backfill_dependencies(
    mocker,
    *,
    stored_count=1,
    failure=None,
    publication_failure: bool = False,
):
    mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill",
        return_value=["000001.SZ", "002156.SZ"],
    )
    mocker.patch(
        "apps.data_center.application.tasks.get_active_provider_id_by_source",
        return_value=7,
    )
    mocker.patch(
        "apps.data_center.application.tasks.latest_completed_cn_market_session",
        return_value=date(2026, 7, 31),
    )

    def _use_case(domain):
        use_case = mocker.Mock()

        def _execute(request):
            asset_code = getattr(request, "asset_code", "batch")
            if failure == (domain, asset_code):
                raise RuntimeError("provider failure")
            count = len(request.asset_codes) if domain == "quote" else stored_count
            return SimpleNamespace(stored_count=count)

        use_case.execute.side_effect = _execute
        if domain == "valuation":

            def _execute_current_batch(*, provider_id, asset_codes, as_of_date):
                del provider_id, as_of_date
                succeeded = [code for code in asset_codes if failure != ("valuation", code)]
                count = len(succeeded) if stored_count else 0
                return SimpleNamespace(
                    stored_count=count,
                    succeeded_asset_codes=(succeeded if stored_count else []),
                )

            use_case.execute.side_effect = _execute_current_batch
        return use_case

    mocker.patch(
        "apps.data_center.application.tasks.make_backfill_sync_quote_use_case",
        return_value=_use_case("quote"),
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_backfill_sync_price_use_case",
        return_value=_use_case("price"),
    )
    mocker.patch(
        "apps.data_center.application.tasks." "make_backfill_sync_current_valuation_batch_use_case",
        return_value=_use_case("valuation"),
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_backfill_sync_financial_use_case",
        return_value=_use_case("financial"),
    )
    coordinator = mocker.Mock()
    if publication_failure:
        coordinator.execute.side_effect = ValueError("full universe incomplete")
    else:
        coordinator.execute.return_value = SimpleNamespace(published_count=6)
    factory = mocker.patch(
        "apps.data_center.application.tasks." "make_core_current_publication_rebuild_use_case",
        return_value=coordinator,
    )
    return factory, coordinator


def test_backfill_batch_rejects_invalid_input_before_repository_access(
    mocker,
    _patch_control_plane_repositories,
) -> None:
    universe = mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill"
    )

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=0)

    assert result["outcome"] == "failed"
    assert result["stage"] == "input"
    universe.assert_not_called()
    for repository in _patch_control_plane_repositories.values():
        repository.save.assert_not_called()


def test_backfill_batch_reports_all_success_with_checkpoint(mocker) -> None:
    factory, coordinator = _patch_backfill_dependencies(mocker)

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "success"
    assert result["requested"] == 2
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["stored"] == 8
    assert result["published"] == 6
    assert result["checkpoint"] == {
        "offset": 0,
        "next_offset": 2,
        "total_assets": 2,
        "complete": True,
    }
    factory.assert_called_once_with(created_by="celery.core_data_backfill")
    coordinator.execute.assert_called_once()


def test_backfill_batch_persists_stable_run_batch_and_cursor_on_retry(
    mocker,
    _patch_control_plane_repositories,
) -> None:
    _patch_backfill_dependencies(mocker)

    first = backfill_active_a_share_core_data_batch_task.run(batch_size=2)
    second = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    run_saves = _patch_control_plane_repositories["run"].save.call_args_list
    batch_saves = _patch_control_plane_repositories["batch"].save.call_args_list
    checkpoint_saves = _patch_control_plane_repositories["checkpoint"].save.call_args_list
    assert len(run_saves) == len(batch_saves) == len(checkpoint_saves) == 2
    assert run_saves[0].args[0].run_id == run_saves[1].args[0].run_id
    assert batch_saves[0].args[0].batch_id == batch_saves[1].args[0].batch_id
    assert (
        batch_saves[0].args[0].idempotency_key
        == "equity.core.backfill:tushare:offset=0:window=2:"
        + batch_saves[0].args[0].idempotency_key.rsplit(":", 1)[-1]
    )
    assert batch_saves[0].args[0].requested == 2
    assert batch_saves[0].args[0].succeeded == 2
    assert batch_saves[0].args[0].stored == 8
    assert batch_saves[0].args[0].published == 6
    assert json.loads(checkpoint_saves[0].args[0].cursor_value) == first["checkpoint"]
    assert json.loads(checkpoint_saves[1].args[0].cursor_value) == second["checkpoint"]


def test_backfill_batch_reports_partial_failure(mocker) -> None:
    _factory, coordinator = _patch_backfill_dependencies(
        mocker,
        failure=("financial", "002156.SZ"),
    )

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "partial"
    assert result["success"] is True
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["domains"]["financial"]["failed"] == 1
    coordinator.execute.assert_not_called()


def test_backfill_batch_reports_zero_output_as_complete_failure(mocker) -> None:
    _patch_backfill_dependencies(mocker, stored_count=0)

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "failed"
    assert result["success"] is False
    assert result["failed"] == 2
    assert any(error["error"] == "zero_output" for error in result["errors"])


def test_backfill_batch_blocks_and_keeps_checkpoint_open_when_publication_fails(
    mocker,
) -> None:
    _factory, coordinator = _patch_backfill_dependencies(
        mocker,
        publication_failure=True,
    )

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "blocked"
    assert result["success"] is False
    assert result["stage"] == "publication"
    assert result["checkpoint"]["complete"] is False
    assert result["checkpoint"]["next_offset"] == 0
    assert result["published"] == 0
    assert any(
        error
        == {
            "domain": "publication",
            "asset_code": "universe",
            "error": "rebuild_failed",
        }
        for error in result["errors"]
    )
    coordinator.execute.assert_called_once()


def test_backfill_batch_reports_missing_provider_as_failure(mocker) -> None:
    mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill",
        return_value=["002156.SZ"],
    )
    mocker.patch(
        "apps.data_center.application.tasks.get_active_provider_id_by_source",
        return_value=None,
    )

    result = backfill_active_a_share_core_data_batch_task.run()

    assert result["outcome"] == "failed"
    assert result["stage"] == "provider"
    assert result["checkpoint"]["complete"] is False


def test_backfill_batch_blocks_when_market_session_is_unavailable(mocker) -> None:
    mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill",
        return_value=["002156.SZ"],
    )
    mocker.patch(
        "apps.data_center.application.tasks.get_active_provider_id_by_source",
        return_value=7,
    )
    mocker.patch(
        "apps.data_center.application.tasks.latest_completed_cn_market_session",
        return_value=None,
    )

    result = backfill_active_a_share_core_data_batch_task.run()

    assert result["outcome"] == "blocked"
    assert result["stage"] == "market_calendar"


def test_backfill_batch_returns_noop_after_checkpoint_completion(mocker) -> None:
    mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill",
        return_value=["002156.SZ"],
    )

    result = backfill_active_a_share_core_data_batch_task.run(offset=1)

    assert result["outcome"] == "noop"
    assert result["checkpoint"]["complete"] is True
