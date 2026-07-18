import pytest

from apps.agent_runtime.infrastructure.context_snapshot_repository import (
    DjangoContextSnapshotRepository,
)


@pytest.mark.django_db
def test_fetch_price_alert_summary_uses_current_realtime_model():
    repository = DjangoContextSnapshotRepository()

    summary = repository.fetch_price_alert_summary()

    assert summary == {
        "status": "ok",
        "active_price_alerts": 0,
        "triggered_price_alerts": 0,
    }


@pytest.mark.django_db
def test_context_snapshot_sources_use_real_orm_models_without_degrading():
    """Exercise the default repository wiring instead of fake source adapters."""

    repository = DjangoContextSnapshotRepository()
    summaries = {
        "regime": repository.fetch_regime_summary(),
        "policy": repository.fetch_policy_summary(),
        "portfolio": repository.fetch_portfolio_summary(),
        "signals": repository.fetch_active_signals_summary(),
        "decisions": repository.fetch_open_decisions_summary(),
        "risk": repository.fetch_risk_alerts_summary(),
        "freshness": repository.fetch_data_freshness_summary(),
        "events": repository.fetch_event_bus_summary(),
        "providers": repository.fetch_ai_provider_summary(),
        "audit": repository.fetch_audit_freshness_summary(),
        "price_alerts": repository.fetch_price_alert_summary(),
        "sentiment": repository.fetch_sentiment_freshness_summary(),
        "quotas": repository.fetch_decision_quota_summary(),
        "pending_signals": repository.fetch_pending_signal_summary(),
        "simulated_accounts": repository.fetch_simulated_account_summary(),
        "regime_history": repository.fetch_regime_history_summary(),
        "signal_invalidation": repository.fetch_signal_invalidation_summary(),
    }

    degraded = {
        name: summary
        for name, summary in summaries.items()
        if summary.get("status") in {"unavailable", "unsupported"}
    }
    assert degraded == {}
