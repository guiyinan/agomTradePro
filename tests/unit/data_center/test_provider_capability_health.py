"""Provider capability health must include recency and output evidence."""

from datetime import UTC, datetime, timedelta

from apps.data_center.application.provider_health import build_capability_health_payload

NOW = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)


def test_provider_capability_without_success_is_unhealthy() -> None:
    payload = build_capability_health_payload(
        {"provider_name": "tushare", "capability": "financial", "status": "healthy"},
        {},
        now=NOW,
    )

    assert payload["status"] == "unhealthy"
    assert payload["must_not_use_for_decision"] is True
    assert payload["block_reason_code"] == "provider_capability_never_succeeded"


def test_provider_capability_old_success_cannot_remain_healthy() -> None:
    payload = build_capability_health_payload(
        {"provider_name": "tushare", "capability": "valuation", "status": "healthy"},
        {
            "health_metrics": {
                "valuation": {"last_success_at": (NOW - timedelta(days=10)).isoformat()}
            },
            "health_max_age_hours": {"valuation": 72},
        },
        now=NOW,
    )

    assert payload["status"] == "stale"
    assert payload["must_not_use_for_decision"] is True


def test_provider_capability_recent_success_is_healthy() -> None:
    payload = build_capability_health_payload(
        {"provider_name": "tushare", "capability": "financial", "status": "healthy"},
        {
            "health_metrics": {
                "financial": {"last_success_at": (NOW - timedelta(hours=2)).isoformat()}
            },
            "health_max_age_hours": {"financial": 24},
        },
        now=NOW,
    )

    assert payload["status"] == "healthy"
    assert payload["must_not_use_for_decision"] is False
    assert payload["success_age_hours"] == 2.0


def test_dataset_keyed_health_evidence_overrides_legacy_capability_key() -> None:
    """Provider health must not merge two capabilities into one dataset slot."""

    payload = build_capability_health_payload(
        {
            "provider_name": "tushare",
            "capability": "financial",
            "dataset_key": "equity.financial.fact",
            "status": "healthy",
        },
        {
            "health_metrics": {
                "financial": {"last_success_at": (NOW - timedelta(days=10)).isoformat()}
            },
            "health_metrics_by_dataset": {
                "equity.financial.fact": {"last_success_at": (NOW - timedelta(hours=1)).isoformat()}
            },
            "health_max_age_hours_by_dataset": {"equity.financial.fact": 24},
        },
        now=NOW,
    )

    assert payload["dataset_key"] == "equity.financial.fact"
    assert payload["status"] == "healthy"
    assert payload["must_not_use_for_decision"] is False
