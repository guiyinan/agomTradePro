"""Regression coverage for Data Center public current-read ports."""

from __future__ import annotations

from apps.data_center.application.public import (
    get_market_breadth_snapshot,
    get_market_thermometer_payload,
)


def test_market_thermometer_public_port_forwards_user_scope(monkeypatch) -> None:
    """User threshold scope must remain an explicit public-port parameter."""

    captured: dict[str, object] = {}

    def _fake_loader(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"status": "ok", "observed_at": "2026-08-05T08:00:00+00:00"}

    monkeypatch.setattr(
        "apps.data_center.application.interface_services.load_market_thermometer_payload",
        _fake_loader,
    )

    payload = get_market_thermometer_payload(user_id=7, use_personal_thresholds=True)

    assert payload["status"] == "ok"
    assert captured == {"user_id": 7, "use_personal_thresholds": True}


def test_market_breadth_public_port_delegates_to_governed_query(monkeypatch) -> None:
    """Realtime consumers must receive the Data Center breadth contract."""

    expected = {
        "status": "blocked",
        "must_not_use_for_decision": True,
        "blocked_reason": "canonical_publication_missing",
    }
    monkeypatch.setattr(
        "apps.data_center.application.public.query_published_a_share_behavior_payload",
        lambda: expected,
    )

    assert get_market_breadth_snapshot() == expected
