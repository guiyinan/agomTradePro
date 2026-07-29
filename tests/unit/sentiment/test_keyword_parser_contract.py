"""Regression contract for malformed AI keyword payloads."""

from unittest.mock import MagicMock

from apps.sentiment.application.services import SentimentAnalyzer


def test_non_list_ai_keywords_fall_back_to_financial_term_extraction() -> None:
    analyzer = SentimentAnalyzer(MagicMock())

    keywords = analyzer._extract_keywords(
        "降息后市场上涨并出现利好",
        '{"keywords": "invalid"}',
    )

    assert keywords == ["降息", "上涨", "利好"]
