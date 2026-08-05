"""Regression coverage for Data Center public current-read ports."""

from __future__ import annotations

from apps.data_center.application.public import (
    get_market_breadth_snapshot,
    get_market_thermometer_payload,
    get_published_latest_quote_payload,
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


def test_published_latest_quote_public_port_preserves_blocked_gate(monkeypatch) -> None:
    """Execution consumers must receive a stable blocked reason from the public port."""

    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_quote_payloads",
        lambda _codes, *, publication_key: {
            "rows": [],
            "publication_id": "pub-1",
            "dataset_key": "equity.quote.snapshot",
            "freshness_status": "stale",
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_stale",
        },
    )

    payload = get_published_latest_quote_payload(" 000001.sz ")

    assert payload == {
        "asset_code": "000001.SZ",
        "is_stale": True,
        "must_not_use_for_decision": True,
        "freshness_status": "stale",
        "blocked_reason": "canonical_publication_stale",
        "publication_id": "pub-1",
        "dataset_key": "equity.quote.snapshot",
    }


def test_published_latest_quote_public_port_returns_member_row_with_gate_metadata(
    monkeypatch,
) -> None:
    """Usable quote rows retain the publication identity and freshness evidence."""

    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_quote_payloads",
        lambda _codes, *, publication_key: {
            "rows": [
                {
                    "asset_code": "000001.SZ",
                    "current_price": 12.3,
                    "snapshot_at": "2026-08-05T07:00:00+00:00",
                }
            ],
            "publication_id": "pub-2",
            "dataset_key": "equity.quote.snapshot",
            "freshness_status": "fresh",
            "must_not_use_for_decision": False,
            "blocked_reason": "",
        },
    )

    payload = get_published_latest_quote_payload("000001.SZ")

    assert payload is not None
    assert payload["current_price"] == 12.3
    assert payload["publication_id"] == "pub-2"
    assert payload["freshness_status"] == "fresh"
    assert payload["must_not_use_for_decision"] is False
    assert payload["is_stale"] is False
