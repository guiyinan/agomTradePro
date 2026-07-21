from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.alpha.domain.entities import AlphaResult, StockScore


@pytest.fixture(autouse=True)
def stub_stock_context_lookup(monkeypatch):
    """Keep Alpha API contracts isolated from read-through market-data backfills."""

    monkeypatch.setattr(
        "apps.equity.application.query_services.get_stock_context_map",
        lambda _codes: {},
    )


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="alpha_staff",
        password="testpass123",
        email="alpha-staff@example.com",
        is_staff=True,
    )


@pytest.mark.django_db
def test_alpha_provider_status_success_contract(authenticated_client):
    cache.clear()
    with patch(
        "apps.alpha.interface.views.AlphaService.get_provider_status",
        return_value={
            "cache": {
                "priority": 10,
                "status": "available",
                "max_staleness_days": 5,
                "error": None,
            },
            "simple": {
                "priority": 100,
                "status": "degraded",
                "max_staleness_days": 7,
                "error": "fallback mode",
            },
        },
    ) as mock_status:
        response = authenticated_client.get("/api/alpha/providers/status/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "cache": {
            "priority": 10,
            "status": "available",
            "max_staleness_days": 5,
            "error": None,
        },
        "simple": {
            "priority": 100,
            "status": "degraded",
            "max_staleness_days": 7,
            "error": "fallback mode",
        },
    }
    mock_status.assert_called_once_with()


@pytest.mark.django_db
def test_alpha_available_universes_success_contract(authenticated_client):
    cache.clear()
    with patch(
        "apps.alpha.interface.views.AlphaService.get_available_universes",
        return_value=["csi500", "csi300", "csi300"],
    ) as mock_universes:
        response = authenticated_client.get("/api/alpha/universes/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {"universes": ["csi300", "csi500"]}
    mock_universes.assert_called_once_with()


@pytest.mark.django_db
def test_alpha_health_success_contract(authenticated_client):
    cache.clear()
    with patch(
        "apps.alpha.interface.views.AlphaService.get_provider_status",
        return_value={
            "qlib": {"status": "unavailable"},
            "cache": {"status": "available"},
            "simple": {"status": "degraded"},
        },
    ) as mock_status:
        response = authenticated_client.get("/api/alpha/health/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["providers"] == {"available": 2, "total": 3}
    assert payload["timestamp"]
    mock_status.assert_called_once_with()


@pytest.mark.django_db
def test_alpha_scores_reject_invalid_top_n(authenticated_client):
    response = authenticated_client.get("/api/alpha/scores/?top_n=0")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["status"] == "invalid_request"
    assert "top_n" in payload["error"]


@pytest.mark.django_db
def test_alpha_scores_support_limit_offset_pagination(authenticated_client):
    scores = [
        StockScore(
            code=f"00000{index}.SZ",
            score=1.0 - (index / 100),
            rank=index,
            factors={"momentum": 0.5},
            source="test",
            confidence=0.9,
            asof_date=date(2026, 4, 2),
            intended_trade_date=date(2026, 4, 3),
            universe_id="csi300",
        )
        for index in range(1, 6)
    ]
    result = AlphaResult(
        success=True,
        scores=scores,
        source="test",
        timestamp="2026-04-03T09:30:00+08:00",
    )

    with patch(
        "apps.alpha.interface.views.AlphaService.get_stock_scores",
        return_value=result,
    ) as get_scores:
        response = authenticated_client.get("/api/alpha/scores/?top_n=5&limit=2&offset=2")

    assert response.status_code == 200
    payload = response.json()
    assert [stock["rank"] for stock in payload["stocks"]] == [3, 4]
    assert payload["total"] == 5
    assert payload["limit"] == 2
    assert payload["offset"] == 2
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    get_scores.assert_called_once()
    assert get_scores.call_args.args[:3] == ("csi300", date.today(), 5)


@pytest.mark.django_db
def test_alpha_scores_rejects_pagination_window_above_top_limit(authenticated_client):
    response = authenticated_client.get("/api/alpha/scores/?limit=2&offset=499")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "limit" in payload["error"]


@pytest.mark.django_db
def test_alpha_scores_non_staff_cannot_query_other_user(authenticated_client):
    response = authenticated_client.get("/api/alpha/scores/?user_id=42")

    assert response.status_code == 403
    payload = response.json()
    assert payload["success"] is False
    assert payload["status"] == "forbidden"


@pytest.mark.django_db
def test_alpha_upload_scores_requires_admin_for_system_scope(authenticated_client):
    response = authenticated_client.post(
        "/api/alpha/scores/upload/",
        {
            "universe_id": "csi300",
            "asof_date": "2026-04-02",
            "intended_trade_date": "2026-04-03",
            "scope": "system",
            "scores": [
                {"code": "600519.SH", "score": 0.9, "rank": 1},
            ],
        },
        format="json",
    )

    assert response.status_code == 403
    assert response.json()["error"] == "只有管理员可以上传系统级评分（scope=system）"


@pytest.mark.django_db
def test_alpha_health_returns_503_when_all_providers_unavailable(authenticated_client):
    with patch(
        "apps.alpha.interface.views.AlphaService.get_provider_status",
        return_value={
            "qlib": {"status": "unavailable"},
            "cache": {"status": "unavailable"},
        },
    ):
        response = authenticated_client.get("/api/alpha/health/")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unhealthy"
    assert payload["providers"] == {"available": 0, "total": 2}
