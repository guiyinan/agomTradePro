from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from apps.market_data.domain.entities import QuoteSnapshot
from apps.market_data.interface.page_views import build_provider_dashboard

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


@pytest.mark.django_db
def test_market_data_providers_page_explains_where_tushare_is_configured():
    user = User.objects.create_user(
        username="market_page_user",
        password="pass123",
        is_staff=True,
    )
    client = Client()
    client.force_login(user)

    response = client.get("/market-data/providers/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "这不是 Tushare 配置页" in content
    assert "市场数据源状态" in content
    assert "/macro/datasources/#tushare-guide" in content


def test_build_provider_dashboard_groups_statuses_by_provider(mocker):
    status_1 = Mock()
    status_1.to_dict.return_value = {
        "provider_name": "eastmoney",
        "capability": "realtime_quote",
        "is_healthy": True,
    }
    status_2 = Mock()
    status_2.to_dict.return_value = {
        "provider_name": "eastmoney",
        "capability": "stock_news",
        "is_healthy": False,
    }
    status_3 = Mock()
    status_3.to_dict.return_value = {
        "provider_name": "tushare",
        "capability": "realtime_quote",
        "is_healthy": True,
    }

    registry = Mock()
    registry.get_all_statuses.return_value = [status_1, status_2, status_3]
    mocker.patch("apps.market_data.interface.page_views.get_registry", return_value=registry)

    dashboard = build_provider_dashboard()

    assert dashboard["provider_count"] == 2
    assert dashboard["healthy_provider_count"] == 1
    assert dashboard["unhealthy_provider_count"] == 1
    assert dashboard["providers"][0]["name"] == "eastmoney"
    assert dashboard["providers"][0]["unhealthy_count"] == 1
