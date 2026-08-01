"""Active A-share core-data backfill task outcome contracts."""

from datetime import date
from types import SimpleNamespace

from apps.data_center.application.tasks import (
    backfill_active_a_share_core_data_batch_task,
)


def _patch_backfill_dependencies(mocker, *, stored_count=1, failure=None) -> None:
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
        "apps.data_center.application.tasks.make_sync_quote_use_case",
        return_value=_use_case("quote"),
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_sync_price_use_case",
        return_value=_use_case("price"),
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_sync_current_valuation_batch_use_case",
        return_value=_use_case("valuation"),
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_sync_financial_use_case",
        return_value=_use_case("financial"),
    )


def test_backfill_batch_rejects_invalid_input_before_repository_access(mocker) -> None:
    universe = mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill"
    )

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=0)

    assert result["outcome"] == "failed"
    assert result["stage"] == "input"
    universe.assert_not_called()


def test_backfill_batch_reports_all_success_with_checkpoint(mocker) -> None:
    _patch_backfill_dependencies(mocker)

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "success"
    assert result["requested"] == 2
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["stored"] == 8
    assert result["checkpoint"] == {
        "offset": 0,
        "next_offset": 2,
        "total_assets": 2,
        "complete": True,
    }


def test_backfill_batch_reports_partial_failure(mocker) -> None:
    _patch_backfill_dependencies(mocker, failure=("financial", "002156.SZ"))

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "partial"
    assert result["success"] is True
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["domains"]["financial"]["failed"] == 1


def test_backfill_batch_reports_zero_output_as_complete_failure(mocker) -> None:
    _patch_backfill_dependencies(mocker, stored_count=0)

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "failed"
    assert result["success"] is False
    assert result["failed"] == 2
    assert any(error["error"] == "zero_output" for error in result["errors"])


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
