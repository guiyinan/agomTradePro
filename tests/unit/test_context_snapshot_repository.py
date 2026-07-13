from apps.agent_runtime.infrastructure.context_snapshot_repository import (
    DjangoContextSnapshotRepository,
)


def test_fetch_price_alert_summary_returns_unsupported_when_model_is_absent():
    repository = DjangoContextSnapshotRepository()

    summary = repository.fetch_price_alert_summary()

    assert summary["status"] == "unsupported"
    assert summary["source"] == "realtime"
    assert "PriceAlert" in summary["error"]
