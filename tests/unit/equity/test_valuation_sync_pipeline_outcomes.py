"""Cross-stage valuation outcomes survive the real Task Monitor projection."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.equity.application import tasks_valuation_sync as tasks
from apps.equity.application.use_cases_valuation_repair import ScanValuationRepairsResponse
from apps.equity.application.use_cases_valuation_sync import (
    SyncEquityValuationRequest,
    SyncEquityValuationResponse,
    SyncEquityValuationUseCase,
    ValidateEquityValuationQualityResponse,
    _freeze_stock_scope,
)
from apps.task_monitor.application.dtos import project_task_business_result
from apps.task_monitor.application.tasks import _bounded_business_result


def _sync_response() -> SyncEquityValuationResponse:
    """Build an exact internal response for a synthetic completed two-asset sync."""
    scope = _freeze_stock_scope(["600000.SH", "600519.SH"], maximum_count=5000)
    return SyncEquityValuationResponse(
        success=True,
        data={
            "outcome": "success",
            "requested_stock_count": 2,
            "succeeded_stock_count": 2,
            "failed_stock_count": 0,
            "synced_count": 2,
            "stored_record_count": 2,
            "counts_unavailable": False,
            "scope_count": 2,
            "scope_sha256": scope.identity,
        },
        _frozen_scope=scope,
    )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sync: SyncEquityValuationResponse | None = None,
    quality: ValidateEquityValuationQualityResponse | None = None,
    scan: ScanValuationRepairsResponse | None = None,
) -> dict[str, MagicMock]:
    """Inject use-case responses while retaining real task and monitor code."""
    executions = {
        "sync": MagicMock(return_value=sync if sync is not None else _sync_response()),
        "validate": MagicMock(
            return_value=(
                quality
                if quality is not None
                else ValidateEquityValuationQualityResponse(
                    success=True,
                    data={"expected_stock_count": 2, "is_gate_passed": True},
                )
            )
        ),
        "scan": MagicMock(return_value=scan),
    }
    for name in (
        "get_equity_stock_repository",
        "get_equity_valuation_data_quality_repository",
        "get_equity_valuation_repair_repository",
        "get_equity_stock_pool_repository",
    ):
        monkeypatch.setattr(tasks, name, lambda: object())
    for factory, phase in (
        ("_make_sync_use_case", "sync"),
        ("_make_validate_use_case", "validate"),
        ("_make_scan_use_case", "scan"),
    ):
        use_case = SimpleNamespace(execute=executions[phase])
        monkeypatch.setattr(tasks, factory, lambda *args, result=use_case: result)
    return executions


@pytest.mark.parametrize(
    "response",
    [
        ValidateEquityValuationQualityResponse(success=False, error="quality unavailable"),
        ValidateEquityValuationQualityResponse(success=True, data=None),
    ],
)
def test_pipeline_quality_failure_preserves_completed_sync_counts(
    monkeypatch: pytest.MonkeyPatch, response: ValidateEquityValuationQualityResponse
) -> None:
    executions = _install(monkeypatch, quality=response)
    result = tasks.sync_validate_scan_equity_valuation_task.run()
    projection = project_task_business_result(_bounded_business_result(result))

    assert projection.outcome == "failed"
    assert projection.phase == "validate"
    assert (projection.requested, projection.succeeded, projection.failed, projection.stored) == (
        2,
        2,
        0,
        2,
    )
    assert projection.stored_count_unit == "canonical_fact_processed"
    assert len(projection.phase_results) == 2
    quality_phase = projection.phase_results[1]
    assert quality_phase.requested == 1
    assert quality_phase.succeeded == 0
    assert quality_phase.failed == 1
    assert quality_phase.count_unit == "quality_operation"
    assert quality_phase.stored is None
    assert quality_phase.stored_count_unit == "quality_snapshot"
    executions["scan"].assert_not_called()


@pytest.mark.parametrize("failed, saved, outcome", [(1, 1, "partial"), (2, 0, "failed")])
def test_scan_outcome_keeps_fact_and_repair_snapshot_counts_separate(
    monkeypatch: pytest.MonkeyPatch, failed: int, saved: int, outcome: str
) -> None:
    scan = ScanValuationRepairsResponse(
        success=False,
        universe="all_active",
        as_of_date=date(2026, 10, 23),
        scanned_count=2,
        saved_count=saved,
        failed_count=failed,
        phase_counts={},
        error="部分股票扫描失败",
    )
    _install(monkeypatch, scan=scan)
    result = tasks.sync_validate_scan_equity_valuation_task.run()
    projection = project_task_business_result(_bounded_business_result(result))

    assert projection.outcome == outcome
    assert projection.business_success is False
    assert projection.stored == 2
    assert projection.stored_count_unit == "canonical_fact_processed"
    assert len(projection.phase_results) == 3
    phase = projection.phase_results[2]
    assert phase.requested == 2
    assert phase.succeeded == 2 - failed
    assert phase.failed == failed
    assert phase.stored == saved
    assert phase.stored_count_unit == "repair_snapshot"


@pytest.mark.parametrize(
    "success, data",
    [(False, None), (True, None), (True, {"expected_stock_count": 2, "is_gate_passed": False})],
)
def test_standalone_quality_task_keeps_unknown_snapshot_write_count(
    monkeypatch: pytest.MonkeyPatch, success: bool, data: dict[str, object] | None
) -> None:
    response = ValidateEquityValuationQualityResponse(success=success, data=data)
    _install(monkeypatch, quality=response)
    result = tasks.validate_equity_valuation_quality_task.run()
    projection = project_task_business_result(_bounded_business_result(result))

    assert projection.outcome == ("success" if success and data is not None else "failed")
    assert projection.stored is None
    assert projection.counts_unavailable is True
    assert projection.stored_count_unit == "quality_snapshot"
    assert len(projection.phase_results) == 1
    assert projection.phase_results[0].stored is None


@pytest.mark.parametrize("workflow", [False, True])
def test_missing_sync_payload_cannot_become_zero_writes_or_success(
    monkeypatch: pytest.MonkeyPatch, workflow: bool
) -> None:
    executions = _install(monkeypatch, sync=SyncEquityValuationResponse(success=False))
    entry = (
        tasks.sync_validate_scan_equity_valuation_task
        if workflow
        else tasks.sync_equity_valuation_task
    )
    result = entry.run()
    projection = project_task_business_result(_bounded_business_result(result))

    assert projection.outcome == "failed"
    assert projection.requested is None
    assert projection.stored is None
    assert projection.counts_unavailable is True
    executions["validate"].assert_not_called()
    executions["scan"].assert_not_called()


def test_standalone_sync_success_survives_bounded_monitor_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch)
    result = tasks.sync_equity_valuation_task.run()
    projection = project_task_business_result(_bounded_business_result(result))

    assert projection.outcome == "success"
    assert projection.business_success is True
    assert (projection.requested, projection.succeeded, projection.failed, projection.stored) == (
        2,
        2,
        0,
        2,
    )
    assert projection.count_unit == "valuation_asset"
    assert projection.stored_count_unit == "canonical_fact_processed"


def test_pipeline_rejects_invalid_days_before_repository_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MagicMock()
    monkeypatch.setattr(tasks, "get_equity_stock_repository", repository)

    result = tasks.sync_validate_scan_equity_valuation_task.run(days_back=True)

    assert result["outcome"] == "failed"
    assert result["stage"] == "input"
    repository.assert_not_called()


def test_failed_asset_quality_is_not_reported_as_all_assets_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quality = ValidateEquityValuationQualityResponse(
        success=True,
        data={
            "expected_stock_count": 2,
            "synced_stock_count": 2,
            "valid_stock_count": 0,
            "is_gate_passed": False,
        },
    )
    _install(monkeypatch, quality=quality)
    result = tasks.validate_equity_valuation_quality_task.run()
    projection = project_task_business_result(_bounded_business_result(result))

    assert result["is_gate_passed"] is False
    assert projection.count_unit == "quality_operation"
    assert (projection.requested, projection.succeeded, projection.failed) == (1, 1, 0)
    assert projection.stored is None


def test_scope_digest_is_a_canonical_member_set_not_a_processing_order_identity() -> None:
    forward = _freeze_stock_scope(["600000.SH", "600519.SH"], maximum_count=5000)
    reversed_scope = _freeze_stock_scope(["600519.SH", "600000.SH"], maximum_count=5000)

    assert forward.stock_codes != reversed_scope.stock_codes
    assert forward.identity == reversed_scope.identity


def test_full_repository_universe_validates_the_invalid_tail_before_provider_access() -> None:
    repo = MagicMock()
    repo.list_active_stock_codes.return_value = [f"{index:06d}.SZ" for index in range(5000)] + [
        "invalid code"
    ]
    provider = MagicMock()
    gateway = MagicMock()
    response = SyncEquityValuationUseCase(
        repo, provider_resolver=provider, gateway_factory=gateway
    ).execute(SyncEquityValuationRequest())

    assert response.success is False
    assert response.error == "stock_code 格式无效"
    provider.assert_not_called()
    gateway.assert_not_called()
    repo.save_valuation.assert_not_called()
