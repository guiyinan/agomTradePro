from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.market_data.domain.entities import QuoteSnapshot

User = get_user_model()


@pytest.mark.django_db
def test_realtime_quotes_returns_close_fallback_metadata_when_tushare_used(mocker):
    user = User.objects.create_user(username="market_tester", password="pass123")
    client = APIClient()
    client.force_authenticate(user=user)

    snapshot = QuoteSnapshot(
        stock_code="000001.SZ",
        price=Decimal("12.3400"),
        source="tushare",
    )
    registry = Mock()
    registry.call_with_failover.return_value = [snapshot]
    mocker.patch("apps.market_data.interface.views.get_registry", return_value=registry)
    mocker.patch(
        "apps.market_data.interface.views.timezone.now",
        return_value=timezone.make_aware(datetime(2026, 3, 12, 17, 52, 0)),
    )

    response = client.get("/api/market-data/quotes/?codes=000001.SZ")

    assert response.status_code == 200
    assert response.data["fallback_mode"] == "close_fallback"
    assert response.data["market_closed"] is True
    assert "收盘价" in response.data["message"]


@pytest.mark.django_db
def test_realtime_quotes_returns_closed_market_hint_when_all_providers_fail(mocker):
    user = User.objects.create_user(username="market_tester_2", password="pass123")
    client = APIClient()
    client.force_authenticate(user=user)

    registry = Mock()
    registry.call_with_failover.return_value = None
    mocker.patch("apps.market_data.interface.views.get_registry", return_value=registry)
    mocker.patch(
        "apps.market_data.interface.views.timezone.now",
        return_value=timezone.make_aware(datetime(2026, 3, 12, 17, 52, 0)),
    )

    response = client.get("/api/market-data/quotes/?codes=000001.SZ")

    assert response.status_code == 503
    assert response.data["market_closed"] is True
    assert response.data["fallback_mode"] == "unavailable"
    assert "收盘" in response.data["error"]
