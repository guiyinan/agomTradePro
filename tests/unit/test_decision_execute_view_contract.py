"""Decision execution HTTP contract for the owner-scoped settlement caller."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.decision_rhythm.application.use_cases import ExecuteDecisionResponse
from apps.decision_rhythm.interface import workflow_api_views


def _request() -> object:
    return APIRequestFactory().post(
        "/api/decision-rhythm/requests/req_001/execute/",
        {
            "target": "SIMULATED",
            "sim_account_id": 5,
            "asset_code": "000001.SZ",
            "action": "buy",
            "quantity": 100,
            "price": 12.35,
        },
        format="json",
    )


def test_simulated_decision_execute_requires_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = Mock()
    monkeypatch.setattr(workflow_api_views, "build_execute_decision_dependencies", builder)

    response = workflow_api_views.ExecuteDecisionRequestView.as_view()(
        _request(), request_id="req_001"
    )
    response.render()

    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")
    builder.assert_not_called()


@pytest.mark.parametrize("result_unknown, status_code", [(False, 400), (True, 409)])
def test_simulated_decision_execute_passes_actor_and_maps_result_status(
    monkeypatch: pytest.MonkeyPatch, result_unknown: bool, status_code: int
) -> None:
    request_repo = Mock()
    request_repo.get_by_id.return_value = SimpleNamespace(asset_code="000001.SZ")
    use_case = Mock()
    use_case.execute.return_value = ExecuteDecisionResponse(
        success=False, error="execution blocked", result_unknown=result_unknown
    )
    builder = Mock(return_value=SimpleNamespace(request_repo=request_repo, use_case=use_case))
    monkeypatch.setattr(workflow_api_views, "build_execute_decision_dependencies", builder)
    request = _request()
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True, pk=23))

    response = workflow_api_views.ExecuteDecisionRequestView.as_view()(
        request, request_id="req_001"
    )
    response.render()

    assert response.status_code == status_code
    assert response["Content-Type"].startswith("application/json")
    assert response.data["success"] is False
    execution_request = use_case.execute.call_args.args[0]
    assert execution_request.user_id == 23
    assert execution_request.sim_account_id == 5


def test_simulated_decision_rejects_price_beyond_ledger_precision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_repo = Mock()
    request_repo.get_by_id.return_value = SimpleNamespace(asset_code="000001.SZ")
    use_case = Mock()
    monkeypatch.setattr(
        workflow_api_views,
        "build_execute_decision_dependencies",
        Mock(return_value=SimpleNamespace(request_repo=request_repo, use_case=use_case)),
    )
    request = APIRequestFactory().post(
        "/api/decision-rhythm/requests/req_001/execute/",
        {
            "target": "SIMULATED",
            "sim_account_id": 5,
            "asset_code": "000001.SZ",
            "action": "buy",
            "quantity": 100,
            "price": "12.34567",
        },
        format="json",
    )
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True, pk=23))

    response = workflow_api_views.ExecuteDecisionRequestView.as_view()(
        request, request_id="req_001"
    )
    response.render()

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    use_case.execute.assert_not_called()
