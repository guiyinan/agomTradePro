import logging
from datetime import UTC, datetime

import pytest

from core.integration.decision_execution_links import (
    DecisionExecutionLinkRecorder,
    DecisionManualTradeExecutionMatcher,
)

pytestmark = pytest.mark.django_db


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


def test_match_confidence_preserves_zero_instead_of_fabricating_default():
    repo = FakeRecommendationRepo()
    repo.match = {"recommendation_id": "urec_zero", "match_confidence": 0.0}
    recorder = DecisionExecutionLinkRecorder(recommendation_repo=repo)

    result = recorder.record_execution(
        recommendation_id=None,
        transaction_id=14,
        account_id=5,
        security_code="000005.sz",
        actual_action="buy",
        executed_at=datetime.now(UTC),
        match_if_missing=True,
    )

    assert result is not None
    assert result["match_confidence"] == 0.0
    assert repo.links[0]["security_code"] == "000005.SZ"


@pytest.mark.parametrize("invalid_confidence", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_recorder_rejects_invalid_match_confidence(invalid_confidence):
    repo = FakeRecommendationRepo()
    repo.match = {
        "recommendation_id": "urec_invalid",
        "match_confidence": invalid_confidence,
    }
    recorder = DecisionExecutionLinkRecorder(recommendation_repo=repo)

    result = recorder.record_execution(
        recommendation_id=None,
        transaction_id=15,
        account_id=6,
        security_code="000006.SZ",
        actual_action="buy",
        executed_at=datetime.now(UTC),
        match_if_missing=True,
    )

    assert result is None
    assert repo.actions == []
    assert repo.links == []


def test_recorder_rejects_naive_execution_time_before_repository_access():
    repo = FakeRecommendationRepo()
    recorder = DecisionExecutionLinkRecorder(recommendation_repo=repo)

    result = recorder.record_execution(
        recommendation_id="urec_naive",
        transaction_id=16,
        account_id=7,
        security_code="000007.SZ",
        actual_action="sell",
        executed_at=datetime(2026, 7, 27, 10, 0),
    )

    assert result is None
    assert repo.actions == []
    assert repo.links == []


def test_recorder_does_not_link_missing_recommendation():
    class MissingRecommendationRepo(FakeRecommendationRepo):
        def update_user_action(self, **kwargs):
            self.actions.append(kwargs)
            return None

    repo = MissingRecommendationRepo()
    recorder = DecisionExecutionLinkRecorder(recommendation_repo=repo)

    result = recorder.record_execution(
        recommendation_id="missing",
        transaction_id=17,
        account_id=8,
        security_code="000008.SZ",
        actual_action="buy",
        executed_at=datetime.now(UTC),
    )

    assert result is None
    assert repo.links == []


def test_recorder_redacts_repository_failure(caplog):
    class FailingRecommendationRepo(FakeRecommendationRepo):
        def record_execution_link(self, **kwargs):
            raise RuntimeError("postgres://user:secret@internal-host")

    repo = FailingRecommendationRepo()
    recorder = DecisionExecutionLinkRecorder(recommendation_repo=repo)

    with caplog.at_level(
        logging.WARNING,
        logger="core.integration.decision_execution_links",
    ):
        result = recorder.record_execution(
            recommendation_id="urec_failure",
            transaction_id=18,
            account_id=9,
            security_code="000009.SZ",
            actual_action="buy",
            executed_at=datetime.now(UTC),
        )

    assert result is None
    assert "RuntimeError" in caplog.text
    assert "postgres://user:secret@internal-host" not in caplog.text
