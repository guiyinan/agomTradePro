import json
import uuid
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.alpha.application.ai_filter import AlphaAISecondPassFilterService
from apps.alpha.domain.entities import AlphaResult, StockScore

User = get_user_model()


def _score(code: str, rank: int, value: float = 0.8) -> StockScore:
    return StockScore(
        code=code,
        score=value,
        rank=rank,
        factors={"momentum": value},
        source="qlib",
        confidence=0.8,
        asof_date=date(2026, 4, 30),
        intended_trade_date=date(2026, 5, 6),
    )


def _alpha_result(scores: list[StockScore]) -> AlphaResult:
    return AlphaResult(
        success=True,
        scores=scores,
        source="qlib",
        timestamp="2026-05-06",
        status="available",
        metadata={"effective_asof_date": "2026-04-30"},
    )


def _ai_response(decisions: list[dict]) -> dict:
    return {
        "status": "success",
        "content": json.dumps({"decisions": decisions}),
    }


def _decision(
    code: str,
    *,
    verdict: str = "buy",
    confidence: float = 0.7,
    ai_filter_score: float = 0.7,
) -> dict:
    return {
        "code": code,
        "verdict": verdict,
        "confidence": confidence,
        "ai_filter_score": ai_filter_score,
        "buy_reasons": ["Alpha 与估值质量共振"],
        "no_buy_reasons": [],
        "invalidation_summary": "跌出 Alpha Top 或 AI 置信度下降则失效",
    }


def _patch_context(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.alpha.application.ai_filter.get_stock_context_map",
        lambda codes: {
            code: {
                "name": code,
                "sector": "bank",
                "close": 10.0,
                "volume": 1000000,
                "pe": 6.0,
                "pb": 0.8,
                "roe": 12.0,
                "debt_ratio": 40.0,
            }
            for code in codes
        },
    )
    monkeypatch.setattr(
        "apps.alpha.application.ai_filter.get_latest_market_thermometer_snapshot_payload",
        lambda: {"score": 55.0, "band": "warm", "must_not_use_for_decision": False},
    )


def test_ai_filter_keeps_buy_watch_and_reranks(monkeypatch):
    _patch_context(monkeypatch)
    scores = [
        _score("000001.SZ", 1, 0.91),
        _score("000002.SZ", 2, 0.88),
        _score("000003.SZ", 3, 0.84),
        _score("000004.SZ", 4, 0.81),
    ]
    monkeypatch.setattr(
        "apps.alpha.application.ai_filter.generate_chat_completion",
        lambda **kwargs: _ai_response(
            [
                _decision("000001.SZ", verdict="buy", confidence=0.72, ai_filter_score=0.81),
                _decision("000002.SZ", verdict="avoid", confidence=0.92, ai_filter_score=0.20),
                _decision("000003.SZ", verdict="watch", confidence=0.60, ai_filter_score=0.66),
                _decision("000004.SZ", verdict="watch", confidence=0.59, ai_filter_score=0.65),
            ]
        ),
    )

    result = AlphaAISecondPassFilterService().apply(
        _alpha_result(scores),
        top_n=2,
        user=None,
        trade_date=date(2026, 5, 6),
    )

    assert [score.code for score in result.scores] == ["000001.SZ", "000003.SZ"]
    assert [score.rank for score in result.scores] == [1, 2]
    assert result.scores[0].factors["ai_filter_score"] == pytest.approx(0.81)
    ai_meta = result.metadata["ai_filter"]
    assert ai_meta["status"] == "applied"
    assert ai_meta["input_count"] == 4
    assert ai_meta["kept_count"] == 2
    assert ai_meta["decisions_by_code"]["000002.SZ"]["verdict"] == "avoid"


def test_ai_filter_preserves_original_top_n_when_ai_call_fails(monkeypatch):
    _patch_context(monkeypatch)
    scores = [_score("000001.SZ", 1), _score("000002.SZ", 2), _score("000003.SZ", 3)]

    def fail_completion(**kwargs):
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(
        "apps.alpha.application.ai_filter.generate_chat_completion",
        fail_completion,
    )

    result = AlphaAISecondPassFilterService().apply(
        _alpha_result(scores),
        top_n=2,
        user=None,
        trade_date=date(2026, 5, 6),
    )

    assert [score.code for score in result.scores] == ["000001.SZ", "000002.SZ"]
    ai_meta = result.metadata["ai_filter"]
    assert ai_meta["status"] == "failed"
    assert ai_meta["input_count"] == 3
    assert ai_meta["kept_count"] == 2
    assert "provider timeout" in ai_meta["failure_reason"]


