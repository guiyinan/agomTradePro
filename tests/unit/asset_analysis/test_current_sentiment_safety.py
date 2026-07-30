"""Asset-pool context must fail closed around stale sentiment inputs."""

from types import SimpleNamespace

from apps.asset_analysis.application import interface_services


def test_asset_pool_context_does_not_score_with_stale_sentiment(monkeypatch):
    monkeypatch.setattr(
        interface_services,
        "resolve_current_regime",
        lambda **_: SimpleNamespace(dominant_regime="Recovery"),
    )
    monkeypatch.setattr(
        interface_services,
        "get_current_policy_repository",
        lambda: SimpleNamespace(get_current_policy_level=lambda: SimpleNamespace(value="P1")),
    )
    monkeypatch.setattr(
        interface_services,
        "resolve_current_sentiment",
        lambda: SimpleNamespace(
            index=None,
            must_not_use_for_decision=True,
            blocked_reason="sentiment_index_stale",
            observed_at=None,
            freshness_status="stale",
        ),
    )
    monkeypatch.setattr(
        interface_services,
        "get_signal_context_gateway",
        lambda: SimpleNamespace(list_active_signals=lambda: []),
    )

    payload = interface_services.build_asset_pool_context()

    assert payload.sentiment_index == 0.0
    assert payload.sentiment_must_not_use_for_decision is True
    assert payload.sentiment_blocked_reason == "sentiment_index_stale"
