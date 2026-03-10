from unittest.mock import MagicMock, patch

from apps.equity.application.tasks_valuation_sync import sync_validate_scan_equity_valuation_task


def test_sync_validate_scan_task_skips_scan_when_gate_blocked():
    with patch("apps.equity.application.tasks_valuation_sync.SyncEquityValuationUseCase") as SyncUC, \
         patch("apps.equity.application.tasks_valuation_sync.ValidateEquityValuationQualityUseCase") as ValidateUC, \
         patch("apps.equity.application.tasks_valuation_sync.ScanValuationRepairsUseCase") as ScanUC:
        SyncUC.return_value.execute.return_value = MagicMock(success=True, data={"synced_count": 10})
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
    with patch("apps.equity.application.tasks_valuation_sync.SyncEquityValuationUseCase") as SyncUC, \
         patch("apps.equity.application.tasks_valuation_sync.ValidateEquityValuationQualityUseCase") as ValidateUC, \
         patch("apps.equity.application.tasks_valuation_sync.ScanValuationRepairsUseCase") as ScanUC:
        SyncUC.return_value.execute.return_value = MagicMock(success=True, data={"synced_count": 10})
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
