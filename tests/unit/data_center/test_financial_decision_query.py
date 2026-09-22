"""Point-in-time contracts for financial decision reads."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from apps.data_center.application import public_published_queries


def test_date_only_decision_uses_china_market_day_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A date-only caller gets one exact, conservative knowledge instant."""

    captured: dict[str, object] = {}

    def _query(asset_code: str, **kwargs: object) -> list[dict[str, object]]:
        captured.update(asset_code=asset_code, **kwargs)
        return []

    monkeypatch.setattr(public_published_queries, "query_financial_facts", _query)

    rows = public_published_queries.get_financial_facts_for_decision(
        "600000.SH",
        decision_date=date(2026, 8, 9),
        limit=30,
    )

    assert rows == []
    assert captured == {
        "asset_code": "600000.SH",
        "limit": 30,
        "end": date(2026, 8, 9),
        "knowledge_cutoff": datetime(2026, 8, 8, 16, tzinfo=UTC),
    }
