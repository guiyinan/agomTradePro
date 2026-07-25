from datetime import date, timedelta
from types import SimpleNamespace

from apps.equity.application.use_cases_valuation_sync import (
    GetEquityValuationFreshnessUseCase,
    ValidateEquityValuationQualityRequest,
    ValidateEquityValuationQualityUseCase,
)
from apps.equity.infrastructure.valuation_repair_repositories import (
    build_quality_snapshot,
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
        SimpleNamespace(
            stock_code="000001.SZ",
            is_valid=True,
            quality_flag="ok",
            source_provider="akshare-main",
        ),
        SimpleNamespace(
            stock_code="000002.SZ",
            is_valid=False,
            quality_flag="invalid_pb",
            source_provider="akshare-main",
        ),
    ]
    stock_repo = DummyStockRepo(date(2026, 3, 10), valuations, ["000001.SZ", "000002.SZ"])
    quality_repo = DummyQualityRepo()

    use_case = ValidateEquityValuationQualityUseCase(
        stock_repo,
        quality_repo,
        provider_resolver=lambda source_type: (
            (1, "akshare-main") if source_type == "akshare" else None
        ),
    )
    response = use_case.execute(ValidateEquityValuationQualityRequest())

    assert response.success is True
    assert response.data["primary_source"] == "akshare-main"
    assert response.data["fallback_used_count"] == 0
    assert response.data["is_gate_passed"] is False
    assert "invalid_pb" in response.data["gate_reason"]


def test_quality_snapshot_does_not_count_duplicate_stock_rows() -> None:
    row = SimpleNamespace(
        stock_code="000001.SZ",
        is_valid=True,
        quality_flag="ok",
        source_provider="akshare-main",
    )

    snapshot = build_quality_snapshot(
        as_of_date=date(2026, 3, 10),
        expected_stock_count=2,
        valuations=[row, row],
        primary_source=" akshare-main ",
    )

    assert snapshot["synced_stock_count"] == 1
    assert snapshot["coverage_ratio"] == 0.5
    assert snapshot["primary_source"] == "akshare-main"


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


def test_freshness_is_critical_when_current_date_fails_quality_gate():
    quality_repo = DummyQualityRepo()
    quality_repo.snapshot = {
        "as_of_date": date.today(),
        "coverage_ratio": 0.0255,
        "is_gate_passed": False,
    }
    stock_repo = DummyStockRepo(date.today(), [], [])
    use_case = GetEquityValuationFreshnessUseCase(stock_repo, quality_repo)

    response = use_case.execute()

    assert response.success is True
    assert response.data["lag_days"] == 0
    assert response.data["freshness_status"] == "critical"
    assert response.data["is_gate_passed"] is False


def test_freshness_is_critical_when_quality_snapshot_is_stale():
    quality_repo = DummyQualityRepo()
    quality_repo.snapshot = {
        "as_of_date": date.today() - timedelta(days=1),
        "coverage_ratio": 1.0,
        "is_gate_passed": True,
    }
    stock_repo = DummyStockRepo(date.today(), [], [])
    use_case = GetEquityValuationFreshnessUseCase(stock_repo, quality_repo)

    response = use_case.execute()

    assert response.success is True
    assert response.data["freshness_status"] == "critical"
    assert response.data["coverage_ratio"] is None
    assert response.data["is_gate_passed"] is False


def test_freshness_rejects_future_valuation_date():
    use_case = GetEquityValuationFreshnessUseCase(
        DummyStockRepo(date.today() + timedelta(days=1), [], []),
        DummyQualityRepo(),
    )

    response = use_case.execute()

    assert response.success is False
    assert response.error == "最新估值日期不能晚于今天"
