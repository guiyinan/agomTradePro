from apps.realtime.infrastructure.repositories import DatabaseWatchlistProvider


def test_database_watchlist_provider_uses_simulated_position_query_service(monkeypatch):
    monkeypatch.setattr(
        "apps.realtime.infrastructure.repositories._list_held_asset_codes",
        lambda: ["510300.SH", "159915.SZ"],
    )

    provider = DatabaseWatchlistProvider()

    assert provider.get_held_assets() == ["510300.SH", "159915.SZ"]


def test_database_watchlist_provider_uses_asset_analysis_query_service(monkeypatch):
    monkeypatch.setattr(
        "apps.realtime.infrastructure.repositories.list_active_watchlist_asset_codes",
        lambda: ["000001.SZ", "510300.OF"],
    )

    provider = DatabaseWatchlistProvider()

    assert provider.get_watchlist_assets() == ["000001.SZ", "510300.OF"]
