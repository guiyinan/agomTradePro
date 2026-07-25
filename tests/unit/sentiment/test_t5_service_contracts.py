"""AI analysis and index calculation contracts for sentiment services."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.sentiment.application import services
from apps.sentiment.application.services import (
    SentimentAnalyzer,
    SentimentIndexCalculator,
)
from apps.sentiment.domain.entities import SentimentCategory, SentimentSource


def test_analyze_text_success_batch_and_source() -> None:
    adapter = MagicMock()
    adapter.chat_completion.return_value = {
        "status": "success",
        "content": '{"score": 2.5, "keywords": ["降息", "上涨"]}',
        "response_time_ms": 1000,
    }
    analyzer = SentimentAnalyzer(MagicMock())
    analyzer._adapter_cache = adapter

    result = analyzer.analyze_text("央行降息，市场上涨")
    assert result.sentiment_score == 2.5
    assert result.confidence == 0.9
    assert result.category == SentimentCategory.POSITIVE
    assert result.keywords == ["降息", "上涨"]
    assert len(analyzer.analyze_batch(["a", "b"])) == 2

    source = SentimentSource(
        source_type="news",
        source_id="1",
        title="央行降息",
        content="市场上涨",
        published_at=datetime(2026, 7, 24, tzinfo=UTC),
    )
    assert analyzer.analyze_source(source).category == SentimentCategory.POSITIVE


def test_analyze_text_failure_creates_neutral_result_and_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MagicMock()
    adapter.chat_completion.return_value = {"status": "failed", "error": "quota"}
    analyzer = SentimentAnalyzer(MagicMock())
    analyzer._adapter_cache = adapter
    alert_repo = MagicMock()
    monkeypatch.setattr(
        services, "get_sentiment_alert_repository", lambda: alert_repo
    )

    result = analyzer.analyze_text("test")

    assert result.sentiment_score == 0
    assert result.category == SentimentCategory.NEUTRAL
    assert result.error_message == "AI 调用失败: quota"
    alert_repo.create_alert.assert_called_once()

    alert_repo.create_alert.side_effect = RuntimeError("database down")
    analyzer._send_ai_failure_alert("", "offline")


def test_get_ai_adapter_validates_provider_and_caches_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MagicMock()
    repository.get_active_configured_system_providers.return_value = []
    analyzer = SentimentAnalyzer(repository)
    with pytest.raises(RuntimeError, match="AI 提供商"):
        analyzer._get_ai_adapter()

    provider = SimpleNamespace(
        extra_config={"api_mode": "chat", "fallback_enabled": True},
        base_url="https://example.test",
        default_model="model",
    )
    repository.get_active_configured_system_providers.return_value = [provider]
    repository.get_api_key.return_value = "secret"
    adapter = MagicMock()
    factory = MagicMock(return_value=adapter)
    monkeypatch.setattr(services, "build_openai_compatible_adapter", factory)
    assert analyzer._get_ai_adapter() is adapter
    assert analyzer._get_ai_adapter() is adapter
    factory.assert_called_once_with(
        base_url="https://example.test",
        api_key="secret",
        default_model="model",
        api_mode="chat",
        fallback_enabled=True,
    )


def test_parser_confidence_category_and_keyword_fallbacks() -> None:
    analyzer = SentimentAnalyzer(MagicMock())
    prompt = analyzer._build_sentiment_prompt("测试文本")
    assert "测试文本" in prompt
    assert analyzer._parse_sentiment_score('{"score": 9}') == 3
    assert analyzer._parse_sentiment_score('{"score": "bad"} fallback -2.5') == -2.5
    assert analyzer._parse_sentiment_score("no score") == 0
    assert analyzer._estimate_confidence({}, 0.2) == 0.75
    assert analyzer._estimate_confidence({}, 1.2) == 0.8
    assert analyzer._estimate_confidence({"response_time_ms": 1000}, -2.2) == 0.9
    assert analyzer._categorize_sentiment(0.5) == SentimentCategory.POSITIVE
    assert analyzer._categorize_sentiment(-0.5) == SentimentCategory.NEGATIVE
    assert analyzer._categorize_sentiment(0.0) == SentimentCategory.NEUTRAL
    assert analyzer._extract_keywords(
        "ignored", '{"keywords": ["a", "b", "c", "d", "e", "f"]}'
    ) == ["a", "b", "c", "d", "e"]


def test_index_calculator_uses_configured_weights_and_data_confidence() -> None:
    config = SimpleNamespace(
        get_news_weight=MagicMock(return_value=0.25),
        get_policy_weight=MagicMock(return_value=0.75),
    )
    calculator = SentimentIndexCalculator(config)
    index = calculator.calculate_index([1.0, 2.0], [-1.0])
    assert index.news_sentiment == pytest.approx(5 / 3)
    assert index.policy_sentiment == -1.0
    assert index.composite_index == pytest.approx(-1 / 3)
    assert index.confidence_level == 0.3
    assert index.data_sufficient is True

    empty = calculator.calculate_index([], [], news_weight=0.4, policy_weight=0.6)
    assert empty.composite_index == 0
    assert empty.data_sufficient is False
    assert SentimentIndexCalculator._weighted_average([]) == 0
