import inspect
from unittest.mock import MagicMock, patch

import pytest

from apps.equity.application import tasks as compatibility_tasks
from apps.equity.application import tasks_valuation_sync as canonical_tasks
from apps.equity.application.tasks_valuation_sync import (
    sync_equity_valuation_task,
    sync_financial_data_task,
    sync_validate_scan_equity_valuation_task,
)


def test_registered_task_bodies_use_canonical_module_globals() -> None:
    """Registry proxies must execute the task functions from the canonical module."""

    tasks = (
        canonical_tasks.sync_equity_valuation_task,
        canonical_tasks.validate_equity_valuation_quality_task,
        canonical_tasks.sync_validate_scan_equity_valuation_task,
        canonical_tasks.sync_financial_data_task,
    )

    for task in tasks:
        assert inspect.unwrap(task.run).__globals__ is vars(canonical_tasks)


def test_legacy_equity_task_aliases_delegate_exactly_to_canonical_tasks(monkeypatch) -> None:
    """The four legacy Celery names are wrappers, not independent business tasks."""

    assert (
        compatibility_tasks.sync_equity_valuation_task is canonical_tasks.sync_equity_valuation_task
    )
    assert (
        compatibility_tasks.validate_equity_valuation_quality_task
        is canonical_tasks.validate_equity_valuation_quality_task
    )
    assert (
        compatibility_tasks.sync_validate_scan_equity_valuation_task
        is canonical_tasks.sync_validate_scan_equity_valuation_task
    )
    assert compatibility_tasks.sync_financial_data_task is canonical_tasks.sync_financial_data_task

    calls: list[tuple[str, dict[str, object]]] = []

    def delegate(name: str):
        def run(**kwargs):
            calls.append((name, kwargs))
            return {"canonical": name}

        return run

    monkeypatch.setattr(canonical_tasks.sync_equity_valuation_task, "run", delegate("sync"))
    monkeypatch.setattr(
        canonical_tasks.validate_equity_valuation_quality_task,
        "run",
        delegate("validate"),
    )
    monkeypatch.setattr(
        canonical_tasks.sync_validate_scan_equity_valuation_task,
        "run",
        delegate("workflow"),
    )
    monkeypatch.setattr(canonical_tasks.sync_financial_data_task, "run", delegate("financial"))

    assert compatibility_tasks.sync_equity_valuation_task_alias.run(
        days_back=2,
        primary_source="p",
        fallback_source="f",
    ) == {"canonical": "sync"}
    assert compatibility_tasks.validate_equity_valuation_quality_task_alias.run(
        primary_source="p"
    ) == {"canonical": "validate"}
    assert compatibility_tasks.sync_validate_scan_equity_valuation_task_alias.run(
        days_back=2,
        primary_source="p",
        fallback_source="f",
        universe="active",
        lookback_days=9,
    ) == {"canonical": "workflow"}
    assert compatibility_tasks.sync_financial_data_task_alias.run(
        source="p",
        periods=6,
        stock_codes=["000001.SZ"],
    ) == {"canonical": "financial"}
    assert calls == [
        ("sync", {"days_back": 2, "primary_source": "p", "fallback_source": "f"}),
        ("validate", {"primary_source": "p"}),
        (
            "workflow",
            {
                "days_back": 2,
                "primary_source": "p",
                "fallback_source": "f",
                "universe": "active",
                "lookback_days": 9,
            },
        ),
        ("financial", {"source": "p", "periods": 6, "stock_codes": ["000001.SZ"]}),
    ]


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
        assert result["outcome"] == "blocked"
        assert result["stage"] == "gate_blocked"
        assert result["scan_skipped"] is True
        ScanUC.return_value.execute.assert_not_called()


