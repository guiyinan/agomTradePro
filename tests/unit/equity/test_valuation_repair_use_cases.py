from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from apps.equity.application.use_cases_valuation_repair import (
    GetValuationPercentileHistoryRequest,
    GetValuationPercentileHistoryUseCase,
    GetValuationRepairStatusRequest,
    GetValuationRepairStatusUseCase,
    ScanValuationRepairsRequest,
    ScanValuationRepairsUseCase,
)
from apps.equity.domain.entities_valuation_repair import (
    DEFAULT_VALUATION_REPAIR_CONFIG,
    ValuationRepairPhase,
)


def test_status_rejects_invalid_inputs_before_repository_access() -> None:
    repository = Mock()
    response = GetValuationRepairStatusUseCase(repository).execute(
        GetValuationRepairStatusRequest(stock_code="../bad", lookback_days=True)
    )

    assert response.success is False
    assert response.error == "获取估值修复状态失败"
    repository.get_stock_info.assert_not_called()


def test_percentile_history_preserves_zero_valuation(monkeypatch) -> None:
    repository = Mock()
    repository.get_valuation_history.return_value = [
        SimpleNamespace(trade_date=date(2026, 7, 25), pe=0, pb=0)
    ]
    captured: dict[str, object] = {}

    def fake_build(history, **kwargs):
        captured["history"] = history
        return []

    monkeypatch.setattr(
        "apps.equity.application.use_cases_valuation_repair.build_percentile_series",
        fake_build,
    )
    monkeypatch.setattr(
        "apps.equity.application.use_cases_valuation_repair.get_valuation_repair_config",
        lambda **_kwargs: DEFAULT_VALUATION_REPAIR_CONFIG,
    )

    response = GetValuationPercentileHistoryUseCase(repository).execute(
        GetValuationPercentileHistoryRequest("000001.SZ", lookback_days=20)
    )

    assert response.success is True
    assert captured["history"] == [{"trade_date": date(2026, 7, 25), "pe": 0.0, "pb": 0.0}]


def test_scan_reports_partial_failure_without_leaking_exception(monkeypatch) -> None:
    stock_repository = Mock()
    stock_repository.list_active_stock_codes.return_value = ["OK", "FAIL"]
    repair_repository = Mock()
    use_case = ScanValuationRepairsUseCase(stock_repository, repair_repository)
    monkeypatch.setattr(
        use_case,
        "_calculate_status",
        Mock(
            side_effect=[
                SimpleNamespace(phase=ValuationRepairPhase.NO_REPAIR_NEEDED.value),
                RuntimeError("database-password"),
            ]
        ),
    )

    response = use_case.execute(ScanValuationRepairsRequest(lookback_days=20, limit=2))

    assert response.success is False
    assert response.scanned_count == 2
    assert response.failed_count == 1
    assert response.error == "部分股票扫描失败"
    assert "database-password" not in response.error
