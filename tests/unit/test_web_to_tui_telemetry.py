"""Unit contracts for bounded Web-to-TUI telemetry classification."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from django.http import HttpRequest, JsonResponse
from django.test import RequestFactory
from django.urls import resolve

from core.ui_migration_telemetry import (
    UiMigrationTelemetryCatalog,
    classify_ui_migration_request,
)
from scripts import build_web_to_tui_telemetry_catalog as telemetry_catalog
from scripts.build_web_to_tui_telemetry_catalog import build_catalog
from scripts.check_web_to_tui_cutover_readiness import required_route_pages

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
CATALOG_PATH = ROOT / "config/tui/migration/web_to_tui_telemetry.v1.json"
ALERTS_PATH = ROOT / "monitoring/alerts.yml"


def _authenticate(request: HttpRequest) -> HttpRequest:
    """Attach the minimal authenticated-user contract used by the classifier."""

    request.user = SimpleNamespace(is_authenticated=True)
    return request


def _catalog() -> UiMigrationTelemetryCatalog:
    """Return a small catalog for classifier unit tests."""

    return UiMigrationTelemetryCatalog(
        task_by_url_name={
            "simulated_trading:dashboard": "simulated-trading.accounts",
        },
        task_keys=frozenset(
            {
                "simulated-trading.accounts",
                "simulated-trading.account-detail",
                "screen:execution.accounts",
            }
        ),
    )


def test_generated_telemetry_catalog_matches_reviewed_matrix() -> None:
    """The runtime catalog must remain a deterministic matrix projection."""

    expected = build_catalog(MATRIX_PATH)
    actual = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    assert actual == expected
    assert len(actual["classic_routes"]) >= 108
    assert "simulated-trading.accounts" in actual["tui_task_keys"]


def test_m5_deleted_route_remains_in_uat_and_telemetry_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting Classic UI must not erase the historical task from M5 evidence."""

    target = "core/templates/sentiment/analyze.html"
    with MATRIX_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames is not None
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    for row in rows:
        if row["template_path"] == target:
            row["status"] = "deleted"
            row["wave"] = "M5-B-W1"
            break
    matrix_path = tmp_path / "matrix.csv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    monkeypatch.setattr(telemetry_catalog, "ROOT", tmp_path)
    catalog = build_catalog(matrix_path)

    assert target in required_route_pages(matrix_path)
    assert any(route["template_path"] == target for route in catalog["classic_routes"])


def test_classifies_classic_route_by_resolved_url_name() -> None:
    """Classic labels come from the reviewed URL-name map, not raw paths."""

    request = _authenticate(RequestFactory().get("/simulated-trading/dashboard/"))
    request.resolver_match = resolve("/simulated-trading/dashboard/")

    event = classify_ui_migration_request(
        request,
        JsonResponse({"ok": True}),
        catalog=_catalog(),
    )

    assert event is not None
    assert event.surface == "classic"
    assert event.event_type == "entry"
    assert event.task_key == "simulated-trading.accounts"
    assert event.outcome == "success"


def test_classifies_tui_deep_link_with_bounded_action_key() -> None:
    """A TUI deep link is comparable with the Classic primary task."""

    request = _authenticate(
        RequestFactory().get(
            "/tui/",
            {"screen": "execution.accounts", "action": "simulated-trading.accounts"},
        )
    )

    event = classify_ui_migration_request(
        request,
        JsonResponse({"ok": True}),
        catalog=_catalog(),
    )

    assert event is not None
    assert event.surface == "tui"
    assert event.event_type == "entry"
    assert event.task_key == "simulated-trading.accounts"


def test_tui_missing_fields_and_confirmation_are_not_runtime_errors() -> None:
    """Expected form discovery and confirmation handshakes are separate outcomes."""

    factory = RequestFactory()
    missing_request = _authenticate(
        factory.post(
            "/api/tui/actions/simulated-trading.account-detail/run/",
            data="{}",
            content_type="application/json",
        )
    )
    missing_response = JsonResponse({})
    missing_response.data = {
        "response": {"status_code": 400},
        "missing_fields": [{"key": "account_id"}],
    }
    confirmation_request = _authenticate(
        factory.post(
            "/api/tui/actions/simulated-trading.accounts/run/",
            data="{}",
            content_type="application/json",
        )
    )
    confirmation_response = JsonResponse({})
    confirmation_response.data = {
        "response": {"status_code": 409},
        "confirmation_required": True,
    }

    missing_event = classify_ui_migration_request(
        missing_request,
        missing_response,
        catalog=_catalog(),
    )
    confirmation_event = classify_ui_migration_request(
        confirmation_request,
        confirmation_response,
        catalog=_catalog(),
    )

    assert missing_event is not None
    assert missing_event.event_type == "form"
    assert missing_event.outcome == "input_required"
    assert confirmation_event is not None
    assert confirmation_event.event_type == "confirmation"
    assert confirmation_event.outcome == "confirmation_required"


