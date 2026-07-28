from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.sentiment.infrastructure.models import SentimentCache


@pytest.fixture
def authenticated_client(client, auth_user):
    client.force_login(auth_user)
    return client


@pytest.fixture
def staff_client(client, db):
    staff_user = get_user_model().objects.create_user(
        username="sentiment_staff",
        password="testpass123",
        email="sentiment-staff@example.com",
        is_staff=True,
    )
    client.force_login(staff_user)
    return client


@pytest.mark.django_db
def test_sentiment_analyze_returns_503_when_ai_unavailable(authenticated_client):
    with patch(
        "apps.sentiment.interface.views.analyze_sentiment_text",
        side_effect=RuntimeError("AI provider unavailable"),
    ):
        response = authenticated_client.post(
            "/api/sentiment/analyze/",
            {"text": "市场情绪很强"},
            content_type="application/json",
        )

    assert response.status_code == 503
    assert response.json()["error"] == "AI provider unavailable"


@pytest.mark.django_db
def test_sentiment_index_rejects_invalid_date_format(authenticated_client):
    response = authenticated_client.get("/api/sentiment/index/?date=2026/04/02")

    assert response.status_code == 400
    assert response.json()["error"] == "日期格式错误，应为 YYYY-MM-DD"


@pytest.mark.django_db
def test_sentiment_index_returns_canonical_payload(authenticated_client):
    payload = {
        "date": "2026-07-10",
        "index": {"overall": 0.62},
        "level": "positive",
        "confidence": 0.84,
        "data_sufficient": True,
        "sector_sentiment": {"technology": 0.71},
        "sources": {"news": 18},
    }
    with patch(
        "apps.sentiment.interface.views.get_sentiment_index_payload",
        return_value=payload,
    ) as mock_index:
        response = authenticated_client.get("/api/sentiment/index/?date=2026-07-10")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == payload
    mock_index.assert_called_once()
    assert mock_index.call_args.args[0].isoformat() == "2026-07-10"


@pytest.mark.django_db
def test_sentiment_recent_days_out_of_range_falls_back_to_default(authenticated_client):
    with patch(
        "apps.sentiment.interface.views.get_recent_sentiment_indices_payload"
    ) as mock_recent:
        mock_recent.return_value = {"indices": [], "total": 0}
        response = authenticated_client.get("/api/sentiment/index/recent/?days=999")

    assert response.status_code == 200
    mock_recent.assert_called_once_with(days=30)


@pytest.mark.django_db
def test_sentiment_recent_returns_canonical_envelope(authenticated_client):
    payload = {
        "indices": [
            {
                "date": "2026-07-10",
                "index": {"overall": 0.62},
                "level": "positive",
                "confidence": 0.84,
                "data_sufficient": True,
                "sector_sentiment": {},
                "sources": {"news": 18},
            }
        ],
        "total": 1,
    }
    with patch(
        "apps.sentiment.interface.views.get_recent_sentiment_indices_payload",
        return_value=payload,
    ) as mock_recent:
        response = authenticated_client.get("/api/sentiment/index/recent/?days=7")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == payload
    mock_recent.assert_called_once_with(days=7)


@pytest.mark.django_db
def test_sentiment_health_returns_canonical_payload(authenticated_client):
    payload = {
        "status": "healthy",
        "ai_provider_available": True,
        "cache_count": 12,
        "latest_index_date": "2026-07-10",
    }
    with patch(
        "apps.sentiment.interface.views.get_sentiment_health_payload",
        return_value=payload,
    ):
        response = authenticated_client.get("/api/sentiment/health/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == payload


@pytest.mark.django_db
def test_sentiment_tui_overview_flattens_recent_indices(
    authenticated_client,
) -> None:
    recent = {
        "indices": [
            {
                "date": "2026-07-10",
                "index": {
                    "composite": 0.62,
                    "news": 0.71,
                    "policy": 0.41,
                },
                "level": "乐观",
                "confidence": 0.84,
                "data_sufficient": True,
                "sector_sentiment": {},
                "sources": {
                    "news_count": 18,
                    "policy_events_count": 4,
                },
            }
        ],
        "total": 1,
    }
    health = {
        "status": "healthy",
        "ai_provider_available": True,
        "cache_count": 12,
        "latest_index_date": "2026-07-10",
    }
    with (
        patch(
            "apps.sentiment.interface.tui_views.get_recent_sentiment_indices_payload",
            return_value=recent,
        ) as recent_mock,
        patch(
            "apps.sentiment.interface.tui_views.get_sentiment_health_payload",
            return_value=health,
        ),
    ):
        response = authenticated_client.get("/api/sentiment/tui/overview/?days=14")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["summary"]["latest_level"] == "乐观"
    assert payload["summary"]["latest_confidence_percent"] == 84.0
    assert payload["indices"] == [
        {
            "date": "2026-07-10",
            "composite": 0.62,
            "news": 0.71,
            "policy": 0.41,
            "level": "乐观",
            "confidence_percent": 84.0,
            "data_sufficient": True,
            "news_count": 18,
            "policy_events_count": 4,
        }
    ]
    recent_mock.assert_called_once_with(days=14)


@pytest.mark.django_db
@pytest.mark.parametrize("days", ["0", "366", "bad"])
def test_sentiment_tui_overview_rejects_invalid_days(
    authenticated_client,
    days: str,
) -> None:
    response = authenticated_client.get(f"/api/sentiment/tui/overview/?days={days}")

    assert response.status_code == 400
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_sentiment_cache_clear_rejects_non_staff_user(authenticated_client):
    response = authenticated_client.post("/api/sentiment/cache/clear/")

    assert response.status_code == 403
    assert SentimentCache._default_manager.count() == 0


@pytest.mark.django_db
def test_sentiment_cache_clear_deletes_persisted_rows_for_staff(staff_client):
    SentimentCache._default_manager.bulk_create(
        [
            SentimentCache(
                text_hash="a" * 64,
                sentiment_score=0.5,
                category="POSITIVE",
                confidence=0.8,
                keywords=["growth"],
            ),
            SentimentCache(
                text_hash="b" * 64,
                sentiment_score=-0.5,
                category="NEGATIVE",
                confidence=0.7,
                keywords=["risk"],
            ),
        ]
    )

    response = staff_client.post("/api/sentiment/cache/clear/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["message"] == "已清除 2 条缓存记录"
    assert SentimentCache._default_manager.count() == 0
