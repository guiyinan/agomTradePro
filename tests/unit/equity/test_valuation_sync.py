import importlib.util
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.data_center.application.dtos import SyncResult

_candidate_root = Path(__file__).resolve().parents[3]
_candidate_use_case_path = _candidate_root / "apps/equity/application/use_cases_valuation_sync.py"
_candidate_use_case_spec = importlib.util.spec_from_file_location(
    "apps.equity.application.use_cases_valuation_sync",
    _candidate_use_case_path,
)
assert _candidate_use_case_spec is not None
assert _candidate_use_case_spec.loader is not None
_candidate_use_case_module = importlib.util.module_from_spec(_candidate_use_case_spec)
sys.modules[_candidate_use_case_spec.name] = _candidate_use_case_module
_candidate_use_case_spec.loader.exec_module(_candidate_use_case_module)
_candidate_writer_path = (
    _candidate_root / "apps/equity/infrastructure/fundamentals_write_repository.py"
)
_candidate_writer_spec = importlib.util.spec_from_file_location(
    "apps.equity.infrastructure.fundamentals_write_repository",
    _candidate_writer_path,
)
assert _candidate_writer_spec is not None
assert _candidate_writer_spec.loader is not None
_candidate_writer_module = importlib.util.module_from_spec(_candidate_writer_spec)
sys.modules[_candidate_writer_spec.name] = _candidate_writer_module
_candidate_writer_spec.loader.exec_module(_candidate_writer_module)

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

    def save_valuation(self, valuation: ValuationMetrics) -> int:
        self.saved.append(valuation)
        return 1


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

    def execute(self, request: object) -> SyncResult:
        self.requests.append(request)
        return SyncResult(
            domain="valuation",
            provider_name="test-provider",
            stored_count=1,
            status="success",
        )


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


def test_sync_zero_processed_records_does_not_count_skipped_writer_call_as_synced() -> None:
    class SkippingRepo(DummyRepo):
        def save_valuation(self, valuation: ValuationMetrics) -> int:
            self.saved.append(valuation)
            return 0

    repo = SkippingRepo()
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
            stock_codes=["000001.SZ"],
            start_date=date(2026, 3, 10),
            end_date=date(2026, 3, 10),
        )
    )

    assert response.success is False
    assert response.data is not None
    assert response.data["outcome"] == "failed"
    assert response.data["succeeded_stock_count"] == 0
    assert response.data["failed_stock_count"] == 1
    assert response.data["synced_count"] == 0
    assert response.data["confirmed_equity_writer_record_count"] == 0
    assert response.data["stored_record_count"] == 0
    assert repo.saved == [metric]


def test_distinct_data_center_writes_for_multiple_stocks_keep_exact_aggregate_count() -> None:
    class SkippingRepo(DummyRepo):
        def save_valuation(self, valuation: ValuationMetrics) -> int:
            self.saved.append(valuation)
            return 0

    class PerStockWarmGateway(DummyGateway):
        def __init__(self, records: dict[str, ValuationMetrics]) -> None:
            super().__init__("akshare-main", [])
            self.records = records
            self.fetch_counts: dict[str, int] = {}

        def fetch(
            self,
            stock_code: str,
            start_date: date,
            end_date: date,
        ) -> SimpleNamespace:
            del start_date, end_date
            fetch_count = self.fetch_counts.get(stock_code, 0) + 1
            self.fetch_counts[stock_code] = fetch_count
            records = [] if fetch_count == 1 else [self.records[stock_code]]
            return SimpleNamespace(source_provider="akshare-main", records=records)

    repo = SkippingRepo()
    metrics = {
        "000001.SZ": _sample_metric("000001.SZ", date(2026, 3, 10)),
        "000002.SZ": _sample_metric("000002.SZ", date(2026, 3, 10)),
    }
    sync_service = DummyDataCenterSync()
    use_case = _use_case(
        repo,
        gateways={
            "akshare-main": PerStockWarmGateway(metrics),
            "tushare-backup": DummyGateway("tushare-backup", []),
        },
        sync_service=sync_service,
    )

    response = use_case.execute(
        SyncEquityValuationRequest(
            stock_codes=list(metrics),
            start_date=date(2026, 3, 10),
            end_date=date(2026, 3, 10),
        )
    )

    assert response.data is not None
    assert response.data["data_center_confirmed_processed_record_count"] == 2
    assert response.data["confirmed_equity_writer_record_count"] == 0
    assert response.data["synced_count"] == 0
    assert response.data["stored_record_count"] == 2
    assert response.data["counts_unavailable"] is False
    assert response.data["stored_record_count_unavailable_reasons"] == []
    assert len(sync_service.requests) == 2
    assert repo.saved == list(metrics.values())


