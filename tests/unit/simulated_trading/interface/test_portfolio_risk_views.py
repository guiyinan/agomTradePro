"""HTTP contracts for owner-scoped simulation-only portfolio risk reports."""

from __future__ import annotations

from unittest.mock import patch

from django.http import HttpRequest
from django.urls import resolve
from rest_framework.authentication import SessionAuthentication
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioRiskOutcome,
    PortfolioRiskReportPayload,
)
from apps.simulated_trading.application.portfolio_risk_public import (
    PortfolioRiskAccountAccessDenied,
    PortfolioRiskUnavailable,
)
from apps.simulated_trading.interface.portfolio_risk_views import (
    PortfolioPressureOptionsAPIView,
    PortfolioPressureRunAPIView,
    PortfolioRiskReportAPIView,
)


class _User:
    """Minimal authenticated principal for APIRequestFactory contracts."""

    pk = 77
    is_authenticated = True


def _report(*, outcome: PortfolioRiskOutcome = "unknown") -> PortfolioRiskReportPayload:
    """Build a complete public payload with a visible unknown and source record."""

    return {
        "account_id": 42,
        "as_of": "2026-11-03T02:00:00+00:00",
        "outcome": outcome,
        "policy_version": "portfolio-policy-v7",
        "resource_snapshot_hash": "a" * 64,
        "checks": [
            {
                "dimension": "liquidity",
                "status": "unknown",
                "reason_codes": ["liquidity_history_stale"],
                "summary": "Historical coverage is incomplete.",
                "details": {"coverage_fraction": "0.40"},
            }
        ],
        "sources": [
            {
                "source_id": "published-price-bars",
                "source_record_id": "publication-91:600000.SH",
                "raw_payload_sha256": "b" * 64,
                "observed_at": None,
                "observed_on": "2026-11-02",
                "observation_precision": "date",
                "available_at": "2026-11-02T01:00:00+00:00",
                "known_at": "2026-11-02T01:03:00+00:00",
                "cutoff": "2026-11-03T02:00:00+00:00",
                "valid_until": None,
                "purpose": "scenario_exit_pressure",
                "restrictions": ["historical_only"],
                "must_not_use_for_decision": False,
                "coverage_fraction": "0.40",
                "coverage_basis": "positions_with_source_bars",
            }
        ],
        "freshness": "unknown",
        "reliability": "partial",
        "must_not_use_for_decision": True,
        "scope": "simulation_only",
        "must_not_execute": True,
    }


def _authenticated_request(request: HttpRequest) -> None:
    """Attach the named authenticated principal to one generated request."""

    force_authenticate(request, user=_User())


def test_get_returns_unknown_business_report_as_json_without_running_pressure() -> None:
    """Unknown risk is HTTP 200 while its source clocks remain in the payload."""

    request = APIRequestFactory().get(
        "/api/simulated-trading/accounts/42/portfolio-risk/",
        HTTP_ACCEPT="application/json",
    )
    _authenticated_request(request)

    report = _report()
    report["sources"][0]["raw_payload_sha256"] = None
    with (
        patch(
            "apps.simulated_trading.interface.portfolio_risk_views.get_owner_portfolio_risk",
            return_value=report,
        ) as get_report,
        patch(
            "apps.simulated_trading.interface.portfolio_risk_views.run_owner_portfolio_pressure"
        ) as run_pressure,
    ):
        response = PortfolioRiskReportAPIView.as_view()(request, account_id=42)

    response.render()
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.data["outcome"] == "unknown"
    assert response.data["scope"] == "simulation_only"
    assert response.data["must_not_execute"] is True
    assert response.data["freshness"] == "unknown"
    assert response.data["reliability"] == "partial"
    assert response.data["must_not_use_for_decision"] is True
    assert response.data["sources"][0]["raw_payload_sha256"] is None
    assert response.data["sources"][0]["known_at"] == "2026-11-02T01:03:00+00:00"
    get_report.assert_called_once_with(user_id=77, account_id=42)
    run_pressure.assert_not_called()


def test_post_requires_literal_confirmation_before_calling_application() -> None:
    """An omitted confirmation cannot create Scenario evidence."""

    request = APIRequestFactory().post(
        "/api/simulated-trading/accounts/42/portfolio-risk/pressure-run/",
        {"scenario_version_id": "revision-3", "confirmed": False},
        format="json",
        HTTP_ACCEPT="application/json",
        HTTP_IDEMPOTENCY_KEY="run-1",
    )
    _authenticated_request(request)

    with patch(
        "apps.simulated_trading.interface.portfolio_risk_views.run_owner_portfolio_pressure"
    ) as run_pressure:
        response = PortfolioPressureRunAPIView.as_view()(request, account_id=42)

    assert response.status_code == 400
    run_pressure.assert_not_called()


