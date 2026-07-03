from datetime import date
from types import SimpleNamespace

from apps.data_center.application import interface_services
from apps.data_center.domain.entities import MarketThermometerSnapshot


def test_decision_readiness_falls_back_to_latest_usable_market_thermometer(monkeypatch):
    blocked_snapshot = MarketThermometerSnapshot(
        observed_at=date(2026, 7, 1),
        score=60.83,
        band="hot",
        change_5d=1.97,
        change_20d=28.87,
        valid_component_count=2,
        data_source="degraded",
        must_not_use_for_decision=True,
        blocked_reason="有效组件数不足，当前仅 2 个，低于要求 4 个。",
    )
    usable_snapshot = MarketThermometerSnapshot(
        observed_at=date(2026, 6, 26),
        score=58.86,
        band="warm",
        change_5d=14.72,
        change_20d=6.91,
        valid_component_count=4,
        data_source="degraded",
        must_not_use_for_decision=False,
        blocked_reason="",
    )

    class FakeThermometerRepo:
        def get_latest(self):
            return blocked_snapshot

    class FakeQuoteUseCase:
        def __init__(self, repo):
            self.repo = repo

        def execute(self, request):
            return SimpleNamespace(
                must_not_use_for_decision=False,
                to_dict=lambda: {
                    "asset_code": request.asset_code,
                    "must_not_use_for_decision": False,
                },
            )

    class FakeThermometerUseCase:
        def build_current_payload(self, *, auto_calculate=False):
            assert auto_calculate is False
            payload = usable_snapshot.to_dict()
            payload["status"] = "ok"
            return payload

    monkeypatch.setattr(
        interface_services,
        "MarketThermometerSnapshotRepository",
        FakeThermometerRepo,
    )
    monkeypatch.setattr(
        interface_services,
        "make_calculate_market_thermometer_use_case",
        lambda: FakeThermometerUseCase(),
    )
    monkeypatch.setattr(interface_services, "QueryLatestQuoteUseCase", FakeQuoteUseCase)
    monkeypatch.setattr(interface_services, "QuoteSnapshotRepository", lambda: object())

    payload = interface_services.get_decision_data_readiness_payload(
        asset_codes=["000300.SH"],
        quote_max_age_hours=4.0,
    )

    assert payload["status"] == "ok"
    assert payload["must_not_use_for_decision"] is False
    assert payload["market_thermometer"]["observed_at"] == "2026-06-26"
    assert payload["market_thermometer"]["status"] == "ok"
    assert payload["skipped_latest_market_thermometer"]["observed_at"] == "2026-07-01"
    assert payload["skipped_latest_market_thermometer"]["status"] == "blocked"
    assert (
        payload["skipped_latest_market_thermometer"]["skip_reason"]
        == "latest_snapshot_after_decision_safe_date"
    )


def test_decision_readiness_skips_latest_thermometer_after_safe_date(monkeypatch):
    unsafe_latest_snapshot = MarketThermometerSnapshot(
        observed_at=date(2026, 7, 2),
        score=62.66,
        band="hot",
        change_5d=3.8,
        change_20d=20.65,
        valid_component_count=4,
        data_source="degraded",
        must_not_use_for_decision=False,
        blocked_reason="",
    )
    safe_payload = MarketThermometerSnapshot(
        observed_at=date(2026, 7, 1),
        score=61.06,
        band="hot",
        change_5d=2.68,
        change_20d=19.53,
        valid_component_count=4,
        data_source="degraded",
        must_not_use_for_decision=False,
        blocked_reason="",
    ).to_dict()

    class FakeThermometerRepo:
        def get_latest(self):
            return unsafe_latest_snapshot

    class FakeThermometerUseCase:
        def build_current_payload(self, *, auto_calculate=False):
            assert auto_calculate is False
            return dict(safe_payload)

    class FakeQuoteUseCase:
        def __init__(self, repo):
            self.repo = repo

        def execute(self, request):
            return SimpleNamespace(
                must_not_use_for_decision=False,
                to_dict=lambda: {
                    "asset_code": request.asset_code,
                    "must_not_use_for_decision": False,
                },
            )

    monkeypatch.setattr(
        interface_services,
        "MarketThermometerSnapshotRepository",
        FakeThermometerRepo,
    )
    monkeypatch.setattr(
        interface_services,
        "make_calculate_market_thermometer_use_case",
        lambda: FakeThermometerUseCase(),
    )
    monkeypatch.setattr(interface_services, "QueryLatestQuoteUseCase", FakeQuoteUseCase)
    monkeypatch.setattr(interface_services, "QuoteSnapshotRepository", lambda: object())

    payload = interface_services.get_decision_data_readiness_payload(
        asset_codes=["000300.SH"],
        quote_max_age_hours=4.0,
    )

    assert payload["status"] == "ok"
    assert payload["market_thermometer"]["observed_at"] == "2026-07-01"
    assert payload["market_thermometer"]["status"] == "ok"
    assert payload["skipped_latest_market_thermometer"]["observed_at"] == "2026-07-02"
    assert payload["skipped_latest_market_thermometer"]["status"] == "skipped"
    assert (
        payload["skipped_latest_market_thermometer"]["skip_reason"]
        == "latest_snapshot_after_decision_safe_date"
    )