def test_ai_filter_preserves_original_top_n_when_ai_json_is_invalid(monkeypatch):
    _patch_context(monkeypatch)
    scores = [_score("000001.SZ", 1), _score("000002.SZ", 2), _score("000003.SZ", 3)]
    monkeypatch.setattr(
        "apps.alpha.application.ai_filter.generate_chat_completion",
        lambda **kwargs: {"status": "success", "content": "not-json"},
    )

    result = AlphaAISecondPassFilterService().apply(
        _alpha_result(scores),
        top_n=2,
        user=None,
        trade_date=date(2026, 5, 6),
    )

    assert [score.code for score in result.scores] == ["000001.SZ", "000002.SZ"]
    assert result.metadata["ai_filter"]["status"] == "failed"
    assert "invalid_json" in result.metadata["ai_filter"]["failure_reason"]


def test_ai_filter_handles_missing_stock_context(monkeypatch):
    monkeypatch.setattr(
        "apps.alpha.application.ai_filter.get_stock_context_map",
        lambda codes: {},
    )
    monkeypatch.setattr(
        "apps.alpha.application.ai_filter.get_latest_market_thermometer_snapshot_payload",
        lambda: None,
    )
    scores = [_score("000001.SZ", 1), _score("000002.SZ", 2)]
    monkeypatch.setattr(
        "apps.alpha.application.ai_filter.generate_chat_completion",
        lambda **kwargs: _ai_response(
            [
                _decision("000001.SZ", verdict="buy", confidence=0.7),
                _decision("000002.SZ", verdict="watch", confidence=0.62),
            ]
        ),
    )

    result = AlphaAISecondPassFilterService().apply(
        _alpha_result(scores),
        top_n=2,
        user=None,
        trade_date=date(2026, 5, 6),
    )

    assert [score.code for score in result.scores] == ["000001.SZ", "000002.SZ"]
    assert result.metadata["ai_filter"]["status"] == "applied"


def _authenticated_client() -> Client:
    client = Client()
    user = User.objects.create_user(
        username=f"alpha-ai-filter-{uuid.uuid4().hex[:8]}",
        email=f"alpha-ai-filter-{uuid.uuid4().hex[:8]}@test.com",
        password="test-pass-123",
    )
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_alpha_scores_api_default_does_not_enable_ai_filter(monkeypatch):
    calls: list[dict] = []

    class FakeAlphaService:
        def get_stock_scores(self, *args, **kwargs):
            calls.append(kwargs)
            return _alpha_result([_score("000001.SZ", 1)])

    monkeypatch.setattr("apps.alpha.interface.views.AlphaService", lambda: FakeAlphaService())

    response = _authenticated_client().get("/api/alpha/scores/?top_n=1")

    assert response.status_code == 200
    assert calls[0]["ai_filter"] is False
    body = response.json()
    assert len(body["stocks"]) == 1
    assert "ai_filter" not in body["metadata"]


@pytest.mark.django_db
def test_alpha_scores_api_passes_ai_filter_parameter(monkeypatch):
    calls: list[dict] = []

    class FakeAlphaService:
        def get_stock_scores(self, *args, **kwargs):
            calls.append(kwargs)
            result = _alpha_result([_score("000001.SZ", 1)])
            result.metadata["ai_filter"] = {
                "enabled": True,
                "status": "applied",
                "input_count": 2,
                "kept_count": 1,
                "min_ai_confidence": 0.6,
                "decisions_by_code": {"000001.SZ": {"verdict": "buy"}},
            }
            return result

    monkeypatch.setattr("apps.alpha.interface.views.AlphaService", lambda: FakeAlphaService())

    response = _authenticated_client().get("/api/alpha/scores/?top_n=1&ai_filter=1")

    assert response.status_code == 200
    assert calls[0]["ai_filter"] is True
    body = response.json()
    assert body["metadata"]["ai_filter"]["status"] == "applied"
    assert len(body["stocks"]) == 1


@pytest.mark.django_db
def test_alpha_scores_api_returns_failed_ai_filter_metadata(monkeypatch):
    class FakeAlphaService:
        def get_stock_scores(self, *args, **kwargs):
            result = _alpha_result([_score("000001.SZ", 1)])
            result.metadata["ai_filter"] = {
                "enabled": True,
                "status": "failed",
                "input_count": 2,
                "kept_count": 1,
                "min_ai_confidence": 0.6,
                "decisions_by_code": {},
                "failure_reason": "provider timeout",
            }
            return result

    monkeypatch.setattr("apps.alpha.interface.views.AlphaService", lambda: FakeAlphaService())

    response = _authenticated_client().get("/api/alpha/scores/?top_n=1&ai_filter=1")

    assert response.status_code == 200
    body = response.json()
    assert body["metadata"]["ai_filter"]["status"] == "failed"
    assert body["metadata"]["ai_filter"]["failure_reason"] == "provider timeout"
    assert len(body["stocks"]) == 1
