from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.sentiment.infrastructure.models import (
    SentimentAlertModel,
    SentimentAnalysisLog,
    SentimentCache,
    SentimentIndexModel,
)


def _index(**overrides):
    values = {
        "index_date": date(2026, 7, 29),
        "news_sentiment": 0.5,
        "policy_sentiment": 0.4,
        "composite_index": 0.45,
        "confidence_level": 0.8,
        "data_sufficient": True,
        "sector_sentiment": {"科技": 0.7},
        "news_count": 10,
        "policy_events_count": 2,
    }
    values.update(overrides)
    return SentimentIndexModel(**values)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"composite_index": float("nan")}, "finite and between"),
        ({"confidence_level": float("inf")}, "finite and between"),
        ({"news_count": True}, "cannot be a boolean"),
        ({"news_count": -1}, "non-negative integer"),
        ({"sector_sentiment": {"科技": 3.1}}, "finite and between"),
        ({"sector_sentiment": {"科技": True}}, "finite number"),
    ],
)
def test_sentiment_index_rejects_invalid_direct_writes(overrides, message):
    with pytest.raises(ValidationError, match=message):
        _index(**overrides).save()

    assert SentimentIndexModel.objects.count() == 0


@pytest.mark.django_db
def test_sentiment_index_detaches_sector_scores_from_caller():
    sector_scores = {"科技": 0.7}
    index = _index(sector_sentiment=sector_scores)
    index.save()
    sector_scores["科技"] = -2.0

    assert index.sector_sentiment == {"科技": 0.7}
    index.refresh_from_db()
    assert index.sector_sentiment == {"科技": 0.7}


@pytest.mark.django_db
def test_analysis_log_redacts_credentials_and_is_append_only():
    keywords = ["银行", "利率"]
    log = SentimentAnalysisLog.objects.create(
        source_type="news",
        source_id="article-1",
        input_text=(
            "Bearer top-secret token=raw-token " "postgres://alice:password@db.internal/main"
        ),
        sentiment_score=0.5,
        category="POSITIVE",
        confidence=0.8,
        keywords=keywords,
        ai_provider="provider-a",
        ai_model="model-a",
        ai_response_time_ms=20,
    )
    keywords.append("mutation")

    assert "top-secret" not in log.input_text
    assert "raw-token" not in log.input_text
    assert "password@" not in log.input_text
    assert log.keywords == ["银行", "利率"]

    log.confidence = 0.7
    with pytest.raises(ValidationError, match="immutable"):
        log.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        log.delete()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"text_hash": "not-a-sha256"}, "SHA-256"),
        ({"sentiment_score": float("nan")}, "finite and between"),
        ({"category": "UNKNOWN"}, "category is unsupported"),
        ({"confidence": 1.1}, "finite and between"),
        ({"keywords": ["duplicate", "duplicate"]}, "must be unique"),
    ],
)
def test_sentiment_cache_rejects_invalid_evidence(overrides, message):
    values = {
        "text_hash": "a" * 64,
        "sentiment_score": 0.5,
        "category": "POSITIVE",
        "confidence": 0.8,
        "keywords": ["keyword"],
    }
    values.update(overrides)

    with pytest.raises(ValidationError, match=message):
        SentimentCache.objects.create(**values)


@pytest.mark.django_db
def test_alert_redacts_metadata_and_enforces_resolution_state():
    caller_metadata = {
        "authorization": "Bearer top-secret",
        "nested": {"password": "database-password"},
        "url": "https://user:password@example.invalid/path",
    }
    alert = SentimentAlertModel.objects.create(
        alert_type="ai_failure",
        severity="warning",
        title="Provider failed",
        message="token=raw-token postgres://alice:password@db.internal/main",
        metadata=caller_metadata,
    )
    caller_metadata["nested"]["password"] = "mutation"

    assert "raw-token" not in alert.message
    assert "password@" not in alert.message
    assert alert.metadata["authorization"] == "***"
    assert alert.metadata["nested"]["password"] == "***"
    assert "password@" not in alert.metadata["url"]

    alert.resolve()
    alert.refresh_from_db()
    assert alert.is_resolved is True
    assert alert.resolved_at is not None
    assert timezone.is_aware(alert.resolved_at)

    with pytest.raises(ValidationError, match="unresolved alerts cannot"):
        SentimentAlertModel.objects.create(
            alert_type="no_data",
            severity="warning",
            title="Bad state",
            message="Bad state",
            is_resolved=False,
            resolved_at=timezone.now(),
        )
