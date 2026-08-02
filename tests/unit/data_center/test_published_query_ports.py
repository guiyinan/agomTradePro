"""Publication-only query port contracts for D7-D9."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from apps.data_center.application import query_services
from apps.data_center.domain.entities import (
    CapitalFlowFact,
    NewsFact,
    SectorMembershipFact,
)


def _publication() -> SimpleNamespace:
    """Return the minimum publication metadata used by the query gate."""

    return SimpleNamespace(
        publication_id="pub-2026-08-02",
        published_at=datetime(2026, 8, 2, tzinfo=UTC),
        must_not_use_for_decision=False,
        blocked_reason="",
    )


def test_published_sector_memberships_fail_closed_without_publication(monkeypatch) -> None:
    """Canonical rows must not leak when the current sector publication is absent."""

    publication_repo = SimpleNamespace(get_current=lambda *_args: None)
    repository = SimpleNamespace(
        get_members=lambda *_args: [
            SectorMembershipFact(
                asset_code="600000.SH",
                sector_code="SW1_BANK",
                sector_name="银行",
                effective_date=date(2026, 1, 1),
                expiry_date=None,
                source="test",
            )
        ]
    )
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publication_repo
    )
    monkeypatch.setattr(query_services, "get_sector_membership_repository", lambda: repository)

    result = query_services.query_published_sector_memberships("SW1_BANK")

    assert result["rows"] == []
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == "canonical_publication_missing"


def test_published_news_and_capital_flow_preserve_publication_evidence(monkeypatch) -> None:
    """D8/D9 ports return canonical rows together with the selected publication."""

    publication_repo = SimpleNamespace(get_current=lambda *_args: _publication())
    news = NewsFact(
        asset_code="",
        title="Market",
        summary="Summary",
        url="https://example.test/news",
        published_at=datetime(2026, 8, 2, tzinfo=UTC),
        source="test",
        external_id="news-1",
    )
    flow = CapitalFlowFact(
        asset_code="600000.SH",
        flow_date=date(2026, 8, 1),
        main_net=1.0,
        source="test",
    )
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publication_repo
    )
    monkeypatch.setattr(
        query_services,
        "get_news_repository",
        lambda: SimpleNamespace(list_market_news_for_date=lambda *_args, **_kwargs: [news]),
    )
    monkeypatch.setattr(
        query_services,
        "get_capital_flow_repository",
        lambda: SimpleNamespace(get_series=lambda *_args, **_kwargs: [flow]),
    )

    news_result = query_services.query_published_market_news(target_date=date(2026, 8, 2))
    flow_result = query_services.query_published_capital_flow_series("600000.SH", limit=20)

    assert len(news_result["rows"]) == 1
    assert len(flow_result["rows"]) == 1
    assert news_result["publication_id"] == "pub-2026-08-02"
    assert flow_result["must_not_use_for_decision"] is False


def test_published_capital_flow_blocks_before_querying_repository(monkeypatch) -> None:
    """A blocked D9 read must not spend a query on the canonical fact table."""

    publication_repo = SimpleNamespace(get_current=lambda *_args: None)
    repository = SimpleNamespace(
        get_series=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError)
    )
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publication_repo
    )
    monkeypatch.setattr(query_services, "get_capital_flow_repository", lambda: repository)

    result = query_services.query_published_capital_flow_series("600000.SH")

    assert result["rows"] == []
    assert result["blocked_reason"] == "canonical_publication_missing"
