import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.market_data.interface.views import get_stock_news, ingest_stock_news


def _make_test_user():
    User = get_user_model()
    return User.objects.create_user(
        username=f"market_data_{uuid.uuid4().hex[:8]}",
        password="testpass123",
    )


@pytest.mark.django_db
class TestMarketDataViews:
    def setup_method(self):
        self.factory = APIRequestFactory()
        self.user = _make_test_user()

    @patch("apps.market_data.interface.views.get_registry")
    def test_get_stock_news_invalid_limit_returns_400(self, mock_get_registry):
        request = self.factory.get("/api/market-data/news/?code=000001.SZ&limit=abc")
        force_authenticate(request, user=self.user)

        response = get_stock_news(request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "limit" in response.data["error"]
        mock_get_registry.assert_not_called()

    @patch("apps.market_data.interface.views.get_registry")
    def test_get_stock_news_non_positive_limit_returns_400(self, mock_get_registry):
        request = self.factory.get("/api/market-data/news/?code=000001.SZ&limit=0")
        force_authenticate(request, user=self.user)

        response = get_stock_news(request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "limit" in response.data["error"]
        mock_get_registry.assert_not_called()

    @patch("apps.market_data.interface.views.get_registry")
    def test_ingest_stock_news_invalid_limit_returns_400(self, mock_get_registry):
        request = self.factory.post(
            "/api/market-data/news/ingest/",
            {"stock_code": "000001.SZ", "limit": "bad"},
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ingest_stock_news(request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "limit" in response.data["error"]
        mock_get_registry.assert_not_called()
