from apps.events.infrastructure.repositories import (
    get_alpha_candidate_repository,
    get_decision_request_repository,
)


class _FakeDecisionRequestRepository:
    def __init__(self):
        self.calls = []

    def get_by_id(self, request_id):
        self.calls.append(("get_by_id", request_id))
        return {"request_id": request_id}


class _FakeAlphaCandidateRepository:
    def __init__(self):
        self.calls = []

    def update_status_to_executed(self, candidate_id):
        self.calls.append(("executed", candidate_id))
        return True


def test_get_decision_request_repository_uses_decision_rhythm_repository(monkeypatch):
    fake_repo = _FakeDecisionRequestRepository()
    monkeypatch.setattr(
        "apps.events.infrastructure.repositories._get_decision_request_repository",
        lambda: fake_repo,
    )

    repo = get_decision_request_repository()

    assert repo.get_by_id("request-1") == {"request_id": "request-1"}
    assert fake_repo.calls == [("get_by_id", "request-1")]


def test_get_alpha_candidate_repository_uses_alpha_trigger_repository(monkeypatch):
    fake_repo = _FakeAlphaCandidateRepository()
    monkeypatch.setattr(
        "apps.events.infrastructure.repositories._get_alpha_candidate_repository",
        lambda: fake_repo,
    )

    repo = get_alpha_candidate_repository()

    assert repo.update_status_to_executed("candidate-1") is True
    assert fake_repo.calls == [("executed", "candidate-1")]
