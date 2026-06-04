from datetime import UTC, datetime

from core.integration.decision_execution_links import DecisionExecutionLinkRecorder


class FakeRecommendationRepo:
    def __init__(self):
        self.actions = []
        self.links = []
        self.match = None

    def find_execution_match(self, **kwargs):
        self.match_args = kwargs
        return self.match

    def update_user_action(self, **kwargs):
        self.actions.append(kwargs)
        return {"ok": True}

    def record_execution_link(self, **kwargs):
        self.links.append(kwargs)
        return kwargs


def test_recorder_links_exact_recommendation_id():
    repo = FakeRecommendationRepo()
    recorder = DecisionExecutionLinkRecorder(recommendation_repo=repo)
    executed_at = datetime.now(UTC)

    result = recorder.record_execution(
        recommendation_id="urec_001",
        transaction_id=10,
        account_id=1,
        security_code="000001.SZ",
        actual_action="sell",
        executed_at=executed_at,
        notes="auto exit",
    )

    assert result["recommendation_id"] == "urec_001"
    assert repo.actions[0]["user_action"] == "ADOPTED"
    assert repo.links[0]["transaction_id"] == 10
    assert repo.links[0]["match_confidence"] == 1.0


def test_recorder_matches_recent_recommendation_when_requested():
    repo = FakeRecommendationRepo()
    repo.match = {"recommendation_id": "urec_match", "match_confidence": 0.85}
    recorder = DecisionExecutionLinkRecorder(recommendation_repo=repo)
    executed_at = datetime.now(UTC)

    result = recorder.record_execution(
        recommendation_id=None,
        transaction_id=11,
        account_id=2,
        security_code="600000.SH",
        actual_action="buy",
        executed_at=executed_at,
        match_if_missing=True,
    )

    assert result["recommendation_id"] == "urec_match"
    assert repo.match_args["side"] == "BUY"
    assert repo.match_args["traded_at"] == executed_at
    assert repo.links[0]["match_confidence"] == 0.85
