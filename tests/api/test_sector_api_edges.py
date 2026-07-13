from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.sector.infrastructure.models import (
    SectorConstituentModel,
    SectorIndexModel,
    SectorInfoModel,
    SectorPreferenceConfigModel,
    SectorRelativeStrengthModel,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="sector_user",
        password="testpass123",
        email="sector@example.com",
    )


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="sector_staff",
        password="testpass123",
        email="sector-staff@example.com",
        is_staff=True,
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.fixture
def staff_client(api_client, staff_user):
    api_client.force_authenticate(user=staff_user)
    return api_client


@pytest.mark.django_db
def test_sector_analyze_maps_unavailable_result_to_200(authenticated_client):
    result = SimpleNamespace(
        success=False,
        status="unavailable",
        regime="Recovery",
        analysis_date="2026-04-02",
        top_sectors=[],
        market_breadth=None,
        concentration_score=None,
        error="upstream unavailable",
    )

    with patch("apps.sector.interface.views.AnalyzeSectorRotationUseCase.execute", return_value=result):
        response = authenticated_client.post(
            "/api/sector/analyze/",
            {"lookback_days": 20, "level": "SW1", "top_n": 5},
            format="json",
        )

    assert response.status_code == 200
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_sector_update_data_returns_400_on_failed_use_case(staff_client):
    result = SimpleNamespace(success=False, updated_count=0, error="adapter failed")

    with patch("apps.sector.interface.views.UpdateSectorDataUseCase.execute", return_value=result):
        response = staff_client.post(
            "/api/sector/update-data/",
            {"level": "SW1", "force_update": True},
            format="json",
        )

    assert response.status_code == 400
    assert response.json() == {"success": False, "error": "adapter failed"}


@pytest.mark.django_db
def test_sector_update_data_rejects_non_staff_user(authenticated_client):
    response = authenticated_client.post(
        "/api/sector/update-data/",
        {"level": "SW1", "force_update": True},
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_sector_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/sector/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["endpoints"]["rotation"] == "/api/sector/rotation/"
    assert payload["endpoints"]["analyze"] == "/api/sector/analyze/"


def _sector_table_snapshot():
    models = (
        SectorInfoModel,
        SectorIndexModel,
        SectorConstituentModel,
        SectorRelativeStrengthModel,
        SectorPreferenceConfigModel,
    )
    return {
        model._meta.label_lower: list(
            model._default_manager.order_by("pk").values()
        )
        for model in models
    }


@pytest.mark.django_db
def test_sector_rotation_is_strict_persisted_read(authenticated_client):
    today = date.today()
    sector = SectorInfoModel._default_manager.create(
        sector_code="801010",
        sector_name="农林牧渔",
        level="SW1",
    )
    SectorPreferenceConfigModel._default_manager.create(
        regime="Recovery",
        sector_name=sector.sector_name,
        weight=0.8,
    )
    for offset, change_pct in ((2, 1.0), (1, 2.0)):
        SectorIndexModel._default_manager.create(
            sector_code=sector.sector_code,
            trade_date=today - timedelta(days=offset),
            open_price=Decimal("1000.00"),
            high=Decimal("1020.00"),
            low=Decimal("990.00"),
            close=Decimal("1010.00"),
            volume=1000,
            amount=Decimal("1000000.00"),
            change_pct=change_pct,
        )
    SectorConstituentModel._default_manager.create(
        sector_code=sector.sector_code,
        stock_code="000001.SZ",
        enter_date=today - timedelta(days=30),
    )
    SectorRelativeStrengthModel._default_manager.create(
        sector_code=sector.sector_code,
        trade_date=today - timedelta(days=1),
        relative_strength=1.5,
        momentum=2.0,
    )
    before = _sector_table_snapshot()

    with patch(
        "apps.sector.interface.views.UpdateSectorDataUseCase.execute",
        side_effect=AssertionError("GET must not synchronize sector providers"),
    ) as sync_execute, patch(
        "apps.equity.infrastructure.adapters.MarketDataRepositoryAdapter._load_remote_index_points",
        side_effect=AssertionError("GET must not hydrate benchmark data"),
    ) as remote_loader:
        response = authenticated_client.get(
            "/api/sector/rotation/",
            {
                "regime": "Recovery",
                "lookback_days": 5,
                "level": "SW1",
                "top_n": 5,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["regime"] == "Recovery"
    assert payload["data_source"] == "fallback"
    assert payload["top_sectors"][0]["sector_code"] == sector.sector_code
    assert payload["top_sectors"][0]["regime_fit_score"] == 80.0
    assert _sector_table_snapshot() == before
    sync_execute.assert_not_called()
    remote_loader.assert_not_called()


@pytest.mark.django_db
def test_sector_rotation_does_not_bootstrap_missing_data(authenticated_client):
    result = SimpleNamespace(
        success=False,
        status="unavailable",
        regime="Recovery",
        analysis_date="2026-04-06",
        top_sectors=[],
        error="未找到级别为 SW1 的板块数据",
        warning_message="sector_data_unavailable",
        warning_detail="请通过显式数据更新流程同步。",
        data_source="persisted",
    )

    with patch(
        "apps.sector.interface.views.AnalyzeSectorRotationUseCase.execute",
        return_value=result,
    ) as analyze_execute, patch(
        "apps.sector.interface.views.UpdateSectorDataUseCase.execute",
        side_effect=AssertionError("GET must not synchronize sector providers"),
    ) as sync_execute:
        response = authenticated_client.get("/api/sector/rotation/?level=SW1")

    assert response.status_code == 200
    assert response.json()["success"] is False
    analyze_execute.assert_called_once()
    sync_execute.assert_not_called()


@pytest.mark.django_db
def test_sector_rotation_rejects_unknown_query_parameters(authenticated_client):
    response = authenticated_client.get("/api/sector/rotation/?payload=legacy")

    assert response.status_code == 400
    assert "Unknown query parameters: payload" in str(response.json())


@pytest.mark.django_db
def test_sector_rotation_requires_authentication(api_client):
    response = api_client.get("/api/sector/rotation/")

    assert response.status_code in {401, 403}