def test_repeated_data_center_warm_writes_for_one_stock_keep_aggregate_unknown() -> None:
    repo = DummyRepo()
    sync_service = DummyDataCenterSync()
    use_case = _use_case(
        repo,
        gateways={
            "akshare-main": DummyGateway("akshare-main", [[], []]),
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

    assert response.data is not None
    assert response.data["data_center_confirmed_processed_record_count"] == 2
    assert response.data["stored_record_count"] is None
    assert response.data["counts_unavailable"] is True
    assert (
        "canonical_write_stages_may_overlap"
        in response.data["stored_record_count_unavailable_reasons"]
    )
    assert len(sync_service.requests) == 2
    assert repo.saved == []


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
    assert response.data["outcome"] == "success"
    assert response.data["stored_record_count"] is None
    assert response.data["data_center_confirmed_processed_record_count"] == 1
    assert response.data["confirmed_equity_writer_record_count"] == 1
    assert response.data["counts_unavailable"] is True
    assert (
        "canonical_write_stages_may_overlap"
        in response.data["stored_record_count_unavailable_reasons"]
    )
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


def test_default_sync_processes_complete_repository_universe_above_5000() -> None:
    class LargeUniverseRepo(DummyRepo):
        def __init__(self) -> None:
            super().__init__()
            self.codes = [f"{index + 100000:06d}.SZ" for index in range(5001)]

        def list_active_stock_codes(self) -> list[str]:
            self.list_calls += 1
            return list(self.codes)

    class RecordingGateway:
        def __init__(self, provider_name: str) -> None:
            self.provider_name = provider_name
            self.requested: list[str] = []

        def fetch(
            self,
            stock_code: str,
            start_date: date,
            end_date: date,
        ) -> SimpleNamespace:
            del start_date, end_date
            self.requested.append(stock_code)
            return SimpleNamespace(
                source_provider=self.provider_name,
                records=[_sample_metric(stock_code, date(2026, 3, 10), self.provider_name)],
            )

    repo = LargeUniverseRepo()
    primary = RecordingGateway("akshare-main")
    fallback = RecordingGateway("tushare-backup")
    use_case = _use_case(
        repo,
        gateways={"akshare-main": primary, "tushare-backup": fallback},
    )

    response = use_case.execute(
        SyncEquityValuationRequest(
            start_date=date(2026, 3, 10),
            end_date=date(2026, 3, 10),
        )
    )

    assert response.success is True
    assert response.data is not None
    assert response.data["outcome"] == "success"
    assert response.data["requested_stock_count"] == 5001
    assert response.data["succeeded_stock_count"] == 5001
    assert response.data["failed_stock_count"] == 0
    assert response.data["stored_record_count"] == 5001
    assert response.data["scope_count"] == 5001
    assert isinstance(response.data["scope_sha256"], str)
    assert len(response.data["scope_sha256"]) == 64
    assert repo.list_calls == 1
    assert len(primary.requested) == 5001
    assert primary.requested == repo.codes
    assert fallback.requested == []


def test_explicit_stock_list_keeps_5000_limit_before_provider_access() -> None:
    repo = DummyRepo()
    primary = DummyGateway("akshare-main", [])
    fallback = DummyGateway("tushare-backup", [])
    use_case = _use_case(
        repo,
        gateways={"akshare-main": primary, "tushare-backup": fallback},
    )
    codes = [f"{index + 100000:06d}.SZ" for index in range(5001)]

    response = use_case.execute(SyncEquityValuationRequest(stock_codes=codes))

    assert response.success is False
    assert response.error == "stock_codes 最多允许 5000 项"
    assert primary.batches == []
    assert fallback.batches == []
    assert repo.list_calls == 0


def test_quality_denominator_uses_complete_repository_universe(monkeypatch) -> None:
    class LargeUniverseRepo(DummyRepo):
        def list_active_stock_codes(self) -> list[str]:
            self.list_calls += 1
            return [f"{index + 100000:06d}.SZ" for index in range(5001)]

        def get_valuation_models_by_date(self, as_of_date: date) -> list[object]:
            del as_of_date
            return []

    class QualityRepo:
        def __init__(self) -> None:
            self.saved: list[object] = []

        def upsert_snapshot(self, snapshot: object) -> None:
            self.saved.append(snapshot)

        def get_latest_snapshot(self) -> object | None:
            return None

    captured: dict[str, object] = {}

    def build_snapshot(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "as_of_date": date(2026, 3, 10),
            "expected_stock_count": kwargs["expected_stock_count"],
        }

    monkeypatch.setattr(
        _candidate_use_case_module,
        "build_quality_snapshot",
        build_snapshot,
    )
    stock_repo = LargeUniverseRepo()
    quality_repo = QualityRepo()
    quality_use_case = _candidate_use_case_module.ValidateEquityValuationQualityUseCase(
        stock_repo,
        quality_repo,
        provider_resolver=_provider_resolver,
    )

    response = quality_use_case.execute(
        _candidate_use_case_module.ValidateEquityValuationQualityRequest(
            as_of_date=date(2026, 3, 10)
        )
    )

    assert response.success is True
    assert captured["expected_stock_count"] == 5001
    assert stock_repo.list_calls == 1
    assert len(quality_repo.saved) == 1


def test_quality_reuses_frozen_scope_and_excludes_out_of_scope_facts() -> None:
    class ChangingUniverseRepo(DummyRepo):
        def __init__(self) -> None:
            super().__init__()
            self.codes = ["000001.SZ", "000002.SZ"]
            self.valuations = [
                _sample_metric("000001.SZ", date(2026, 3, 10)),
                _sample_metric("000003.SZ", date(2026, 3, 10)),
            ]

        def list_active_stock_codes(self) -> list[str]:
            self.list_calls += 1
            return list(self.codes)

        def get_valuation_models_by_date(self, as_of_date: date) -> list[object]:
            del as_of_date
            return list(self.valuations)

    class QualityRepo:
        def __init__(self) -> None:
            self.saved: list[object] = []

        def upsert_snapshot(self, snapshot: object) -> None:
            self.saved.append(snapshot)

        def get_latest_snapshot(self) -> object | None:
            return None

    stock_repo = ChangingUniverseRepo()
    scope_owner = _use_case(
        stock_repo,
        gateways={
            "akshare-main": DummyGateway(
                "akshare-main",
                [
                    [_sample_metric("000001.SZ", date(2026, 3, 10))],
                    [_sample_metric("000002.SZ", date(2026, 3, 10))],
                ],
            ),
            "tushare-backup": DummyGateway("tushare-backup", []),
        },
    )
    sync_response = scope_owner.execute(
        SyncEquityValuationRequest(
            start_date=date(2026, 3, 10),
            end_date=date(2026, 3, 10),
        )
    )
    assert sync_response.success is True
    assert sync_response.data is not None
    frozen_scope = sync_response._frozen_scope
    assert frozen_scope is not None
    stock_repo.codes = ["000001.SZ", "000003.SZ"]
    quality_repo = QualityRepo()
    quality_use_case = _candidate_use_case_module.ValidateEquityValuationQualityUseCase(
        stock_repo,
        quality_repo,
        provider_resolver=_provider_resolver,
    )

    response = quality_use_case.execute(
        _candidate_use_case_module.ValidateEquityValuationQualityRequest(
            as_of_date=date(2026, 3, 10)
        ),
        _frozen_scope=frozen_scope,
    )

    assert response.success is True
    assert response.data is not None
    assert response.data["expected_stock_count"] == 2
    assert response.data["synced_stock_count"] == 1
    assert response.data["coverage_ratio"] == 0.5
    assert response.data["is_gate_passed"] is False
    assert response.data["scope_sha256"] == frozen_scope.identity
    assert response.data["scope_count"] == 2
    assert response.data["scope_sha256"] == sync_response.data["scope_sha256"]
    assert stock_repo.list_calls == 1


def test_quality_excludes_out_of_scope_fact_from_coverage_numerator() -> None:
    class ScopedRepo(DummyRepo):
        def list_active_stock_codes(self) -> list[str]:
            self.list_calls += 1
            return ["000001.SZ", "000002.SZ"]

        def get_valuation_models_by_date(self, as_of_date: date) -> list[object]:
            del as_of_date
            return [
                _sample_metric("000001.SZ", date(2026, 3, 10)),
                _sample_metric("000003.SZ", date(2026, 3, 10)),
            ]

    class QualityRepo:
        def upsert_snapshot(self, snapshot: object) -> None:
            del snapshot

        def get_latest_snapshot(self) -> object | None:
            return None

    stock_repo = ScopedRepo()
    use_case = _candidate_use_case_module.ValidateEquityValuationQualityUseCase(
        stock_repo,
        QualityRepo(),
        provider_resolver=_provider_resolver,
    )

    response = use_case.execute(
        _candidate_use_case_module.ValidateEquityValuationQualityRequest(
            as_of_date=date(2026, 3, 10)
        )
    )

    assert response.success is True
    assert response.data is not None
    assert response.data["expected_stock_count"] == 2
    assert response.data["synced_stock_count"] == 1
    assert response.data["coverage_ratio"] == pytest.approx(0.5)
    assert response.data["is_gate_passed"] is False


def test_backfill_batches_complete_repository_universe_above_5000() -> None:
    class LargeUniverseRepo(DummyRepo):
        def list_active_stock_codes(self) -> list[str]:
            self.list_calls += 1
            return [f"{index + 100000:06d}.SZ" for index in range(5001)]

    repo = LargeUniverseRepo()
    sync_use_case = MagicMock()
    sync_use_case.execute.side_effect = [
        SimpleNamespace(
            success=True,
            data={
                "outcome": "success",
                "requested_stock_count": count,
                "succeeded_stock_count": count,
                "failed_stock_count": 0,
                "synced_count": count,
                "stored_record_count": count,
                "confirmed_equity_writer_record_count": count,
                "data_center_confirmed_processed_record_count": 0,
                "counts_unavailable": False,
                "stored_record_count_unavailable_reasons": [],
            },
            error=None,
        )
        for count in (2000, 2000, 1001)
    ]
    use_case = BackfillEquityValuationUseCase(stock_repository=repo, sync_use_case=sync_use_case)

    response = use_case.execute(BackfillEquityValuationRequest(years=1, batch_size=2000))

    assert response.success is True
    assert response.data is not None
    assert response.data["total_batches"] == 3
    assert response.data["requested_stock_count"] == 5001
    assert response.data["succeeded_stock_count"] == 5001
    assert response.data["stored_record_count"] == 5001
    assert [len(call.args[0].stock_codes) for call in sync_use_case.execute.call_args_list] == [
        2000,
        2000,
        1001,
    ]
    assert repo.list_calls == 1


def test_backfill_preserves_prior_counts_when_later_batch_outcome_is_unknown() -> None:
    repo = DummyRepo()
    sync_use_case = MagicMock()
    sync_use_case.execute.side_effect = [
        SimpleNamespace(
            success=True,
            data={
                "outcome": "success",
                "requested_stock_count": 2,
                "succeeded_stock_count": 2,
                "failed_stock_count": 0,
                "stored_record_count": 2,
                "confirmed_equity_writer_record_count": 2,
                "data_center_confirmed_processed_record_count": 0,
                "stored_record_count_unavailable_reasons": [],
            },
            error=None,
        ),
        RuntimeError("commit outcome unknown"),
    ]
    use_case = BackfillEquityValuationUseCase(
        stock_repository=repo,
        sync_use_case=sync_use_case,
    )

    response = use_case.execute(BackfillEquityValuationRequest(years=1, batch_size=2))

    assert response.success is False
    assert response.data is not None
    assert response.data["outcome"] == "partial"
    assert response.data["requested_stock_count"] == 3
    assert response.data["succeeded_stock_count"] == 2
    assert response.data["failed_stock_count"] == 1
    assert response.data["confirmed_equity_writer_record_count"] == 2
    assert response.data["equity_writer_outcome_unknown"] is True
    assert response.data["stored_record_count"] is None
    assert "batch_sync_outcome_unknown" in response.data["stored_record_count_unavailable_reasons"]
    assert response.data["results"][0]["stored_record_count"] == 2
    assert response.data["results"][1]["stored_record_count"] is None


def test_sync_partial_write_exception_preserves_confirmed_count_and_unknown_total() -> None:
    class PartialWriteRepo(DummyRepo):
        def save_valuation(self, valuation: ValuationMetrics) -> int:
            self.saved.append(valuation)
            if valuation.stock_code == "000002.SZ":
                raise RuntimeError("commit result unknown")
            return 1

    repo = PartialWriteRepo()
    metrics = [
        _sample_metric("000001.SZ", date(2026, 3, 10)),
        _sample_metric("000002.SZ", date(2026, 3, 10)),
    ]

    class PerCodeGateway:
        def __init__(self, provider_name: str) -> None:
            self.provider_name = provider_name

        def fetch(
            self,
            stock_code: str,
            start_date: date,
            end_date: date,
        ) -> SimpleNamespace:
            del start_date, end_date
            record = next(item for item in metrics if item.stock_code == stock_code)
            return SimpleNamespace(source_provider=self.provider_name, records=[record])

    response = _use_case(
        repo,
        gateways={
            "akshare-main": PerCodeGateway("akshare-main"),
            "tushare-backup": PerCodeGateway("tushare-backup"),
        },
    ).execute(
        SyncEquityValuationRequest(
            stock_codes=["000001.SZ", "000002.SZ"],
            start_date=date(2026, 3, 10),
            end_date=date(2026, 3, 10),
        )
    )

    assert response.success is False
    assert response.data is not None
    assert response.data["outcome"] == "partial"
    assert response.data["requested_stock_count"] == 2
    assert response.data["succeeded_stock_count"] == 1
    assert response.data["failed_stock_count"] == 1
    assert response.data["confirmed_equity_writer_record_count"] == 1
    assert response.data["stored_record_count"] is None
    assert response.data["synced_count"] is None
    assert response.data["counts_unavailable"] is True
    assert (
        "equity_writer_outcome_unknown" in response.data["stored_record_count_unavailable_reasons"]
    )


def test_equity_valuation_writer_returns_bulk_count_and_zero_for_invalid_fact() -> None:
    StockFundamentalsWriteRepositoryMixin = (
        _candidate_writer_module.StockFundamentalsWriteRepositoryMixin
    )

    class Writer(StockFundamentalsWriteRepositoryMixin):
        def __init__(self, bulk_upsert: MagicMock) -> None:
            self._dc_valuation_repo = SimpleNamespace(bulk_upsert=bulk_upsert)

        def _valuation_entity_to_dc_fact(self, valuation: ValuationMetrics) -> object:
            return valuation

    bulk_upsert = MagicMock(return_value=1)
    writer = Writer(bulk_upsert)

    assert writer.save_valuation(_sample_metric("000001.SZ", date(2026, 3, 10))) == 1
    bulk_upsert.assert_called_once()

    bulk_upsert.reset_mock()
    invalid = _sample_metric("000001.SZ", date(2026, 3, 10))
    invalid = ValuationMetrics(
        stock_code=invalid.stock_code,
        trade_date=invalid.trade_date,
        pe=invalid.pe,
        pb=invalid.pb,
        ps=invalid.ps,
        total_mv=invalid.total_mv,
        circ_mv=invalid.circ_mv,
        dividend_yield=invalid.dividend_yield,
        source_provider=invalid.source_provider,
        is_valid=False,
    )
    assert writer.save_valuation(invalid) == 0
    bulk_upsert.assert_not_called()
