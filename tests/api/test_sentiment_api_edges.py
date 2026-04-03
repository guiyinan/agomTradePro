from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="sentiment_user",
        password="testpass123",
        email="sentiment@example.com",
    )


@pytest.fixture
def authenticated_client(client, auth_user):
    client.force_login(auth_user)
    return client


@pytest.mark.django_db
def test_sentiment_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/sentiment/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["analyze"] == "/api/sentiment/analyze/"
    assert payload["endpoints"]["health"] == "/api/sentiment/health/"


@pytest.mark.django_db
def test_sentiment_analyze_returns_503_when_ai_unavailable(authenticated_client):
    with patch(
        "apps.sentiment.interface.views.SentimentAnalyzer.analyze_text",
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
def test_sentiment_recent_days_out_of_range_falls_back_to_default(authenticated_client):
    with patch("apps.sentiment.interface.views.SentimentIndexRepository.get_recent") as mock_recent:
        mock_recent.return_value = []
        response = authenticated_client.get("/api/sentiment/index/recent/?days=999")

    assert response.status_code == 200
    mock_recent.assert_called_once_with(days=30)


@pytest.mark.django_db
def test_sentiment_cache_clear_returns_deleted_count(authenticated_client):
    with patch("apps.sentiment.interface.views.SentimentCacheRepository.clear", return_value=7):
        response = authenticated_client.post("/api/sentiment/cache/clear/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["message"] == "已清除 7 条缓存记录"
