"""API boundary regressions for the immutable signal forecast ledger."""

from datetime import UTC, datetime, timedelta

import pytest


def _entry_payload() -> dict[str, object]:
    published_at = datetime(2026, 1, 1, tzinfo=UTC)
    return {
        "entry_id": "api-forecast-safety",
        "published_at": published_at.isoformat(),
        "direction": "LONG",
        "asset_code": "000001.SZ",
        "horizon_end": (published_at + timedelta(days=30)).isoformat(),
        "benchmark_asset": "000300.SH",
        "probability": 0.8,
        "invalidation_rule_version": "rule-v1",
        "decision_snapshot_id": "decision-v1",
        "pit_manifest_id": "manifest-v1",
        "source": "strategy",
    }


@pytest.mark.django_db
def test_forecast_entry_api_rejects_unknown_fields(authenticated_client) -> None:
    response = authenticated_client.post(
        "/api/signal/forecast-ledger/",
        {**_entry_payload(), "unexpected": "value"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "Unknown fields: unexpected" in str(response.json())


@pytest.mark.django_db
def test_forecast_evaluation_api_rejects_unsafe_evidence(
    authenticated_client,
) -> None:
    created = authenticated_client.post(
        "/api/signal/forecast-ledger/",
        _entry_payload(),
        content_type="application/json",
    )
    assert created.status_code == 201

    duplicate_versions = authenticated_client.post(
        "/api/signal/forecast-ledger/api-forecast-safety/evaluations/",
        {
            "checked_at": datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
            "data_version_ids": [1, 1],
            "conditions": [],
        },
        content_type="application/json",
    )
    non_boolean_trigger = authenticated_client.post(
        "/api/signal/forecast-ledger/api-forecast-safety/evaluations/",
        {
            "checked_at": datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
            "data_version_ids": [1],
            "conditions": [{"triggered": "yes"}],
        },
        content_type="application/json",
    )

    assert duplicate_versions.status_code == 400
    assert non_boolean_trigger.status_code == 400
