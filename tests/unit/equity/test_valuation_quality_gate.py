from datetime import date, timedelta
from types import SimpleNamespace

from apps.equity.application.use_cases_valuation_sync import (
    ValidateEquityValuationQualityUseCase,
    ValidateEquityValuationQualityRequest,
    GetEquityValuationFreshnessUseCase,
)


class DummyStockRepo:
    def __init__(self, latest_date, valuations, active_codes):
        self._latest_date = latest_date
        self._valuations = valuations
        self._active_codes = active_codes

    def get_latest_valuation_date(self):
        return self._latest_date

    def list_active_stock_codes(self):
        return self._active_codes

    def get_valuation_models_by_date(self, as_of_date):
        return self._valuations


class DummyQualityRepo:
    def __init__(self):
        self.snapshot = None

    def upsert_snapshot(self, snapshot):
        self.snapshot = snapshot

    def get_latest_snapshot(self):
        return SimpleNamespace(**self.snapshot) if self.snapshot else None


def test_validate_quality_builds_gate_failed_snapshot():
    valuations = [
        SimpleNamespace(is_valid=True, quality_flag="ok", source_provider="akshare"),
        SimpleNamespace(is_valid=False, quality_flag="invalid_pb", source_provider="akshare"),
    ]
    stock_repo = DummyStockRepo(date(2026, 3, 10), valuations, ["000001.SZ", "000002.SZ"])
    quality_repo = DummyQualityRepo()

    use_case = ValidateEquityValuationQualityUseCase(stock_repo, quality_repo)
    response = use_case.execute(ValidateEquityValuationQualityRequest())

    assert response.success is True
    assert response.data["is_gate_passed"] is False
    assert "invalid_pb" in response.data["gate_reason"]


def test_freshness_returns_warning_for_two_day_lag():
    quality_repo = DummyQualityRepo()
    quality_repo.snapshot = {
        "as_of_date": date.today() - timedelta(days=2),
        "coverage_ratio": 0.98,
        "is_gate_passed": True,
    }
    stock_repo = DummyStockRepo(date.today() - timedelta(days=2), [], [])
    use_case = GetEquityValuationFreshnessUseCase(stock_repo, quality_repo)

    response = use_case.execute()

    assert response.success is True
    assert response.data["freshness_status"] == "warning"
