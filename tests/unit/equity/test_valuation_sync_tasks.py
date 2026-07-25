from unittest.mock import MagicMock, patch

from apps.equity.application.tasks_valuation_sync import (
    sync_equity_valuation_task,
    sync_financial_data_task,
    sync_validate_scan_equity_valuation_task,
)


def test_sync_validate_scan_task_skips_scan_when_gate_blocked():
    with (
        patch("apps.equity.application.tasks_valuation_sync.SyncEquityValuationUseCase") as SyncUC,
        patch(
            "apps.equity.application.tasks_valuation_sync.ValidateEquityValuationQualityUseCase"
        ) as ValidateUC,
        patch("apps.equity.application.tasks_valuation_sync.ScanValuationRepairsUseCase") as ScanUC,
    ):
        SyncUC.return_value.execute.return_value = MagicMock(
            success=True, data={"synced_count": 10}
        )
        ValidateUC.return_value.execute.return_value = MagicMock(
            success=True,
            data={"is_gate_passed": False, "gate_reason": "coverage<0.95"},
        )

        result = sync_validate_scan_equity_valuation_task(days_back=1)

        assert result["success"] is True
        assert result["stage"] == "gate_blocked"
        assert result["scan_skipped"] is True
        ScanUC.return_value.execute.assert_not_called()


def test_sync_validate_scan_task_runs_scan_when_gate_passed():
    with (
        patch("apps.equity.application.tasks_valuation_sync.SyncEquityValuationUseCase") as SyncUC,
        patch(
            "apps.equity.application.tasks_valuation_sync.ValidateEquityValuationQualityUseCase"
        ) as ValidateUC,
        patch("apps.equity.application.tasks_valuation_sync.ScanValuationRepairsUseCase") as ScanUC,
    ):
        SyncUC.return_value.execute.return_value = MagicMock(
            success=True, data={"synced_count": 10}
        )
        ValidateUC.return_value.execute.return_value = MagicMock(
            success=True,
            data={"is_gate_passed": True},
        )
        ScanUC.return_value.execute.return_value = MagicMock(
            success=True,
            universe="all_active",
            as_of_date=MagicMock(isoformat=lambda: "2026-03-10"),
            scanned_count=10,
            saved_count=4,
            failed_count=0,
            phase_counts={},
            error=None,
        )

        result = sync_validate_scan_equity_valuation_task(days_back=1)

        assert result["success"] is True
        assert result["stage"] == "scan"
        assert result["scan"]["saved_count"] == 4


def test_sync_validate_scan_task_stops_when_sync_writes_no_records():
    with (
        patch(
            "apps.equity.application.tasks_valuation_sync.SyncEquityValuationUseCase"
        ) as sync_use_case,
        patch(
            "apps.equity.application.tasks_valuation_sync.ValidateEquityValuationQualityUseCase"
        ) as validate_use_case,
        patch(
            "apps.equity.application.tasks_valuation_sync.ScanValuationRepairsUseCase"
        ) as scan_use_case,
    ):
        sync_use_case.return_value.execute.return_value = MagicMock(
            success=True,
            data={
                "requested_count": 10,
                "synced_count": 0,
                "skipped_count": 10,
                "error_count": 0,
            },
        )

        result = sync_validate_scan_equity_valuation_task(days_back=1)

        assert result["success"] is False
        assert result["stage"] == "sync"
        assert result["error"] == "估值同步未写入任何记录"
        validate_use_case.assert_not_called()
        scan_use_case.assert_not_called()


def test_sync_valuation_task_rejects_boolean_days_before_repository_access():
    with patch(
        "apps.equity.application.tasks_valuation_sync.get_equity_stock_repository"
    ) as stock_repository:
        result = sync_equity_valuation_task(days_back=True)

    assert result == {
        "success": False,
        "error": "days_back 必须是整数",
        "stage": "input",
    }
    stock_repository.assert_not_called()