def test_sync_validate_scan_reuses_one_frozen_repository_scope() -> None:
    frozen_scope = object()
    with (
        patch("apps.equity.application.tasks_valuation_sync.get_equity_stock_repository"),
        patch(
            "apps.equity.application.tasks_valuation_sync.get_equity_valuation_data_quality_repository"
        ),
        patch("apps.equity.application.tasks_valuation_sync.SyncEquityValuationUseCase") as SyncUC,
        patch(
            "apps.equity.application.tasks_valuation_sync.ValidateEquityValuationQualityUseCase"
        ) as ValidateUC,
        patch("apps.equity.application.tasks_valuation_sync.ScanValuationRepairsUseCase") as ScanUC,
    ):
        SyncUC.return_value.execute.return_value = MagicMock(
            success=True,
            data={"outcome": "success", "synced_count": 10},
            _frozen_scope=frozen_scope,
        )
        ValidateUC.return_value.execute.return_value = MagicMock(
            success=True,
            data={"is_gate_passed": False, "gate_reason": "coverage<0.95"},
        )

        result = sync_validate_scan_equity_valuation_task(days_back=1)

    assert SyncUC.return_value.execute.call_count == 1
    assert ValidateUC.return_value.execute.call_args.kwargs["_frozen_scope"] is frozen_scope
    assert result["outcome"] == "blocked"
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
        assert result["outcome"] == "success"
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
        assert result["outcome"] == "failed"
        assert result["stage"] == "sync"
        assert result["phase"] == "sync"
        assert result["error"] == "估值同步未写入任何记录"
        validate_use_case.assert_not_called()
        scan_use_case.assert_not_called()


def test_sync_task_preserves_partial_outcome_and_nullable_stored_count() -> None:
    from apps.task_monitor.application.dtos import project_task_business_result
    from apps.task_monitor.application.tasks import _bounded_business_result

    partial_data = {
        "outcome": "partial",
        "requested_stock_count": 2,
        "succeeded_stock_count": 1,
        "failed_stock_count": 1,
        "confirmed_stored_record_count": 1,
        "stored_record_count": None,
        "counts_unavailable": True,
    }
    with patch(
        "apps.equity.application.tasks_valuation_sync.SyncEquityValuationUseCase"
    ) as sync_use_case:
        sync_use_case.return_value.execute.return_value = MagicMock(
            success=False,
            data=partial_data,
            error="估值同步部分失败",
        )

        result = sync_equity_valuation_task(days_back=1)

    assert result["success"] is True
    assert result["outcome"] == "partial"
    assert result["requested_stock_count"] == 2
    assert result["stored_record_count"] is None
    assert result["counts_unavailable"] is True
    projection = project_task_business_result(_bounded_business_result(result))
    assert projection.outcome == "partial"
    assert projection.requested == 2
    assert projection.succeeded == 1
    assert projection.failed == 1
    assert projection.stored is None
    assert projection.counts_unavailable is True
    assert projection.count_unit == "valuation_asset"
    assert projection.stored_count_unit == "canonical_fact_processed"
    assert projection.phase_results is not None
    assert projection.phase_results[0].phase == "sync"


