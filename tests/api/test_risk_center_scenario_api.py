"""API contracts for governed stress-scenario reads and validation."""

from datetime import UTC, date, datetime

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.risk_center.application.scenario_dtos import ScenarioSummaryDTO
from apps.risk_center.domain.scenarios import (
    HistoricalWindowParameters,
    ScenarioDefinition,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSourceType,
    ScenarioType,
)
from apps.risk_center.interface.scenario_api_views import (
    ScenarioResearchUnavailableView,
    StressScenarioListView,
    ValidateScenarioRevisionView,
)

pytestmark = pytest.mark.django_db


def _user() -> object:
    return get_user_model().objects.create_user(username="scenario-reader", password="x")


def _summary() -> ScenarioSummaryDTO:
    created_at = datetime(2026, 8, 1, tzinfo=UTC)
    definition = ScenarioDefinition(
        scenario_key="historical.api-test",
        name="API test",
        category="historical",
        owner="risk_center",
        created_at=created_at,
    )
    revision = ScenarioRevision(
        revision_id="revision-api-test",
        scenario_key=definition.scenario_key,
        version=1,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.HISTORICAL_WINDOW,
        parameters=HistoricalWindowParameters(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 2),
            source="published-bars",
            event_description="test",
        ),
        assumptions=("published",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="operator",
        change_reason="test",
        created_at=created_at,
    )
    return ScenarioSummaryDTO(definition=definition, revision=revision)


def test_scenario_catalog_requires_authentication() -> None:
    request = APIRequestFactory().get("/api/risk-center/stress-scenarios/")
    response = StressScenarioListView.as_view()(request)

    assert response.status_code in {401, 403}


def test_scenario_catalog_uses_application_facade(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.risk_center.interface.scenario_api_views.list_scenarios",
        lambda **kwargs: (_summary(),),
    )
    request = APIRequestFactory().get(
        "/api/risk-center/stress-scenarios/",
        {"include_inactive": "false"},
    )
    force_authenticate(request, user=_user())

    response = StressScenarioListView.as_view()(request)

    assert response.status_code == 200
    assert response.data["data"][0]["scenario_key"] == "historical.api-test"


def test_scenario_query_rejects_unknown_fields() -> None:
    request = APIRequestFactory().get(
        "/api/risk-center/stress-scenarios/",
        {"debug": "true"},
    )
    force_authenticate(request, user=_user())

    response = StressScenarioListView.as_view()(request)

    assert response.status_code == 400
    assert "debug" in response.data["details"]


def test_validate_revision_rejects_unknown_payload_fields() -> None:
    request = APIRequestFactory().post(
        "/api/risk-center/stress-scenarios/validate-revision/",
        {"scenario_key": "historical.api-test", "unexpected": True},
        format="json",
    )
    force_authenticate(request, user=_user())

    response = ValidateScenarioRevisionView.as_view()(request)

    assert response.status_code == 400
    assert "unexpected" in response.data["details"]


def test_research_surface_fails_closed_until_canonical_providers_exist() -> None:
    request = APIRequestFactory().get("/api/risk-center/research/market-state/")
    force_authenticate(request, user=_user())

    response = ScenarioResearchUnavailableView.as_view()(request)

    assert response.status_code == 503
    assert response.data["data"]["must_not_use_for_decision"] is True
    assert response.data["data"]["blocked_reason"] == (
        "canonical_research_evidence_provider_not_configured"
    )
