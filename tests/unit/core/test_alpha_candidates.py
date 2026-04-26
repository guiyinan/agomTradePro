from core.integration.alpha_candidates import get_alpha_candidate_repository


class _FakeAlphaCandidateRepository:
    def __init__(self):
        self.calls = []

    def update_last_decision_request_id(self, candidate_id, request_id):
        self.calls.append(("request", candidate_id, request_id))
        return True

    def update_status_to_rejected(self, candidate_id):
        self.calls.append(("rejected", candidate_id))
        return True

    def update_status_to_executed(self, candidate_id):
        self.calls.append(("executed", candidate_id))
        return True

    def update_execution_status_to_failed(self, candidate_id):
        self.calls.append(("failed", candidate_id))
        return True


def test_get_alpha_candidate_repository_uses_alpha_trigger_repository(monkeypatch):
    fake_repo = _FakeAlphaCandidateRepository()
    monkeypatch.setattr(
        "core.integration.alpha_candidates.AlphaCandidateRepository",
        lambda: fake_repo,
    )

    bridge = get_alpha_candidate_repository()

    assert bridge.update_last_decision_request_id("candidate-1", "request-1")
    assert bridge.update_status_to_rejected("candidate-1")
    assert bridge.update_status_to_executed("candidate-1")
    assert bridge.update_execution_status_to_failed("candidate-1")
    assert fake_repo.calls == [
        ("request", "candidate-1", "request-1"),
        ("rejected", "candidate-1"),
        ("executed", "candidate-1"),
        ("failed", "candidate-1"),
    ]