def test_sync_validate_scan_stops_and_preserves_partial_sync_before_gate() -> None:
    partial_data = {
        "outcome": "partial",
        "requested_stock_count": 2,
        "succeeded_stock_count": 1,
        "failed_stock_count": 1,
        "confirmed_stored_record_count": 1,
        "stored_record_count": None,
        "counts_unavailable": True,
    }
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
            success=False,
            data=partial_data,
            error="估值同步部分失败",
        )

        result = sync_validate_scan_equity_valuation_task(days_back=1)

    assert result["success"] is True
    assert result["outcome"] == "partial"
    assert result["stage"] == "sync"
    assert result["sync"]["stored_record_count"] is None
    assert result["scan_skipped"] is True
    assert result["requested"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["stored"] is None
    assert result["phase"] == "sync"
    assert result["phase_results"][0]["phase"] == "sync"
    validate_use_case.assert_not_called()
    scan_use_case.assert_not_called()


def test_scan_failure_count_cannot_be_reported_as_success() -> None:
    with (
        patch("apps.equity.application.tasks_valuation_sync.SyncEquityValuationUseCase") as SyncUC,
        patch(
            "apps.equity.application.tasks_valuation_sync.ValidateEquityValuationQualityUseCase"
        ) as ValidateUC,
        patch("apps.equity.application.tasks_valuation_sync.ScanValuationRepairsUseCase") as ScanUC,
    ):
        SyncUC.return_value.execute.return_value = MagicMock(
            success=True,
            data={"outcome": "success", "stored_record_count": 10, "synced_count": 10},
        )
        ValidateUC.return_value.execute.return_value = MagicMock(
            success=True,
            data={"is_gate_passed": True},
        )
        ScanUC.return_value.execute.return_value = MagicMock(
            success=True,
            universe="all_active",
            as_of_date=MagicMock(isoformat=lambda: "2026-03-10"),
            scanned_count=3,
            saved_count=2,
            failed_count=1,
            phase_counts={},
            error=None,
        )

        result = sync_validate_scan_equity_valuation_task(days_back=1)

    assert result["success"] is True
    assert result["outcome"] == "partial"
    assert result["scan"]["scanned_count"] == 3
    assert result["scan"]["failed_count"] == 1


def test_sync_valuation_task_rejects_boolean_days_before_repository_access():
    with patch(
        "apps.equity.application.tasks_valuation_sync.get_equity_stock_repository"
    ) as stock_repository:
        result = sync_equity_valuation_task(days_back=True)

    assert result == {
        "success": False,
        "outcome": "failed",
        "error": "days_back 必须是整数",
        "stage": "input",
        "phase": "input",
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
    assert result["outcome"] == "failed"
    assert result["stage"] == "sync"
    assert result["sync"] == {"requested_count": 2, "synced_count": 0}


@pytest.mark.parametrize(
    ("stock_codes", "requested_stock_count"),
    [(None, 0), (["001979.SZ", "600000.SH"], 2)],
)
def test_sync_financial_data_task_blocks_scopes_without_governed_budget(
    stock_codes: list[str] | None,
    requested_stock_count: int,
    monkeypatch,
):
    """Legacy full-universe and explicit scopes both stop before external access."""

    def fail_if_called(*args, **kwargs):
        pytest.fail("legacy financial sync must block before repository or provider access")

    with patch(
        "apps.equity.application.tasks_valuation_sync.get_equity_stock_repository"
    ) as stock_repo_cls:
        monkeypatch.setattr(
            canonical_tasks, "get_active_provider_id_by_source", fail_if_called, raising=False
        )
        monkeypatch.setattr(
            canonical_tasks, "make_sync_financial_use_case", fail_if_called, raising=False
        )
        result = sync_financial_data_task(stock_codes=stock_codes)

    assert result["success"] is False
    assert result["outcome"] == "blocked"
    assert result["stage"] == "capacity"
    assert result["error_code"] == "FINANCIAL_CAPACITY_RECEIPT_REQUIRED"
    assert result["requested_stock_count"] == requested_stock_count
    assert result["stored_record_count"] == 0
    assert result["must_not_use_for_decision"] is True
    stock_repo_cls.assert_not_called()


def test_sync_financial_data_task_rejects_invalid_periods_before_repository_access():
    with patch(
        "apps.equity.application.tasks_valuation_sync.get_equity_stock_repository"
    ) as stock_repository:
        result = sync_financial_data_task(periods=0)

    assert result == {
        "success": False,
        "outcome": "failed",
        "error": "periods 必须在 1..40 之间",
        "stage": "input",
    }
    stock_repository.assert_not_called()


def test_sync_financial_data_task_rejects_malformed_stock_code_before_provider_access(
    monkeypatch,
):
    def fail_if_called(*args, **kwargs):
        pytest.fail("malformed financial scope must be rejected before provider access")

    monkeypatch.setattr(
        canonical_tasks, "get_active_provider_id_by_source", fail_if_called, raising=False
    )
    monkeypatch.setattr(
        canonical_tasks, "make_sync_financial_use_case", fail_if_called, raising=False
    )
    with patch(
        "apps.equity.application.tasks_valuation_sync.get_equity_stock_repository"
    ) as stock_repository:
        result = sync_financial_data_task(stock_codes=["000001.SZ;DROP"])

    assert result["success"] is False
    assert result["outcome"] == "failed"
    assert result["stage"] == "input"
    stock_repository.assert_not_called()


def test_validate_valuation_task_rejects_invalid_source_before_repository_access():
    with patch(
        "apps.equity.application.tasks_valuation_sync.get_equity_stock_repository"
    ) as stock_repository:
        from apps.equity.application.tasks_valuation_sync import (
            validate_equity_valuation_quality_task,
        )

        result = validate_equity_valuation_quality_task(primary_source="")

    assert result["success"] is False
    assert result["outcome"] == "failed"
    assert result["stage"] == "input"
    stock_repository.assert_not_called()
