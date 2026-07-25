"""Authorization and disclosure invariants for operation-log use cases."""

from unittest.mock import Mock

import pytest

from apps.audit.application import interface_services
from apps.audit.application.operation_log_use_cases import (
    ExportOperationLogsRequest,
    ExportOperationLogsUseCase,
    GetOperationLogDetailRequest,
    GetOperationLogDetailUseCase,
    GetOperationStatsRequest,
    GetOperationStatsUseCase,
    QueryOperationLogsRequest,
    QueryOperationLogsUseCase,
)


def test_anonymous_non_admin_query_fails_closed() -> None:
    repository = Mock()

    response = QueryOperationLogsUseCase(repository).execute(
        QueryOperationLogsRequest(
            is_admin=False,
            current_user_id=None,
        )
    )

    assert response.success is False
    assert response.error == "需要有效用户身份"
    repository.query_operation_logs.assert_not_called()


def test_anonymous_non_admin_detail_fails_before_lookup() -> None:
    repository = Mock()

    response = GetOperationLogDetailUseCase(repository).execute(
        GetOperationLogDetailRequest(
            log_id="log-1",
            is_admin=False,
            current_user_id=None,
        )
    )

    assert response.success is False
    assert response.error == "需要有效用户身份"
    repository.get_operation_log_by_id.assert_not_called()


def test_export_requires_explicit_admin_context() -> None:
    repository = Mock()

    response = ExportOperationLogsUseCase(repository).execute(ExportOperationLogsRequest())

    assert response.success is False
    assert response.error == "仅管理员可导出操作日志"
    repository.query_operation_logs.assert_not_called()


def test_stats_require_explicit_admin_context() -> None:
    repository = Mock()

    response = GetOperationStatsUseCase(repository).execute(GetOperationStatsRequest())

    assert response.success is False
    assert response.error == "仅管理员可查看操作统计"
    repository.get_operation_stats.assert_not_called()


def test_query_rejects_untrusted_ordering_before_repository() -> None:
    repository = Mock()

    response = QueryOperationLogsUseCase(repository).execute(
        QueryOperationLogsRequest(
            is_admin=True,
            ordering="request_params",
        )
    )

    assert response.success is False
    assert response.error == "不支持的排序字段"
    repository.query_operation_logs.assert_not_called()


def test_decision_trace_list_without_identity_fails_before_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_factory = Mock()
    monkeypatch.setattr(
        interface_services,
        "get_audit_repository",
        repository_factory,
    )

    result = interface_services.list_decision_traces_payload(
        current_user_id=None,
        is_admin=False,
        mcp_client_id=None,
        page=1,
        page_size=20,
    )

    assert result == ([], 0)
    repository_factory.assert_not_called()


def test_decision_trace_detail_without_identity_fails_before_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_factory = Mock()
    monkeypatch.setattr(
        interface_services,
        "get_audit_repository",
        repository_factory,
    )

    result = interface_services.get_decision_trace_payload(
        request_id="req-1",
        mcp_client_id=None,
        current_user_id=None,
        is_admin=False,
    )

    assert result is None
    repository_factory.assert_not_called()
