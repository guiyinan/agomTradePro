"""Decision execution use case tests."""

from types import SimpleNamespace
from unittest.mock import Mock

from apps.decision_rhythm.application.use_cases import (
    ExecuteDecisionRequest,
    ExecuteDecisionUseCase,
)
from apps.decision_rhythm.domain.entities import ExecutionTarget


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
