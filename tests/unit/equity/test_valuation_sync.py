from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.equity.application.use_cases_valuation_sync import (
    BackfillEquityValuationRequest,
    BackfillEquityValuationUseCase,
    SyncEquityValuationRequest,
    SyncEquityValuationUseCase,
)
from apps.equity.domain.entities import ValuationMetrics


class DummyRepo:
    def __init__(self) -> None:
        self.saved: list[ValuationMetrics] = []
        self.list_calls = 0

    def list_active_stock_codes(self) -> list[str]:
        self.list_calls += 1
        return ["000001.SZ", "000002.SZ", "000003.SZ"]

    def save_valuation(self, valuation: ValuationMetrics) -> None:
        self.saved.append(valuation)


class DummyGateway:
    def __init__(self, provider_name: str, batches: list[list[ValuationMetrics]]) -> None:
        self.provider_name = provider_name
        self.batches = list(batches)

    def fetch(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> SimpleNamespace:
        del stock_code, start_date, end_date
        records = self.batches.pop(0) if self.batches else []
        return SimpleNamespace(source_provider=self.provider_name, records=records)


class DummyDataCenterSync:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def execute(self, request: object) -> object:
        self.requests.append(request)
        return SimpleNamespace(stored_count=1)


def _provider_resolver(source_type: str) -> tuple[int, str] | None:
    return {
        "akshare": (11, "akshare-main"),
        "tushare": (22, "tushare-backup"),
    }.get(source_type)


def _sample_metric(
    stock_code: str,
    trade_date: date,
    source_provider: str = "akshare-main",
) -> ValuationMetrics:
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


def _use_case(
    repo: DummyRepo,
    *,
    gateways: dict[str, DummyGateway],
    sync_service: DummyDataCenterSync | None = None,
) -> SyncEquityValuationUseCase:
    return SyncEquityValuationUseCase(
        stock_repository=repo,
        provider_resolver=_provider_resolver,
        gateway_factory=lambda provider_name: gateways[provider_name],
        data_center_sync_use_case=sync_service or DummyDataCenterSync(),
    )


def test_sync_use_case_persists_records_from_configured_primary_provider() -> None:
    repo = DummyRepo()
    metric = _sample_metric("000001.SZ", date(2026, 3, 10))
    use_case = _use_case(
        repo,
        gateways={
            "akshare-main": DummyGateway("akshare-main", [[metric]]),
            "tushare-backup": DummyGateway("tushare-backup", []),
        },
    )

    response = use_case.execute(
        SyncEquityValuationRequest(
            stock_codes=["000001.sz"],
            start_date=date(2026, 3, 10),
            end_date=date(2026, 3, 10),
        )
    )

    assert response.success is True
    assert response.data is not None
    assert response.data["synced_count"] == 1
    assert repo.saved == [metric]


def test_sync_use_case_warms_data_center_when_primary_gateway_empty() -> None:
    repo = DummyRepo()
    metric = _sample_metric("000001.SZ", date(2026, 3, 10))
    sync_service = DummyDataCenterSync()
    use_case = _use_case(
        repo,
        gateways={
            "akshare-main": DummyGateway("akshare-main", [[], [metric]]),
            "tushare-backup": DummyGateway("tushare-backup", []),
        },
        sync_service=sync_service,
    )

    response = use_case.execute(
        SyncEquityValuationRequest(
            stock_codes=["000001.SZ"],
            start_date=date(2026, 3, 10),
            end_date=date(2026, 3, 10),
        )
    )

    assert response.success is True
    assert response.data is not None
    assert response.data["synced_count"] == 1
    assert len(sync_service.requests) == 1


def test_sync_use_case_uses_configured_fallback_and_counts_it() -> None:
    repo = DummyRepo()
    metric = _sample_metric(
        "000001.SZ",
        date(2026, 3, 10),
        source_provider="tushare-backup",
    )
    sync_service = DummyDataCenterSync()
    use_case = _use_case(
        repo,
        gateways={
            "akshare-main": DummyGateway("akshare-main", [[], []]),
            "tushare-backup": DummyGateway("tushare-backup", [[metric]]),
        },
        sync_service=sync_service,
    )

    response = use_case.execute(
        SyncEquityValuationRequest(
            stock_codes=["000001.SZ"],
            start_date=date(2026, 3, 10),
            end_date=date(2026, 3, 10),
        )
    )

    assert response.success is True
    assert response.data is not None
    assert response.data["fallback_used_count"] == 1
    assert len(sync_service.requests) == 2


def test_sync_use_case_fails_when_no_record_is_written_and_hides_exception() -> None:
    repo = DummyRepo()

    class FailingGateway(DummyGateway):
        def fetch(
            self,
            stock_code: str,
            start_date: date,
            end_date: date,
        ) -> SimpleNamespace:
            del stock_code, start_date, end_date
            raise RuntimeError("token=private")

    use_case = _use_case(
        repo,
        gateways={
            "akshare-main": FailingGateway("akshare-main", []),
            "tushare-backup": DummyGateway("tushare-backup", []),
        },
    )

    response = use_case.execute(
        SyncEquityValuationRequest(
            stock_codes=["000001.SZ"],
            start_date=date(2026, 3, 10),
            end_date=date(2026, 3, 10),
        )
    )

    assert response.success is False
    assert response.error == "估值同步未写入任何记录"
    assert response.data is not None
    assert response.data["errors"] == ["000001.SZ: 同步失败"]
    assert "private" not in str(response)


def test_sync_use_case_rejects_explicit_empty_universe_without_expanding() -> None:
    repo = DummyRepo()
    use_case = _use_case(
        repo,
        gateways={
            "akshare-main": DummyGateway("akshare-main", []),
            "tushare-backup": DummyGateway("tushare-backup", []),
        },
    )

    response = use_case.execute(SyncEquityValuationRequest(stock_codes=[]))

    assert response.success is False
    assert response.error == "未找到可同步股票"
    assert repo.list_calls == 0


@pytest.mark.parametrize(
    "sync_request",
    [
        SyncEquityValuationRequest(days_back=0),
        SyncEquityValuationRequest(days_back=True),
        SyncEquityValuationRequest(
            start_date=date(2026, 3, 11),
            end_date=date(2026, 3, 10),
        ),
        SyncEquityValuationRequest(end_date=date.today() + timedelta(days=1)),
        SyncEquityValuationRequest(primary_source="akshare", fallback_source="akshare"),
    ],
)
def test_sync_use_case_rejects_invalid_request_before_repository_access(
    sync_request: SyncEquityValuationRequest,
) -> None:
    repo = DummyRepo()
    use_case = _use_case(
        repo,
        gateways={
            "akshare-main": DummyGateway("akshare-main", []),
            "tushare-backup": DummyGateway("tushare-backup", []),
        },
    )

    response = use_case.execute(sync_request)

    assert response.success is False
    assert repo.list_calls == 0


def test_backfill_use_case_batches_requests() -> None:
    repo = DummyRepo()
    sync_use_case = MagicMock()
    sync_use_case.execute.return_value = SimpleNamespace(
        success=True,
        data={"synced_count": 10},
        error=None,
    )
    use_case = BackfillEquityValuationUseCase(
        stock_repository=repo,
        sync_use_case=sync_use_case,
    )

    response = use_case.execute(BackfillEquityValuationRequest(years=3, batch_size=2))

    assert response.success is True
    assert response.data is not None
    assert response.data["total_batches"] == 2


def test_backfill_reports_partial_batch_failure_truthfully() -> None:
    repo = DummyRepo()
    sync_use_case = MagicMock()
    sync_use_case.execute.side_effect = [
        SimpleNamespace(success=True, data={"synced_count": 2}, error=None),
        SimpleNamespace(success=False, data=None, error="private failure"),
    ]
    use_case = BackfillEquityValuationUseCase(
        stock_repository=repo,
        sync_use_case=sync_use_case,
    )

    response = use_case.execute(BackfillEquityValuationRequest(years=3, batch_size=2))

    assert response.success is False
    assert response.error == "部分估值回填批次失败"
    assert response.data is not None
    assert response.data["failed_batches"] == 1
    assert "private failure" not in str(response)
