from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.audit.infrastructure.models import (
    IndicatorPerformanceModel,
    IndicatorThresholdConfigModel,
    ValidationSummaryModel,
)


@pytest.fixture
def staff_client(db):
    user = User.objects.create_user(
        username="audit-validation-staff",
        password="testpass123",
        is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def regular_client(db):
    user = User.objects.create_user(
        username="audit-validation-regular",
        password="testpass123",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_audit_validation_preview_is_staff_only_and_read_only(staff_client, regular_client):
    IndicatorThresholdConfigModel._default_manager.create(
        indicator_code="CN_PMI",
        indicator_name="PMI",
        is_active=True,
    )
    before = (
        ValidationSummaryModel._default_manager.count(),
        IndicatorPerformanceModel._default_manager.count(),
    )
    payload = {"start_date": "2025-01-01", "end_date": "2025-12-31"}

    denied = regular_client.post(
        "/api/audit/run-validation/preview/",
        payload,
        format="json",
    )
    response = staff_client.post(
        "/api/audit/run-validation/preview/",
        payload,
        format="json",
    )

    assert denied.status_code == 403
    assert response.status_code == 200
    assert response.json()["preview"] == {
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "active_indicator_count": 1,
        "indicator_codes": ["CN_PMI"],
        "writes": ["validation_summary", "indicator_performance_reports"],
    }
    assert (
        ValidationSummaryModel._default_manager.count(),
        IndicatorPerformanceModel._default_manager.count(),
    ) == before


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"start_date": "2025-02-01", "end_date": "2025-01-01"},
        {"start_date": "2025-01-01", "end_date": "2025-02-01", "unknown": True},
        {"start_date": "2025-01-01"},
    ],
)
def test_audit_validation_rejects_invalid_contract(staff_client, payload):
    with patch(
        "apps.audit.interface.validation_api_views.run_threshold_validation"
    ) as run_validation:
        response = staff_client.post(
            "/api/audit/run-validation/",
            payload,
            format="json",
        )

    assert response.status_code == 400
    run_validation.assert_not_called()


@pytest.mark.django_db
def test_audit_validation_commit_uses_exact_canonical_dates(staff_client):
    result = SimpleNamespace(
        success=True,
        validation_run_id="validation_test",
        validation_report=None,
        error=None,
    )
    with patch(
        "apps.audit.interface.validation_api_views.run_threshold_validation",
        return_value=result,
    ) as run_validation:
        response = staff_client.post(
            "/api/audit/run-validation/",
            {"start_date": "2025-01-01", "end_date": "2025-12-31"},
            format="json",
        )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "validation_run_id": "validation_test",
        "report": None,
    }
    kwargs = run_validation.call_args.kwargs
    assert kwargs["start_date"].isoformat() == "2025-01-01"
    assert kwargs["end_date"].isoformat() == "2025-12-31"
    assert kwargs["use_shadow_mode"] is False
