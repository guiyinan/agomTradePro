from datetime import UTC, datetime

from core.integration.decision_execution_links import (
    DecisionExecutionLinkRecorder,
    DecisionManualTradeExecutionMatcher,
)


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


def test_manual_trade_matcher_records_manual_only_when_no_recommendation():
    repo = FakeRecommendationRepo()
    matcher = DecisionManualTradeExecutionMatcher(recommendation_repo=repo)
    traded_at = datetime.now(UTC)

    result = matcher.record_imported_execution(
        account_id="3",
        transaction_id=12,
        security_code="000003.SZ",
        actual_action="buy",
        traded_at=traded_at,
    )

    assert result["recommendation_id"] == ""
    assert result["match_method"] == "manual_only"
    assert result["match_confidence"] == 0.0
    assert repo.match_args["side"] == "BUY"
    assert repo.actions == []


def test_manual_trade_matcher_marks_matched_recommendation_adopted():
    repo = FakeRecommendationRepo()
    repo.match = {"recommendation_id": "urec_manual", "match_confidence": 0.9}
    matcher = DecisionManualTradeExecutionMatcher(recommendation_repo=repo)
    traded_at = datetime.now(UTC)

    result = matcher.record_imported_execution(
        account_id="4",
        transaction_id=13,
        security_code="600004.SH",
        actual_action="sell",
        traded_at=traded_at,
    )

    assert result["recommendation_id"] == "urec_manual"
    assert result["match_method"] == "auto"
    assert result["match_confidence"] == 0.9
    assert repo.match_args["side"] == "SELL"
    assert repo.actions[0]["user_action"] == "ADOPTED"
