"""Decision execution use case tests."""

from types import SimpleNamespace
from unittest.mock import Mock

from apps.decision_rhythm.application.use_cases import (
    ExecuteDecisionRequest,
    ExecuteDecisionUseCase,
)
from apps.decision_rhythm.domain.entities import ExecutionTarget


def _pending_decision_request():
    return SimpleNamespace(
        request_id="req_001",
        execution_status=SimpleNamespace(value="PENDING"),
        candidate_id=None,
        asset_code="000001.SZ",
    )


def _execution_use_case():
    request_repo = Mock()
    request_repo.get_by_id.return_value = _pending_decision_request()
    return (
        ExecuteDecisionUseCase(
            request_repo=request_repo,
            candidate_repo=Mock(),
            simulated_account_repo=Mock(),
            position_repo=Mock(),
            trade_repo=Mock(),
        ),
        request_repo,
    )


def test_resolve_simulated_buy_signal_id_prefers_request_signal_id():
    use_case = ExecuteDecisionUseCase(
        request_repo=Mock(),
        candidate_repo=Mock(),
        signal_repo=Mock(),
    )
    request = ExecuteDecisionRequest(
        request_id="req_001",
        target=ExecutionTarget.SIMULATED,
        asset_code="000001.SZ",
        action="buy",
        signal_id=88,
    )

    signal_id = use_case._resolve_simulated_buy_signal_id(
        request,
        SimpleNamespace(candidate_id=None),
    )

    assert signal_id == 88


def test_resolve_simulated_buy_signal_id_falls_back_to_latest_approved_signal():
    signal_repo = Mock()
    signal_repo.get_valid_signal_summaries.return_value = [
        {"id": 101, "asset_code": "000001.SZ", "logic_desc": "approved"},
    ]
    use_case = ExecuteDecisionUseCase(
        request_repo=Mock(),
        candidate_repo=Mock(),
        signal_repo=signal_repo,
    )
    request = ExecuteDecisionRequest(
        request_id="req_001",
        target=ExecutionTarget.SIMULATED,
        asset_code="000001.SZ",
        action="buy",
    )

    signal_id = use_case._resolve_simulated_buy_signal_id(
        request,
        SimpleNamespace(candidate_id=None),
    )

    assert signal_id == 101
    signal_repo.get_valid_signal_summaries.assert_called_once_with(["000001.SZ"])


def test_execute_simulated_rejects_missing_required_fields():
    use_case, request_repo = _execution_use_case()

    response = use_case.execute(
        ExecuteDecisionRequest(
            request_id="req_001",
            target=ExecutionTarget.SIMULATED,
        )
    )

    assert response.success is False
    assert response.error is not None
    assert "sim_account_id" in response.error
    request_repo.update_execution_status.assert_called_once()


def test_execute_simulated_rejects_unknown_action():
    use_case, _ = _execution_use_case()

    response = use_case.execute(
        ExecuteDecisionRequest(
            request_id="req_001",
            target=ExecutionTarget.SIMULATED,
            sim_account_id=1,
            asset_code="000001.SZ",
            action="hold",
            quantity=100,
            price=10.0,
        )
    )

    assert response.success is False
    assert response.error is not None
    assert "action" in response.error


def test_execute_account_rejects_missing_position_fields():
    use_case, _ = _execution_use_case()

    response = use_case.execute(
        ExecuteDecisionRequest(
            request_id="req_001",
            target=ExecutionTarget.ACCOUNT,
            portfolio_id=1,
        )
    )

    assert response.success is False
    assert response.error is not None
    assert "asset_code" in response.error
