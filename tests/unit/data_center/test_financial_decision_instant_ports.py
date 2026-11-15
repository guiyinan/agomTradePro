"""Exact financial decision instants must survive the public read boundary."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from apps.data_center.application import public
from apps.data_center.application import public_published_queries as queries
from core.exceptions import DataValidationError

OPEN = datetime(2026, 11, 13, 1, 30, tzinfo=UTC)
ROW = {"asset_code": "000001.SZ", "available_at": OPEN.isoformat(), "value": 12}


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    # The compatibility shim copies public monkeypatches into this module.
    # Register the original split function so teardown restores both surfaces.
    monkeypatch.setattr(
        queries, "get_published_financial_facts", queries.get_published_financial_facts
    )
    monkeypatch.setattr("django.utils.timezone.now", lambda: OPEN + timedelta(days=2))


@pytest.mark.parametrize("published", [False, True])
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_explicit_instant_preserves_open_boundary(monkeypatch, published, offset):
    calls = []

    def query(_asset, **kwargs):
        calls.append(kwargs)
        rows = [ROW] if kwargs["knowledge_cutoff"] >= OPEN else []
        if published:
            return {
                "rows": rows,
                "dataset_key": "equity.financial.fact",
                "publication_id": "p1",
                "must_not_use_for_decision": False,
            }
        return rows

    target = "get_published_financial_facts" if published else "query_financial_facts"
    monkeypatch.setattr(public if published else queries, target, query)
    port_name = (
        "get_published_financial_facts_for_decision_at"
        if published
        else "get_financial_facts_for_decision_at"
    )
    port = getattr(public, port_name)
    cutoff = OPEN + timedelta(microseconds=offset)
    result = port("000001.SZ", decision_at=cutoff, limit=7)
    assert result == ([ROW] if offset >= 0 else [])
    assert calls[0]["knowledge_cutoff"] == cutoff
    assert calls[0]["as_of" if published else "end"] == date(2026, 11, 13)
    assert calls[0]["limit"] == 7


@pytest.mark.parametrize("published", [False, True])
def test_instant_normalizes_timezone_and_uses_shanghai_date(monkeypatch, published):
    calls = []

    def query(_asset, **kwargs):
        calls.append(kwargs)
        return (
            {"rows": [], "dataset_key": "equity.financial.fact", "publication_id": "p1"}
            if published
            else []
        )

    monkeypatch.setattr(
        public if published else queries,
        "get_published_financial_facts" if published else "query_financial_facts",
        query,
    )
    cutoff = datetime(2026, 11, 13, 0, 15, tzinfo=timezone(timedelta(hours=8)))
    port = getattr(
        public,
        (
            "get_published_financial_facts_for_decision_at"
            if published
            else "get_financial_facts_for_decision_at"
        ),
    )
    port("000001.SZ", decision_at=cutoff)
    assert calls[0]["knowledge_cutoff"] == datetime(2026, 11, 12, 16, 15, tzinfo=UTC)
    assert calls[0]["knowledge_cutoff"].utcoffset() == timedelta(0)
    assert calls[0]["as_of" if published else "end"] == date(2026, 11, 13)


@pytest.mark.parametrize("published", [False, True])
@pytest.mark.parametrize(
    "bad", [datetime(2026, 11, 13), date(2026, 11, 13), None, OPEN + timedelta(days=3)]
)
def test_invalid_or_future_cutoff_stops_before_query(monkeypatch, published, bad):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid cutoff reached the query")

    monkeypatch.setattr(
        public if published else queries,
        "get_published_financial_facts" if published else "query_financial_facts",
        forbidden,
    )
    port = getattr(
        public,
        (
            "get_published_financial_facts_for_decision_at"
            if published
            else "get_financial_facts_for_decision_at"
        ),
    )
    with pytest.raises(DataValidationError) as caught:
        port("000001.SZ", decision_at=bad)
    assert caught.value.code in {
        "FINANCIAL_DECISION_TIME_INVALID",
        "FINANCIAL_DECISION_TIME_FUTURE",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {
            "rows": [ROW],
            "dataset_key": "equity.financial.fact",
            "publication_id": "p1",
            "must_not_use_for_decision": True,
        },
        {"rows": [ROW], "dataset_key": "equity.financial.fact"},
        {"rows": [ROW], "dataset_key": "equity.valuation.fact", "publication_id": "p1"},
    ],
)
def test_explicit_instant_cannot_bypass_publication_gate(monkeypatch, payload):
    monkeypatch.setattr(public, "get_published_financial_facts", lambda *args, **kwargs: payload)
    assert public.get_published_financial_facts_for_decision_at("000001.SZ", decision_at=OPEN) == []


@pytest.mark.parametrize("published", [False, True])
def test_legacy_date_port_keeps_midnight_cutoff(monkeypatch, published):
    calls = []

    def query(_asset, **kwargs):
        calls.append(kwargs)
        return (
            {"rows": [], "dataset_key": "equity.financial.fact", "publication_id": "p1"}
            if published
            else []
        )

    monkeypatch.setattr(
        queries, "get_published_financial_facts" if published else "query_financial_facts", query
    )
    port = (
        queries.get_published_financial_facts_for_decision
        if published
        else queries.get_financial_facts_for_decision
    )
    assert port("000001.SZ", decision_date=date(2026, 11, 13)) == []
    assert calls[0]["knowledge_cutoff"] == datetime(2026, 11, 12, 16, tzinfo=UTC)


def test_explicit_port_preserves_publication_key_at_server_clock(monkeypatch):
    calls = []

    def query(_asset, **kwargs):
        calls.append(kwargs)
        return {"rows": [ROW], "dataset_key": "equity.financial.fact", "publication_id": "p1"}

    monkeypatch.setattr(public, "get_published_financial_facts", query)
    cutoff = OPEN + timedelta(days=2)
    assert public.get_published_financial_facts_for_decision_at(
        "000001.SZ", decision_at=cutoff, publication_key="retained-key"
    ) == [ROW]
    assert calls[0]["publication_key"] == "retained-key"
    assert calls[0]["knowledge_cutoff"] == cutoff
