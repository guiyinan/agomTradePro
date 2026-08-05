"""Contracts for the Data Center-owned RSS transport."""

from __future__ import annotations

from datetime import UTC, datetime
from time import struct_time
from types import SimpleNamespace

import pytest

from apps.data_center.infrastructure import rss_gateway


class _Entry:
    published_parsed: struct_time | None
    updated_parsed: struct_time | None = None

    def __init__(self, *, title: str, link: str, published: struct_time | None) -> None:
        self.published_parsed = published
        self._values = {
            "title": title,
            "link": link,
            "description": "policy summary",
            "guid": "guid-1",
            "author": "publisher",
        }

    def get(self, key: str, default: str = "") -> object:
        return self._values.get(key, default)


def test_rss_gateway_preserves_source_time_and_fetch_time(monkeypatch: pytest.MonkeyPatch) -> None:
    response = SimpleNamespace(content=b"<rss/>", raise_for_status=lambda: None)
    published = struct_time((2026, 7, 22, 8, 30, 0, 2, 203, 0))
    entry = _Entry(title="Policy update", link="https://example.test/item", published=published)
    monkeypatch.setattr(rss_gateway.requests, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(
        rss_gateway,
        "import_module",
        lambda name: SimpleNamespace(
            parse=lambda content: SimpleNamespace(
                bozo=False,
                bozo_exception=None,
                entries=[entry],
            )
        ),
    )

    facts = rss_gateway.fetch_rss_feed(url="https://example.test/feed", source_name="policy")

    assert len(facts) == 1
    assert facts[0].published_at == datetime(2026, 7, 22, 8, 30, tzinfo=UTC)
    assert facts[0].fetched_at.tzinfo is UTC
    assert facts[0].title == "Policy update"
    assert facts[0].external_id == "guid-1"


def test_rss_gateway_drops_items_without_observed_time(monkeypatch: pytest.MonkeyPatch) -> None:
    response = SimpleNamespace(content=b"<rss/>", raise_for_status=lambda: None)
    entry = _Entry(title="No timestamp", link="https://example.test/item", published=None)
    monkeypatch.setattr(rss_gateway.requests, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(
        rss_gateway,
        "import_module",
        lambda name: SimpleNamespace(
            parse=lambda content: SimpleNamespace(
                bozo=False,
                bozo_exception=None,
                entries=[entry],
            )
        ),
    )

    assert rss_gateway.fetch_rss_feed(url="https://example.test/feed", source_name="policy") == []


def test_rss_gateway_rejects_credentialed_urls() -> None:
    with pytest.raises(ValueError, match="must not contain credentials"):
        rss_gateway.fetch_rss_feed(
            url="https://user:secret@example.test/feed",
            source_name="policy",
        )


def test_rss_gateway_probe_uses_bounded_transport_without_parser(monkeypatch) -> None:
    response = SimpleNamespace(content=b"<rss/>", raise_for_status=lambda: None)
    calls: list[dict[str, object]] = []

    def _get(*args, **kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(rss_gateway.requests, "get", _get)

    rss_gateway.probe_rss_feed(
        url="https://example.test/feed",
        source_name="policy",
        timeout_seconds=7,
        retry_times=1,
    )

    assert calls == [
        {"proxies": None, "headers": {"User-Agent": "AgomTradePro-RSS-Bot/1.0"}, "timeout": 7}
    ]
