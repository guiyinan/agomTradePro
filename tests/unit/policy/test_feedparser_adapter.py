"""Focused contracts for the typed feedparser infrastructure boundary."""

from datetime import UTC, datetime
from time import struct_time

from apps.policy.infrastructure.adapters.feedparser_adapter import FeedparserAdapter


class _FeedEntry:
    published_parsed = struct_time((2026, 7, 22, 8, 30, 0, 2, 203, 0))
    updated_parsed: struct_time | None = None

    def __init__(self) -> None:
        self._values: dict[str, object] = {
            "title": " Policy update ",
            "link": "https://example.com/policy",
            "description": "summary",
            "guid": 123,
            "author": "publisher",
        }

    def get(self, key: str, default: str = "") -> object:
        return self._values.get(key, default)


def test_parse_entry_normalizes_dynamic_fields_and_uses_aware_utc_date() -> None:
    item = FeedparserAdapter()._parse_entry(_FeedEntry(), "test-feed")

    assert item is not None
    assert item.title == "Policy update"
    assert item.guid == "123"
    assert item.pub_date == datetime(2026, 7, 22, 8, 30, tzinfo=UTC)
    assert item.pub_date.tzinfo is UTC
