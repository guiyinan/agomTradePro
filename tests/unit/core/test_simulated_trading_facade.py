from core.integration.simulated_trading_facade import (
    get_simulated_trading_facade_bridge,
)


def test_get_simulated_trading_facade_bridge_uses_simulated_trading_module(
    monkeypatch,
):
    expected = object()
    monkeypatch.setattr(
        "apps.simulated_trading.application.facade.get_simulated_trading_facade",
        lambda: expected,
    )

    assert get_simulated_trading_facade_bridge() is expected