def test_classic_api_request_uses_reviewed_same_origin_referrer_task() -> None:
    """Classic fetch/XHR calls contribute comparable execution outcomes."""

    request = _authenticate(
        RequestFactory().get(
            "/api/health/",
            HTTP_REFERER="http://testserver/simulated-trading/dashboard/",
        )
    )

    event = classify_ui_migration_request(
        request,
        JsonResponse({"ok": False}, status=500),
        catalog=_catalog(),
    )

    assert event is not None
    assert event.surface == "classic"
    assert event.event_type == "execution"
    assert event.task_key == "simulated-trading.accounts"
    assert event.outcome == "server_error"


def test_external_referrer_cannot_claim_a_classic_task() -> None:
    """Only same-origin Classic navigation may classify an API execution."""

    request = _authenticate(
        RequestFactory().get(
            "/api/health/",
            HTTP_REFERER="https://example.invalid/simulated-trading/dashboard/",
        )
    )

    event = classify_ui_migration_request(
        request,
        JsonResponse({"ok": True}),
        catalog=_catalog(),
    )

    assert event is None


def test_unapproved_tui_task_is_not_recorded() -> None:
    """Untrusted path values must never create new Prometheus label values."""

    request = _authenticate(
        RequestFactory().post(
            "/api/tui/actions/user-controlled-value/run/",
            data="{}",
            content_type="application/json",
        )
    )

    event = classify_ui_migration_request(
        request,
        JsonResponse({"ok": False}, status=500),
        catalog=_catalog(),
    )

    assert event is None


def test_anonymous_requests_do_not_enter_migration_samples() -> None:
    """Login redirects and spoofed referrers cannot dilute production task evidence."""

    classic_request = RequestFactory().get("/simulated-trading/dashboard/")
    classic_request.resolver_match = resolve("/simulated-trading/dashboard/")
    referrer_request = RequestFactory().get(
        "/api/health/",
        HTTP_REFERER="http://testserver/simulated-trading/dashboard/",
    )

    assert (
        classify_ui_migration_request(
            classic_request,
            JsonResponse({"redirect": "login"}, status=302),
            catalog=_catalog(),
        )
        is None
    )
    assert (
        classify_ui_migration_request(
            referrer_request,
            JsonResponse({"ok": True}),
            catalog=_catalog(),
        )
        is None
    )


def test_m5_prometheus_rules_keep_reviewed_thresholds() -> None:
    """M5 telemetry alerts must retain their approved window and thresholds."""

    payload = yaml.safe_load(ALERTS_PATH.read_text(encoding="utf-8"))
    migration_group = next(
        group for group in payload["groups"] if group["name"] == "web_to_tui_migration_readiness"
    )
    rules = migration_group["rules"]
    rules_by_name = {
        str(rule.get("record") or rule.get("alert")): str(rule["expr"]) for rule in rules
    }

    assert "[14d]" in rules_by_name["web_to_tui:entry_samples_14d"]
    assert 'surface="classic"' in rules_by_name["web_to_tui:legacy_entry_ratio_14d"]
    assert (
        'outcome=~"client_error|server_error"'
        in rules_by_name["web_to_tui:execution_error_ratio_14d"]
    )
    assert (
        'event_type=~"entry|execution"' in rules_by_name["web_to_tui:task_request_error_ratio_14d"]
    )
    assert "> 0.05" in rules_by_name["WebToTuiLegacyEntryRatioHigh"]
    assert ">= 20" in rules_by_name["WebToTuiLegacyEntryRatioHigh"]
    assert "> 0.005" in rules_by_name["WebToTuiErrorRateRegression"]
    assert ">= 20" in rules_by_name["WebToTuiErrorRateRegression"]
