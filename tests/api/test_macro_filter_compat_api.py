from datetime import date

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.macro.infrastructure.models import MacroIndicator


@pytest.mark.django_db
def test_macro_indicator_data_accepts_indicator_code_alias():
    MacroIndicator.objects.create(
        code="CN_PMI",
        value=50.2,
        unit="指数",
        original_unit="指数",
        reporting_period=date(2026, 3, 1),
        period_type="M",
        source="manual",
        revision_number=1,
    )

    response = APIClient().get("/api/macro/indicator-data/?indicator_code=CN_PMI")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["data"][0]["code"] == "CN_PMI"


@pytest.mark.django_db
def test_filter_api_root_contract():
    user = User.objects.create_user(username="filter-api", password="pass")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/filter/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["service"] == "Filter API"
    assert payload["endpoints"]["apply"]["method"] == "POST"
