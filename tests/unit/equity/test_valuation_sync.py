from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from apps.equity.application.use_cases_valuation_sync import (
    BackfillEquityValuationRequest,
    BackfillEquityValuationUseCase,
    SyncEquityValuationRequest,
    SyncEquityValuationUseCase,
)
from apps.equity.domain.entities import ValuationMetrics


class DummyRepo:
    def __init__(self):
        self.saved = []

    def list_active_stock_codes(self):
        return ["000001.SZ", "000002.SZ", "000003.SZ"]

    def save_valuation(self, valuation):
        self.saved.append(valuation)


def _sample_metric(stock_code: str, trade_date: date, source_provider: str = "akshare") -> ValuationMetrics:
    return ValuationMetrics(
        stock_code=stock_code,
        trade_date=trade_date,
        pe=0.0,
        pb=1.2,
        ps=0.0,
        total_mv=Decimal("100000000"),
        circ_mv=Decimal("100000000"),
        dividend_yield=0.0,
        source_provider=source_provider,
        pe_type="ttm",
        is_valid=True,
        quality_flag="ok",
    )


def test_sync_use_case_persists_records_from_primary_gateway():
    repo = DummyRepo()
    use_case = SyncEquityValuationUseCase(stock_repository=repo)

    with patch.object(use_case.akshare_gateway, "fetch") as mock_fetch:
        mock_fetch.return_value.records = [_sample_metric("000001.SZ", date(2026, 3, 10))]
        response = use_case.execute(
            SyncEquityValuationRequest(stock_codes=["000001.SZ"], start_date=date(2026, 3, 10), end_date=date(2026, 3, 10))
        )

    assert response.success is True
    assert response.data["synced_count"] == 1
    assert len(repo.saved) == 1


def test_sync_use_case_warms_data_center_when_primary_gateway_empty():
    repo = DummyRepo()
    use_case = SyncEquityValuationUseCase(stock_repository=repo)
    empty_batch = SimpleNamespace(records=[])
    loaded_batch = SimpleNamespace(
        records=[_sample_metric("000001.SZ", date(2026, 3, 10))]
    )

    with (
        patch.object(use_case.akshare_gateway, "fetch", side_effect=[empty_batch, loaded_batch]),
        patch.object(use_case, "_sync_data_center_valuation") as mock_sync,
    ):
        response = use_case.execute(
            SyncEquityValuationRequest(
                stock_codes=["000001.SZ"],
                start_date=date(2026, 3, 10),
                end_date=date(2026, 3, 10),
            )
        )

    assert response.success is True
    assert response.data["synced_count"] == 1
    assert len(repo.saved) == 1
    mock_sync.assert_called_once()


def test_backfill_use_case_batches_requests():
    repo = DummyRepo()
    use_case = BackfillEquityValuationUseCase(stock_repository=repo)

    with patch.object(use_case.sync_use_case, "execute") as mock_execute:
        mock_execute.return_value.success = True
        mock_execute.return_value.data = {"synced_count": 10}
        response = use_case.execute(BackfillEquityValuationRequest(years=3, batch_size=2))

    assert response.success is True
    assert response.data["total_batches"] == 2
