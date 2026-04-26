from core.integration.decision_requests import get_decision_request_repository


class _FakeDecisionRequestRepository:
    def __init__(self):
        self.calls = []

    def update_execution_status_to_executed(self, request_id, execution_ref):
        self.calls.append(("executed", request_id, execution_ref))
        return True

    def update_execution_status_to_failed(self, request_id):
        self.calls.append(("failed", request_id))
        return True

    def get_by_id(self, request_id):
        self.calls.append(("get_by_id", request_id))
        return {"request_id": request_id}


def test_get_decision_request_repository_uses_decision_rhythm_repository(monkeypatch):
    fake_repo = _FakeDecisionRequestRepository()
    monkeypatch.setattr(
        "core.integration.decision_requests.DecisionRequestRepository",
        lambda: fake_repo,
    )

    bridge = get_decision_request_repository()

    assert bridge.update_execution_status_to_executed(
        "request-1",
        {"trade_id": "trade-1"},
    )
    assert bridge.update_execution_status_to_failed("request-1")
    assert bridge.get_by_id("request-1") == {"request_id": "request-1"}
    assert fake_repo.calls == [
        ("executed", "request-1", {"trade_id": "trade-1"}),
        ("failed", "request-1"),
        ("get_by_id", "request-1"),
    ]
