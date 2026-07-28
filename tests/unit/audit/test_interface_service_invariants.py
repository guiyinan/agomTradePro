"""Application interface invariants for user-visible Audit payloads."""

from datetime import date
from unittest.mock import Mock

import pytest
from django.db import DatabaseError

from apps.audit.application import indicator_use_cases, interface_services
from apps.audit.application.attribution_use_cases import (
    GenerateAttributionReportResponse,
)
from apps.audit.application.indicator_use_cases import (
    EvaluateIndicatorPerformanceResponse,
    ValidateThresholdsRequest,
    ValidateThresholdsUseCase,
)


def test_generation_cannot_succeed_without_persisted_report_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_repository = Mock()
    use_case = Mock()
    use_case.execute.return_value = GenerateAttributionReportResponse(success=True)
    use_case_type = Mock(return_value=use_case)
    monkeypatch.setattr(interface_services, "get_audit_repository", lambda: audit_repository)
    monkeypatch.setattr(interface_services, "GenerateAttributionReportUseCase", use_case_type)
    monkeypatch.setattr(interface_services, "_get_backtest_repository", Mock())

    payload = interface_services.generate_attribution_report_payload(7)

    assert payload == {
        "success": False,
        "error": "归因报告未返回有效 ID",
        "report": None,
    }
    audit_repository.get_attribution_report.assert_not_called()


def test_generation_reports_read_after_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_repository = Mock()
    audit_repository.get_attribution_report.return_value = None
    use_case = Mock()
    use_case.execute.return_value = GenerateAttributionReportResponse(
        success=True,
        report_id=11,
    )
    monkeypatch.setattr(interface_services, "get_audit_repository", lambda: audit_repository)
    monkeypatch.setattr(
        interface_services,
        "GenerateAttributionReportUseCase",
        Mock(return_value=use_case),
    )
    monkeypatch.setattr(interface_services, "_get_backtest_repository", Mock())

    payload = interface_services.generate_attribution_report_payload(7)

    assert payload["success"] is False
    assert payload["report"] is None
    assert "无法读取" in str(payload["error"])


def test_chart_payload_loads_nested_audit_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_repository = Mock()
    audit_repository.get_attribution_report.return_value = {
        "total_pnl": 0.12,
        "regime_accuracy": 0.75,
    }
    audit_repository.get_loss_analyses.return_value = [{"id": 2}]
    audit_repository.get_experience_summaries.return_value = [{"id": 3}]
    monkeypatch.setattr(interface_services, "get_audit_repository", lambda: audit_repository)

    payload = interface_services.get_attribution_chart_data_payload(9)

    assert payload is not None
    assert payload["loss_analyses"] == [{"id": 2}]
    assert payload["experience_summaries"] == [{"id": 3}]
    audit_repository.get_loss_analyses.assert_called_once_with(9)
    audit_repository.get_experience_summaries.assert_called_once_with(9)


@pytest.mark.parametrize(
    ("low", "high"),
    [
        (float("nan"), 1.0),
        (0.0, float("inf")),
        (1.0, 1.0),
        (2.0, 1.0),
    ],
)
def test_direct_threshold_updates_reject_invalid_values_before_repository(
    monkeypatch: pytest.MonkeyPatch,
    low: float,
    high: float,
) -> None:
    repository_factory = Mock()
    monkeypatch.setattr(interface_services, "get_audit_repository", repository_factory)

    with pytest.raises(ValueError):
        interface_services.update_indicator_threshold_levels(
            indicator_code="PMI",
            level_low=low,
            level_high=high,
        )

    repository_factory.assert_not_called()


def test_unknown_report_method_filter_is_not_sent_to_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_repository = Mock()
    audit_repository.list_attribution_report_records.return_value = []
    audit_repository.get_reported_backtest_ids.return_value = set()
    audit_repository.count_attribution_reports.return_value = 0
    backtest_repository = Mock()
    backtest_repository.get_backtests_by_status.return_value = []
    monkeypatch.setattr(interface_services, "get_audit_repository", lambda: audit_repository)
    monkeypatch.setattr(
        interface_services,
        "_get_backtest_repository",
        lambda: backtest_repository,
    )

    context = interface_services.build_report_list_context("unexpected")

    assert context["method_filter"] == ""
    audit_repository.list_attribution_report_records.assert_called_once_with(
        attribution_method=None,
        limit=50,
    )


def test_public_failure_stats_exclude_raw_failure_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = Mock(
        total_count=3,
        by_component={"database": 3},
        recent_failures=[
            Mock(reason="postgresql://user:secret@internal/db"),
        ],
    )
    counter = Mock()
    counter.get_failure_stats.return_value = stats
    monkeypatch.setattr(
        interface_services,
        "get_audit_failure_counter",
        lambda: counter,
    )

    payload = interface_services.get_audit_failure_stats()

    assert payload == {
        "total_count": 3,
        "by_component": {"database": 3},
    }
    assert "secret" not in str(payload)


def test_threshold_validation_failure_redacts_exception_from_response_storage_and_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = Mock()
    repository.get_active_threshold_configs_by_codes.side_effect = DatabaseError(
        "postgresql://audit:secret@internal/validation"
    )
    repository.update_validation_summary_status.side_effect = DatabaseError(
        "redis://audit:second-secret@internal/validation"
    )

    response = ValidateThresholdsUseCase(repository).execute(
        ValidateThresholdsRequest(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            use_shadow_mode=False,
        )
    )

    assert response.success is False
    assert response.error == "threshold_validation_failed"
    repository.update_validation_summary_status.assert_called_once()
    assert (
        repository.update_validation_summary_status.call_args.kwargs["error_message"]
        == "threshold_validation_failed"
    )
    assert "secret" not in caplog.text
    assert "postgresql://" not in caplog.text
    assert "redis://" not in caplog.text


def test_failed_indicator_evaluations_are_reconciled_as_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Mock()
    repository.get_active_threshold_configs_by_codes.return_value = [
        {"indicator_code": "PMI"},
        {"indicator_code": "CPI"},
    ]

    class _FailedEvaluationUseCase:
        def __init__(self, audit_repository: object) -> None:
            self.audit_repository = audit_repository

        def execute(self, request: object) -> EvaluateIndicatorPerformanceResponse:
            return EvaluateIndicatorPerformanceResponse(
                success=False,
                error="indicator_evaluation_failed",
            )

    monkeypatch.setattr(
        indicator_use_cases,
        "EvaluateIndicatorPerformanceUseCase",
        _FailedEvaluationUseCase,
    )

    response = ValidateThresholdsUseCase(repository).execute(
        ValidateThresholdsRequest(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            use_shadow_mode=False,
        )
    )

    assert response.success is True
    assert response.validation_report is not None
    assert response.validation_report.pending_indicators == 2
    completion = repository.update_validation_summary_status.call_args.kwargs
    assert completion["status"] == "completed"
    assert completion["approved_indicators"] == 0
    assert completion["rejected_indicators"] == 0
    assert completion["pending_indicators"] == 2