def test_sync_valuation_task_fails_when_success_response_has_no_records():
    with patch(
        "apps.equity.application.tasks_valuation_sync.SyncEquityValuationUseCase"
    ) as sync_use_case:
        sync_use_case.return_value.execute.return_value = MagicMock(
            success=True,
            data={"requested_count": 2, "synced_count": 0},
        )

        result = sync_equity_valuation_task(days_back=1)

    assert result["success"] is False
    assert result["stage"] == "sync"
    assert result["sync"] == {"requested_count": 2, "synced_count": 0}


def test_sync_financial_data_task_uses_explicit_codes_without_legacy_filter():
    with (
        patch(
            "apps.equity.application.tasks_valuation_sync.get_active_provider_id_by_source",
            return_value=3,
        ),
        patch(
            "apps.equity.application.tasks_valuation_sync.make_sync_financial_use_case"
        ) as make_sync_uc,
        patch(
            "apps.equity.application.tasks_valuation_sync.get_equity_stock_repository"
        ) as stock_repo_cls,
    ):
        stock_repo_cls.return_value.list_active_stock_codes.return_value = []
        make_sync_uc.return_value.execute.return_value = MagicMock(stored_count=10)

        result = sync_financial_data_task(
            source="akshare",
            periods=8,
            stock_codes=["001979.SZ", "001979.SZ"],
        )

        assert result["success"] is True
        assert result["synced_count"] == 10
        assert result["total_stocks"] == 1
        stock_repo_cls.return_value.list_active_stock_codes.assert_not_called()
        make_sync_uc.return_value.execute.assert_called_once()
        request = make_sync_uc.return_value.execute.call_args.args[0]
        assert request.provider_id == 3
        assert request.asset_code == "001979.SZ"
        assert request.periods == 8


def test_sync_financial_data_task_does_not_expand_explicit_empty_list():
    with patch(
        "apps.equity.application.tasks_valuation_sync.get_equity_stock_repository"
    ) as stock_repo_cls:
        result = sync_financial_data_task(stock_codes=[])

    assert result == {"success": False, "error": "没有找到活跃股票"}
    stock_repo_cls.return_value.list_active_stock_codes.assert_not_called()


def test_sync_financial_data_task_reports_complete_failure():
    with (
        patch(
            "apps.equity.application.tasks_valuation_sync.get_active_provider_id_by_source",
            return_value=3,
        ),
        patch(
            "apps.equity.application.tasks_valuation_sync.make_sync_financial_use_case"
        ) as make_sync_use_case,
    ):
        make_sync_use_case.return_value.execute.side_effect = RuntimeError("provider down")

        result = sync_financial_data_task(
            source="custom.provider",
            periods=8,
            stock_codes=["000001.SZ", "600000.SH"],
        )

    assert result["success"] is False
    assert result["partial_success"] is False
    assert result["synced_count"] == 0
    assert result["error_count"] == 2
    assert result["total_stocks"] == 2
    assert result["errors"] == [
        "000001.SZ: 同步失败",
        "600000.SH: 同步失败",
    ]
    assert "provider down" not in str(result)


def test_sync_financial_data_task_reports_partial_success():
    with (
        patch(
            "apps.equity.application.tasks_valuation_sync.get_active_provider_id_by_source",
            return_value=3,
        ),
        patch(
            "apps.equity.application.tasks_valuation_sync.make_sync_financial_use_case"
        ) as make_sync_use_case,
    ):
        make_sync_use_case.return_value.execute.side_effect = [
            MagicMock(stored_count=4),
            RuntimeError("second failed"),
        ]

        result = sync_financial_data_task(
            periods=8,
            stock_codes=["000001.SZ", "600000.SH"],
        )

    assert result["success"] is True
    assert result["partial_success"] is True
    assert result["synced_count"] == 4
    assert result["error_count"] == 1


def test_sync_financial_data_task_rejects_invalid_periods_before_repository_access():
    with patch(
        "apps.equity.application.tasks_valuation_sync.get_equity_stock_repository"
    ) as stock_repository:
        result = sync_financial_data_task(periods=0)

    assert result == {
        "success": False,
        "error": "periods 必须在 1..40 之间",
        "stage": "input",
    }
    stock_repository.assert_not_called()