def test_post_forwards_version_and_idempotency_after_confirmation() -> None:
    """A confirmed run uses its explicit version and request idempotency key."""

    request = APIRequestFactory().post(
        "/api/simulated-trading/accounts/42/portfolio-risk/pressure-run/",
        {"scenario_version_id": "revision-3", "confirmed": True},
        format="json",
        HTTP_ACCEPT="application/json",
        HTTP_IDEMPOTENCY_KEY="run-1",
    )
    _authenticated_request(request)

    with patch(
        "apps.simulated_trading.interface.portfolio_risk_views.run_owner_portfolio_pressure",
        return_value=_report(outcome="partial"),
    ) as run_pressure:
        response = PortfolioPressureRunAPIView.as_view()(request, account_id=42)

    assert response.status_code == 200
    assert response.data["outcome"] == "partial"
    assert response.data["must_not_execute"] is True
    run_pressure.assert_called_once_with(
        user_id=77,
        account_id=42,
        scenario_version_id="revision-3",
        idempotency_key="run-1",
        confirmed=True,
    )


def test_source_qualified_veto_report_remains_non_executable() -> None:
    """A valid negative decision may be used as a veto, never as execution permission."""

    report = _report(outcome="blocked")
    report["freshness"] = "qualified_snapshot"
    report["reliability"] = "source_bound"
    report["must_not_use_for_decision"] = False
    request = APIRequestFactory().get("/api/simulated-trading/accounts/42/portfolio-risk/")
    _authenticated_request(request)

    with patch(
        "apps.simulated_trading.interface.portfolio_risk_views.get_owner_portfolio_risk",
        return_value=report,
    ):
        response = PortfolioRiskReportAPIView.as_view()(request, account_id=42)

    assert response.status_code == 200
    assert response.data["freshness"] == "qualified_snapshot"
    assert response.data["reliability"] == "source_bound"
    assert response.data["must_not_use_for_decision"] is False
    assert response.data["must_not_execute"] is True


def test_cross_account_denial_does_not_disclose_account_existence() -> None:
    """The owner-scoped service rejection maps to one generic 403 response."""

    request = APIRequestFactory().get("/api/simulated-trading/accounts/99/portfolio-risk/")
    _authenticated_request(request)

    with patch(
        "apps.simulated_trading.interface.portfolio_risk_views.get_owner_portfolio_risk",
        side_effect=PortfolioRiskAccountAccessDenied(),
    ):
        response = PortfolioRiskReportAPIView.as_view()(request, account_id=99)

    assert response.status_code == 403
    assert "99" not in response.data["detail"]


def test_unavailable_consistent_read_maps_to_503() -> None:
    """A source or consistency outage is distinguishable from unknown risk data."""

    request = APIRequestFactory().get("/api/simulated-trading/accounts/42/portfolio-risk/")
    _authenticated_request(request)

    with patch(
        "apps.simulated_trading.interface.portfolio_risk_views.get_owner_portfolio_risk",
        side_effect=PortfolioRiskUnavailable(),
    ):
        response = PortfolioRiskReportAPIView.as_view()(request, account_id=42)

    assert response.status_code == 503
    assert response.data["detail"]


def test_mutating_pressure_endpoint_is_bound_to_session_authentication() -> None:
    """POST uses the browser session authenticator that enforces CSRF checks."""

    assert PortfolioPressureRunAPIView.authentication_classes == (SessionAuthentication,)
    assert PortfolioPressureRunAPIView.http_method_names == ("post", "options")
    assert PortfolioRiskReportAPIView.http_method_names == ("get", "options")


def test_pressure_scenario_catalog_is_read_only_and_returns_human_labels_with_revision_values() -> (
    None
):
    """The account catalog maps a visible label to one exact approved revision ID."""

    request = APIRequestFactory().get(
        "/api/simulated-trading/accounts/42/portfolio-risk/scenarios/",
        HTTP_ACCEPT="application/json",
    )
    _authenticated_request(request)
    payload = {
        "account_id": 42,
        "options": [{"value": "revision-opaque-17", "label": "流动性冲击 · v3"}],
        "scope": "simulation_only",
        "read_only": True,
    }

    with (
        patch(
            "apps.simulated_trading.interface.portfolio_risk_views.get_owner_portfolio_pressure_options",
            return_value=payload,
        ) as get_options,
        patch(
            "apps.simulated_trading.interface.portfolio_risk_views.run_owner_portfolio_pressure"
        ) as run_pressure,
    ):
        response = PortfolioPressureOptionsAPIView.as_view()(request, account_id=42)

    response.render()
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.data["options"] == payload["options"]
    assert response.data["options"][0]["value"] == "revision-opaque-17"
    assert "revision-opaque-17" not in response.data["options"][0]["label"]
    assert response.data["scope"] == "simulation_only"
    assert response.data["read_only"] is True
    get_options.assert_called_once_with(user_id=77, account_id=42)
    run_pressure.assert_not_called()


