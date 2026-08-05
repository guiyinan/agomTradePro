"""Regression coverage for public decision-readiness and coverage ports."""

from __future__ import annotations

from apps.data_center.application.public import (
    get_active_stock_fact_coverage_payload,
    get_decision_data_readiness_payload,
)
from apps.decision_rhythm.application.advisor_providers import DecisionDataHealthProvider


def test_decision_readiness_public_port_forwards_query_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_readiness(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"status": "blocked", "must_not_use_for_decision": True}

    monkeypatch.setattr(
        "apps.data_center.application.interface_services.get_decision_data_readiness_payload",
        _fake_readiness,
    )

    payload = get_decision_data_readiness_payload(
        asset_codes=["000001.SZ"],
        quote_max_age_hours=2.0,
    )

    assert payload["must_not_use_for_decision"] is True
    assert captured == {"asset_codes": ["000001.SZ"], "quote_max_age_hours": 2.0}


def test_stock_fact_coverage_public_port_delegates_to_diagnostic_query(monkeypatch) -> None:
    expected = {"status": "warning", "published_price": {"member_count": 0}}
    monkeypatch.setattr(
        "apps.data_center.application.query_services.get_active_stock_fact_coverage_payload",
        lambda: expected,
    )

    assert get_active_stock_fact_coverage_payload() == expected


def test_decision_rhythm_health_provider_uses_public_readiness_port(monkeypatch) -> None:
    expected = {"status": "ok", "must_not_use_for_decision": False}
    monkeypatch.setattr(
        "apps.data_center.application.public.get_decision_data_readiness_payload",
        lambda **kwargs: expected,
    )

    assert DecisionDataHealthProvider().get_health(asset_codes=["000300.SH"]) == expected
