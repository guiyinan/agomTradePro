from core.integration.manual_trade_sync import get_manual_trade_sync_repository


def test_manual_trade_sync_repository_bridge(monkeypatch):
    sentinel = object()

    monkeypatch.setattr(
        "apps.account.application.repository_provider.get_manual_trade_sync_repository",
        lambda: sentinel,
    )

    assert get_manual_trade_sync_repository() is sentinel