def test_pressure_scenario_catalog_empty_is_a_successful_read_with_no_fallback_choice() -> None:
    """An empty approved catalog offers no implicit latest or hard-coded revision."""

    request = APIRequestFactory().get(
        "/api/simulated-trading/accounts/42/portfolio-risk/scenarios/"
    )
    _authenticated_request(request)

    with patch(
        "apps.simulated_trading.interface.portfolio_risk_views.get_owner_portfolio_pressure_options",
        return_value={
            "account_id": 42,
            "options": [],
            "scope": "simulation_only",
            "read_only": True,
        },
    ) as get_options:
        response = PortfolioPressureOptionsAPIView.as_view()(request, account_id=42)

    response.render()
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.data["options"] == []
    get_options.assert_called_once_with(user_id=77, account_id=42)


def test_pressure_scenario_catalog_denies_accounts_outside_the_existing_read_scope() -> None:
    """The catalog reuses the service's owner/delegated-read authorization boundary."""

    request = APIRequestFactory().get(
        "/api/simulated-trading/accounts/99/portfolio-risk/scenarios/"
    )
    _authenticated_request(request)

    with patch(
        "apps.simulated_trading.interface.portfolio_risk_views.get_owner_portfolio_pressure_options",
        side_effect=PortfolioRiskAccountAccessDenied(),
    ) as get_options:
        response = PortfolioPressureOptionsAPIView.as_view()(request, account_id=99)

    assert response.status_code == 403
    assert "99" not in response.data["detail"]
    get_options.assert_called_once_with(user_id=77, account_id=99)


def test_pressure_scenario_catalog_rejects_query_overrides_without_reading() -> None:
    """A client cannot broaden the published Scenario catalog with query flags."""

    request = APIRequestFactory().get(
        "/api/simulated-trading/accounts/42/portfolio-risk/scenarios/?include_inactive=true"
    )
    _authenticated_request(request)

    with patch(
        "apps.simulated_trading.interface.portfolio_risk_views.get_owner_portfolio_pressure_options"
    ) as get_options:
        response = PortfolioPressureOptionsAPIView.as_view()(request, account_id=42)

    assert response.status_code == 400
    get_options.assert_not_called()


def test_pressure_scenario_catalog_maps_unavailable_read_to_503() -> None:
    """A catalogue service outage remains distinct from an empty approved catalog."""

    request = APIRequestFactory().get(
        "/api/simulated-trading/accounts/42/portfolio-risk/scenarios/"
    )
    _authenticated_request(request)

    with patch(
        "apps.simulated_trading.interface.portfolio_risk_views.get_owner_portfolio_pressure_options",
        side_effect=PortfolioRiskUnavailable(),
    ):
        response = PortfolioPressureOptionsAPIView.as_view()(request, account_id=42)

    assert response.status_code == 503
    assert response.data["detail"]


def test_pressure_scenario_catalog_route_resolves_to_the_read_only_get_view() -> None:
    """The account-scoped catalog route exposes the GET-only Scenario options view."""

    match = resolve("/api/simulated-trading/accounts/42/portfolio-risk/scenarios/")

    assert match.url_name == "portfolio-pressure-scenarios"
    assert match.func.view_class is PortfolioPressureOptionsAPIView
    assert PortfolioPressureOptionsAPIView.http_method_names == ("get", "options")


def test_portfolio_risk_root_route_rejects_post() -> None:
    """The report route cannot be used as an alternate pressure-run write path."""

    path = "/api/simulated-trading/accounts/42/portfolio-risk/"
    request = APIRequestFactory().post(path, {}, format="json")
    _authenticated_request(request)

    match = resolve(path)
    assert match.func.view_class is PortfolioRiskReportAPIView
    response = match.func(request, account_id=42)

    assert response.status_code == 405


def test_pressure_run_route_rejects_get() -> None:
    """The pressure-run subresource cannot be read as the risk report route."""

    path = "/api/simulated-trading/accounts/42/portfolio-risk/pressure-run/"
    request = APIRequestFactory().get(path)
    _authenticated_request(request)

    match = resolve(path)
    assert match.func.view_class is PortfolioPressureRunAPIView
    response = match.func(request, account_id=42)

    assert response.status_code == 405


def test_pressure_options_route_rejects_post() -> None:
    """The approved Scenario catalog remains a read-only GET resource."""

    path = "/api/simulated-trading/accounts/42/portfolio-risk/scenarios/"
    request = APIRequestFactory().post(path, {}, format="json")
    _authenticated_request(request)

    match = resolve(path)
    assert match.func.view_class is PortfolioPressureOptionsAPIView
    response = match.func(request, account_id=42)

    assert response.status_code == 405
