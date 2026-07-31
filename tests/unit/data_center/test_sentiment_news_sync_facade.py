"""Tests for capability-driven market-news synchronization."""

from types import SimpleNamespace

from apps.data_center.application.dtos import SyncResult
from apps.data_center.application.interface_services import sync_market_news_for_sentiment


def test_sentiment_news_sync_selects_active_news_capability(monkeypatch) -> None:
    """Provider selection follows configured capabilities, not a source hardcode."""

    providers = [
        SimpleNamespace(id=1, name="macro-only", source_type="tushare", priority=1),
        SimpleNamespace(id=2, name="news-capable", source_type="akshare", priority=5),
    ]
    captured: list[object] = []

    monkeypatch.setattr(
        "apps.data_center.application.interface_services._make_provider_repo",
        lambda: SimpleNamespace(list_active=lambda: providers),
    )
    monkeypatch.setattr(
        "apps.data_center.application.interface_services.make_sync_news_use_case",
        lambda: SimpleNamespace(
            execute=lambda request: (
                captured.append(request) or SyncResult("news", "news-capable", 8, "success")
            )
        ),
    )

    result = sync_market_news_for_sentiment(limit=100)

    assert result.stored_count == 8
    assert len(captured) == 1
    assert captured[0].provider_id == 2
    assert captured[0].asset_code == ""
    assert captured[0].limit == 100
