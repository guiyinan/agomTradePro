from datetime import date
from unittest.mock import call, patch

from agomtradepro import AgomTradeProClient


def _client() -> AgomTradeProClient:
    return AgomTradeProClient(base_url="http://test.com", api_token="test_token")


def test_policy_status_maps_canonical_level_and_latest_event() -> None:
    client = _client()
    response = {
        "current_level": "P2",
        "as_of_date": "2026-07-10",
        "latest_event": {
            "event_date": "2026-07-09",
            "level": "P1",
            "title": "Liquidity operation",
            "description": "Central bank liquidity operation.",
            "evidence_url": "https://example.com/policy",
        },
    }

    with patch.object(client, "get", return_value=response) as mocked:
        status = client.policy.get_status()

    assert status.current_gear == "stimulus"
    assert status.observed_at == date(2026, 7, 10)
    assert len(status.recent_events) == 1
    assert status.recent_events[0].gear == "tightening"
    mocked.assert_called_once_with("/api/policy/status/", params=None)


def test_policy_events_reads_canonical_envelope_and_applies_limit() -> None:
    client = _client()
    response = {
        "events": [
            {
                "event_date": "2026-07-09",
                "level": "P2",
                "title": "Liquidity support",
                "description": "Targeted liquidity support was announced.",
                "evidence_url": "https://example.com/policy/1",
            },
            {
                "event_date": "2026-07-08",
                "level": "P1",
                "title": "Macro-prudential tightening",
                "description": "A tightening measure was announced.",
                "evidence_url": "https://example.com/policy/2",
            },
        ],
        "total_count": 2,
        "start_date": "2026-07-01",
        "end_date": "2026-07-10",
    }

    with patch.object(client, "get", return_value=response) as mocked:
        events = client.policy.get_events(
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 10),
            gear="stimulus",
            limit=1,
        )

    assert len(events) == 1
    assert events[0].event_date == date(2026, 7, 9)
    assert events[0].event_type == "policy"
    assert events[0].gear == "stimulus"
    mocked.assert_called_once_with(
        "/api/policy/events/",
        params={
            "start_date": "2026-07-01",
            "end_date": "2026-07-10",
            "level": "P2",
        },
    )


def test_policy_create_event_posts_canonical_fields() -> None:
    client = _client()
    response = {
        "success": True,
        "event": {
            "event_date": "2026-07-11",
            "level": "P2",
            "title": "Liquidity support",
            "description": "Targeted liquidity support was announced with sufficient detail.",
            "evidence_url": "https://example.com/policy/create",
        },
        "errors": [],
        "warnings": [],
        "alert_triggered": True,
    }

    with patch.object(client, "post", return_value=response) as mocked:
        event = client.policy.create_event(
            date(2026, 7, 11),
            "liquidity_support",
            "Targeted liquidity support was announced with sufficient detail.",
            "stimulus",
            level="P2",
            title="Liquidity support",
            evidence_url="https://example.com/policy/create",
        )

    assert event.event_date == date(2026, 7, 11)
    assert event.description == "Targeted liquidity support was announced with sufficient detail."
    assert event.gear == "stimulus"
    mocked.assert_called_once_with(
        "/api/policy/events/",
        data=None,
        json={
            "event_date": "2026-07-11",
            "level": "P2",
            "title": "Liquidity support",
            "description": "Targeted liquidity support was announced with sufficient detail.",
            "evidence_url": "https://example.com/policy/create",
        },
    )


def test_policy_rss_source_reads_use_canonical_endpoints() -> None:
    client = _client()
    sources = [
        {
            "id": 3,
            "name": "Policy Feed",
            "category": "central_bank",
            "is_active": True,
        }
    ]

    with patch.object(client, "get", side_effect=[sources, sources[0]]) as mocked:
        catalog = client.policy.list_rss_sources(is_active=True)
        detail = client.policy.get_rss_source(3)

    assert catalog == sources
    assert detail == sources[0]
    assert mocked.call_args_list == [
        call("/api/policy/rss/sources/", params={"is_active": "true"}),
        call("/api/policy/rss/sources/3/", params=None),
    ]


def test_policy_trigger_fetch_uses_synchronous_canonical_endpoint() -> None:
    client = _client()
    response = {
        "success": True,
        "mode": "single",
        "sources_processed": 1,
        "total_items": 2,
        "new_policy_events": 1,
        "errors": [],
        "details": [],
    }

    with patch.object(client, "post", return_value=response) as mocked:
        result = client.policy.trigger_fetch(source_id=3, force_refetch=True)

    assert result == response
    mocked.assert_called_once_with(
        "/api/policy/workbench/fetch/",
        data=None,
        json={"source_id": 3, "force_refetch": True},
    )
